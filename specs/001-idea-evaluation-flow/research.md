# Phase 0 Research: Guided Idea Evaluation Flow

Every unknown from the Technical Context is resolved below. Items marked **Verify at build time**
are settled in principle but have one fact that must be confirmed against live Anthropic docs
during implementation rather than recalled here.

## 1. Two-step conversation without server state

**Decision**: The HTTP API is stateless. The browser owns the session and sends the full round
history with each request; the server assembles the Anthropic `messages` array from it, calls the
model, and returns the new round. Nothing about a session is retained server-side after the
response is written.

**Rationale**: FR-018 requires the session to survive a reload with no server-side storage and no
visitor identity, and the constitution forbids adding a database. A stateless API is also what
makes the CLI and the HTTP surface trivially share one core function, satisfying the
CLI/API-parity constraint.

**Alternatives considered**: A server-side session cache with a TTL — rejected because it is
storage by another name, needs eviction and a privacy story, and buys nothing the client cannot
do. Server-Sent Events with a persistent connection — rejected for v1; it solves progress
reporting, not state, and a visible in-progress indicator meets FR-019 without it.

## 2. Carrying attachments across rounds

**Decision**: Attachments are uploaded once to the Anthropic Files API. The returned `file_id`
goes back to the browser, which stores it in the session and re-sends it on every later round.
Raw bytes cross the wire exactly once. When the founder clears the session, the client asks the
API to delete those file ids.

**Rationale**: Re-sending 10 MB images on every round would multiply both bandwidth and input
tokens, and would collide with the request-size limit for inline base64 documents (32 MB per
request, well under 5 × 10 MB). File ids also keep the client-held session small enough for
IndexedDB without storing file bytes in the browser.

**Risk to flag to the owner**: attachment bytes are held by Anthropic for the life of the session.
That is a third-party retention surface the spec's "no server-side storage" assumption does not
by itself cover. Mitigation: delete on session clear, and say so in the UI near the upload control.

**Alternatives considered**: Inline base64 on every round — rejected on cost and the size limit.
Storing file bytes in IndexedDB and re-uploading each round — rejected; same token cost, more
client complexity.

## 3. Structured output alongside live web search

**Decision**: Request the verdict in one call that declares the web search server tool and sets
`output_config.format` to the `VerdictReport` JSON schema, with adaptive thinking. A contract test
run against the live API confirms the combination is accepted. If it is not, fall back to the
documented two-call shape: a research-and-reason call with web search, then a cheap formatting
call that parses the reasoning into the schema.

**Rationale**: One call is cheaper, faster, and keeps the reasoning and the formatting in the same
context. Naming the fallback now means discovering an incompatibility costs a test, not a redesign.

**Verify at build time**: that `output_config.format` and a server tool can be combined on
`claude-opus-5`. Note the related known constraint — document `citations` are incompatible with
`output_config.format`, which is why sources are collected from search result blocks instead (§4).

**Alternatives considered**: Strict tool use as the output contract — rejected; structured outputs
is the documented path for "I want JSON back", and the report is not a tool call.

## 4. Making sources inspectable (FR-015)

**Decision**: Collect source URLs and titles from the `web_search_tool_result` blocks in the
response content, and return them alongside the parsed report as a `sources` list the UI renders.
Do not use document citations.

**Rationale**: Citations cannot be combined with structured outputs, and the requirement is that a
founder can trace a named competitor to where it came from — a list of what the evaluation
actually read satisfies that. Search result blocks carry it without extra cost.

**Alternatives considered**: A second call asking the model to list its sources — rejected as both
expensive and unfaithful, since it could invent a citation after the fact.

## 5. Degraded research (FR-016)

**Decision**: Treat search failure as data, not an exception. Server-tool errors arrive as an HTTP
200 whose result block content is an error object rather than a list, so `claude.py` inspects each
`web_search_tool_result` block, records a `ResearchStatus` of `ok`, `degraded`, or `unavailable`,
and passes it into the response. A verdict is still produced and rendered, with the UI marking
affected claims unverified and showing a banner.

**Rationale**: FR-016 requires a verdict even when research fails, and an exception-based design
would produce exactly the failure page the requirement forbids.

**Alternatives considered**: Retrying the round on search failure — rejected; it doubles cost for
an outcome the requirement already defines as acceptable.

## 6. Bounding research cost (FR-017, Principle III)

**Decision**: Cap the web search tool with `max_uses` (default 8, env-overridable). Before each
call, count tokens for the assembled request and project a cost; refuse with a typed
`BudgetExceeded` error if projected cost would push the round over $1.50 or the session over
$5.00. After the call, record actual cost from `usage` plus the per-search charge and return it.

**Rationale**: Principle III demands a ceiling enforced in code, and live research is the one part
of this feature whose cost is not bounded by the prompt length.

**Verify at build time**: the current per-search price of the web search tool, from the live
pricing page. `pricing.py` gets a named constant with that value; it is not guessed here.

**Alternatives considered**: Post-hoc accounting only — rejected; the constitution requires a run
that would exceed the ceiling to stop rather than complete and bill.

## 7. Attachment conversion

**Decision**: Images (PNG, JPG) and PDFs are referenced as native image and document content
blocks by `file_id`. XLSX is converted server-side with `openpyxl` to a compact text rendering
(one section per sheet, header row preserved, cells tab-separated), CSV and TXT/MD are passed as
text. Conversion happens once at upload; the text is returned to the client as part of the
attachment record so later rounds re-send text rather than re-converting.

**Rationale**: The API reads images and PDFs natively; spreadsheets it does not. A text rendering
is also what makes numbers quotable in the verdict.

**Alternatives considered**: Converting XLSX to CSV via pandas — rejected; a far heavier
dependency for one conversion. Screenshotting spreadsheets — rejected as lossy and absurd.

## 8. Model, effort, and thinking

**Decision**: `claude-opus-5` for both phases (already the configured default). Adaptive thinking
on both. Effort `medium` for the question round, `high` for the verdict round, both in `Settings`.
Calls are streamed internally and finalized with the SDK's final-message helper, so a long verdict
round cannot trip an HTTP timeout.

**Rationale**: The prompt asks for genuine reasoning and self-rechecking; the question round is a
much lighter task and does not need the same effort. Streaming is the documented defence against
timeouts on long, high-`max_tokens` requests.

**Alternatives considered**: A cheaper model for the question round — rejected for v1; question
quality is what the whole verdict rests on. It stays available as a config change.

## 9. Prompt caching across rounds

**Decision**: Put the interrogator prompt in a cached system block and keep the round history
append-only, so each later round reads the prefix from cache. Never rewrite earlier rounds.

**Rationale**: A four-round session re-sends the whole transcript each time; caching the stable
prefix is the single largest cost saving available and costs one parameter.

**Alternatives considered**: No caching — rejected; it wastes money for nothing.

## 10. Prompt-injection defence (FR-028, SC-011)

**Decision**: Founder text, extracted file text, and retrieved web content are all wrapped in
clearly delimited data blocks whose framing states they are material to be evaluated, never
instructions. The system prompt asserts that the verdict format and rules cannot be altered by
anything inside those blocks. Eval cases cover an idea, an attachment, and a retrieved page that
each attempt to force a PROCEED.

**Rationale**: Web search widens the injection surface beyond what the spec first assumed —
retrieved pages are attacker-controlled in a way the founder's own text is not.

**Alternatives considered**: Stripping suspicious phrases from inputs — rejected; brittle, and it
mutates the material the founder asked to have evaluated.

## 11. Browser session storage

**Decision**: IndexedDB, one record per session, holding the idea, every round, attachment
metadata with file ids, and cumulative cost. `localStorage` is used only for trivial UI state.

**Rationale**: `localStorage` is a ~5 MB string store and would be tight even without file bytes;
IndexedDB is browser-native, needs no dependency, and matches the constitution's UI constraint.

**Alternatives considered**: `localStorage` with the transcript only — viable but fragile as
sessions grow; IndexedDB costs a few dozen lines more and removes the worry.

## 12. Replacing the scaffolded schema and UI

**Decision**: Delete `IdeaEvaluation`, `DimensionScore`, `Risk`, `EvaluationResult`, and the
`DIMENSIONS` tuple from `schemas.py`; keep and extend `Usage` and `JudgeVerdict`. Rebuild
`web/index.html` and `web/app.js` on the design committed in `24969dd`, keeping its 90s chrome in
`styles.css` and restructuring the page into an idea pane and a conversation pane. The score
block, the dimension table and the `.meter` rules go; the "Ask The Analyst" chat becomes the main
surface rather than a step-3 extra. Bump `BIE_PROMPT_VERSION` default to `v3`.

**Rationale**: The scaffold implements a scored one-shot evaluation that the owner's prompt
explicitly does not do. Leaving it in place would mean two contradictory contracts in one package.

**Alternatives considered**: Keeping the scorer behind a flag — rejected; nothing in the spec asks
for scores, and it would double the eval surface.
