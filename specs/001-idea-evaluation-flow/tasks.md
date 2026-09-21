---

description: "Task list for Guided Idea Evaluation Flow"
---

# Tasks: Guided Idea Evaluation Flow

**Input**: Design documents from `/specs/001-idea-evaluation-flow/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, evaluation-prompt.md

**Tests**: Included and mandatory. The project constitution makes test-first development
non-negotiable (Principle I): every test task MUST be written and observed failing before the
implementation task that follows it. A task that produces implementation code with no preceding
failing test is not done, it is to be redone.

**Organization**: Grouped by user story so each can be implemented, tested, and demoed on its own.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1, US2, US3 — maps to the user stories in spec.md
- Exact file paths are given in every task

## Path Conventions

Single Python project: `src/bie/`, `tests/`, `evals/`, `web/` at the repository root, per plan.md.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Dependencies and test scaffolding so the first failing test can be written.

- [X] T001 Add `openpyxl>=3.1` and `python-multipart>=0.0.9` to `[project.dependencies]` in pyproject.toml, and add `markers = ["live: hits the real Anthropic API and costs money"]` to `[tool.pytest.ini_options]`
- [X] T002 [P] Create the test package structure `tests/__init__.py`, `tests/unit/__init__.py`, `tests/contract/__init__.py`, `tests/integration/__init__.py`, plus `tests/conftest.py` holding a `fake_anthropic` fixture (a stub client returning canned `Message` objects) and a `tmp_attachments` fixture producing a small XLSX, PNG, CSV and PDF
- [X] T003 [P] Create `evals/__init__.py` and the empty `evals/cases/` directory with a README explaining the case format
- [X] T004 [P] Extend .env.example with every new setting: `BIE_MIN_IDEA_CHARS`, `BIE_QUESTION_EFFORT`, `BIE_VERDICT_EFFORT`, `BIE_MAX_SEARCHES`, `BIE_MAX_COST_PER_ROUND_USD`, `BIE_MAX_COST_PER_SESSION_USD`, `BIE_MAX_ATTACHMENTS`, `BIE_MAX_ATTACHMENT_MB`, each with its default as the commented value

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The schemas, config, cost control, prompt, error taxonomy and model-call layer that
every user story sits on.

**⚠️ CRITICAL**: No user story work begins until this phase is complete.

- [X] T005 [P] Write failing tests in tests/unit/test_config.py: defaults (`prompt_version` is `"v3"`, `max_cost_per_round_usd` is `1.50`, `max_cost_per_session_usd` is `5.00`, `max_searches` is `8`, `max_attachments` is `5`, `max_attachment_mb` is `10`, `min_idea_chars` is `40`, `question_effort` is `"medium"`, `verdict_effort` is `"high"`), env-var override for each, and `ValueError` at construction for an effort outside `EFFORTS` or a non-positive ceiling
- [X] T006 Extend `Settings` in src/bie/config.py to satisfy T005, keeping the existing frozen dataclass style and `__post_init__` validation (Principle V: no value read anywhere but here)
- [X] T007 [P] Write failing tests in tests/unit/test_schemas.py covering every rule in data-model.md verbatim: `Question.number` ≥ 1 and contiguous from 1 within a set; `QuestionSet.questions` holds 3–10 items; a re-ask requires a non-empty `note`; question text containing a verdict word is rejected (FR-004); `verdict_condition` is required when `verdict` is `PROCEED_ONLY_AFTER_TESTING` and must be null otherwise (FR-007); `works_because` and `fails_because` each hold exactly 3 items (FR-008); `FailureMode.rank` is 1–3; `ValidationPlan.duration_days` is 1–14 and `requires_code` must be `False`; `research_directions` 1–6; `kill_criteria` 1–5; `word_count` ≤ 750
- [X] T008 Rewrite src/bie/schemas.py per data-model.md: delete `IdeaEvaluation`, `DimensionScore`, `Risk`, `EvaluationResult` and the `DIMENSIONS` tuple; add the `RoundKind`, `Confidence`, `VerdictKind`, `ResearchStatus`, `AttachmentKind` and `QuestionTopic` literals and the `Question`, `QuestionSet`, `FailureMode`, `ValidationPlan`, `ResearchDirection`, `VerdictReport`, `Source`, `Attachment` and `Round` models; keep `Usage` (adding `web_searches: int = 0`) and `JudgeVerdict`
- [X] T009 [P] Write failing tests in tests/unit/test_pricing.py for the web-search charge: `cost_usd(...)` unchanged for zero searches, and a run with N searches costs tokens plus N × the per-search constant
- [X] T010 Add a named `WEB_SEARCH_COST_PER_SEARCH_USD` constant to src/bie/pricing.py and extend `cost_usd()` with a `web_searches: int = 0` parameter. **Confirm the current per-search price from the live Anthropic pricing page before setting it** (research.md §6) — do not guess the number
- [X] T011 [P] Write failing tests in tests/unit/test_budget.py: a projected cost under the round ceiling passes; over it raises `BudgetExceeded` carrying the projected cost and the ceiling; cumulative session cost over `max_cost_per_session_usd` raises before the call; actual cost is recorded after the call
- [X] T012 Implement src/bie/budget.py with `project_round_cost()` (uses `client.messages.count_tokens` for input, `max_tokens` and `max_searches` for the worst case), `check_round()` and `check_session()` raising `BudgetExceeded` (Principle III: refuse before spending, never after)
- [X] T013 [P] Write failing tests in tests/unit/test_errors.py asserting every error class exposes a stable `code` and `retryable` flag matching the envelope in contracts/http-api.md (`idea_too_short`, `attachment_rejected`, `budget_exceeded`, `invalid_model_output`, `upstream_error`, `upstream_timeout`, `rate_limited`)
- [X] T014 Implement src/bie/errors.py with a `BieError` base and the seven subclasses, each carrying a founder-facing message separate from the internal detail (FR-029)
- [X] T015 [P] Write failing tests in tests/unit/test_prompts.py: the loader returns the text for `v3`, raises for an unknown version, and the loaded prompt contains the STEP 1 / STEP 2 structure and the RULES block from specs/001-idea-evaluation-flow/evaluation-prompt.md
- [X] T016 Create src/bie/prompts/v3_interrogator.md from specs/001-idea-evaluation-flow/evaluation-prompt.md — owner's wording preserved — split into a system prompt plus per-phase framing, with the injection-hardening statement from research.md §10 that nothing inside a delimited data block can alter the format or the rules; add src/bie/prompts/__init__.py with `load(version: str) -> str` reading from this directory
- [X] T017 Write failing tests in tests/unit/test_claude.py using the `fake_anthropic` fixture: `Usage` is mapped from an SDK response including `web_searches`; sources are extracted from `web_search_tool_result` blocks; a result block whose content is an error object yields `ResearchStatus.degraded` rather than raising (research.md §5); no search blocks at all yields `unavailable`; a reply that fails schema validation raises `InvalidModelOutput`; SDK `RateLimitError`, `APITimeoutError` and `APIStatusError` are translated to the matching `BieError`
- [X] T018 Implement src/bie/claude.py: client factory reading credentials from the environment, one `call()` path that streams and finalises via the SDK helper (plan.md performance constraint), `model` and `output_config.effort` from `Settings`, adaptive thinking, the `web_search_20260209` server tool capped by `max_uses`, `output_config.format` carrying the target Pydantic schema, a cached system block with the round history kept append-only (research.md §9), plus usage mapping, source extraction and error translation
- [X] T019 Write the live integration test tests/integration/test_structured_output_with_search.py, marked `live`, that sends one real `claude-opus-5` request combining `output_config.format` with the web search tool and asserts a schema-valid parse — this settles the open verification in research.md §3
- [ ] T020 Record the outcome of T019 in research.md §3. **Only if the combination is rejected**, add the documented fallback to src/bie/claude.py: a research-and-reason call with web search followed by a cheap formatting call that parses into the schema, with its own unit test in tests/unit/test_claude.py
- [X] T021 [P] Write failing contract tests in tests/contract/test_api_foundation.py: `GET /api/health` returns status, model, prompt version and `has_api_key` without raising when no key is set; `GET /api/limits` returns exactly the `Settings` values the UI must enforce; every raised `BieError` renders as `{"error": {"code", "message", "retryable"}}` with the right HTTP status and no internal detail in the body
- [X] T022 Implement the FastAPI app in src/bie/api.py: app factory, exception handlers mapping `BieError` to the envelope, the `/api/health` and `/api/limits` routes, a 180 s call deadline, and `web/` mounted as static files at `/`
- [X] T023 [P] Write failing contract tests in tests/contract/test_cli_foundation.py using Typer's `CliRunner`: `bie --help` lists `ask`, `verdict`, `evaluate`, `serve` and `eval`; `--model`, `--effort` and `--prompt-version` override `Settings` for one invocation
- [X] T024 Implement src/bie/cli.py with the Typer app referenced by `[project.scripts]` in pyproject.toml, the global overrides, and `bie serve` running uvicorn against the app from T022

**Checkpoint**: `pytest` and `ruff check .` pass; `bie serve` starts and serves the current page.

---

## Phase 3: User Story 1 — Interrogation, then verdict (Priority: P1) 🎯 MVP

**Goal**: A founder types an idea, gets questions and only questions, answers them, and receives
the full verdict report with its sources and cost.

**Independent Test**: Submit an idea on the page; confirm the conversation opens with numbered
questions and no verdict or score; answer them; confirm a verdict report arrives whose first line
is one of the three permitted verdicts, with every named section present.

### Tests for User Story 1 ⚠️ write first, watch them fail

- [X] T025 [P] [US1] Write failing unit tests in tests/unit/test_evaluator_questions.py: `ask_questions()` builds a request from idea + prompt v3, returns a validated `QuestionSet` of 3–10 questions covering the prompt's priority topics, and raises `InvalidModelOutput` when the reply contains a verdict (FR-004)
- [X] T026 [P] [US1] Write failing unit tests in tests/unit/test_evaluator_verdict.py: `evaluate()` assembles idea + full round history into the messages array, returns a validated `VerdictReport` with `sources` and a `ResearchStatus`, and still returns a verdict when research is degraded or unavailable (FR-016)
- [X] T027 [P] [US1] Write failing contract tests in tests/contract/test_questions_route.py for `POST /api/questions`: 200 with `kind: "questions"`, usage and cost; 422 when the idea is under `min_idea_chars` **before any model call**; 402 on `BudgetExceeded`; 500 on `InvalidModelOutput`; 502 on upstream failure
- [X] T028 [P] [US1] Write failing contract tests in tests/contract/test_verdict_route.py for `POST /api/verdict`: 200 with `kind: "verdict"`, the report, sources, `research_status`, usage and cost; the same 402/422/500/502 semantics; `research_status: "degraded"` still returns 200
- [X] T029 [P] [US1] Write failing contract tests in tests/contract/test_cli_rounds.py: `bie ask "IDEA"` prints the numbered questions and exits 0; exits 2 on a short idea, 3 on budget refusal, 4 on invalid model output, 5 on upstream failure; `--json` prints the validated model
- [X] T030 [P] [US1] Write the graded eval case `evals/cases/no_verdict_in_step_one.yaml` asserting zero verdict or score language in a first response across several idea shapes (SC-002)
- [X] T031 [P] [US1] Write the graded eval case `evals/cases/verdict_structure.yaml` asserting the verdict line is first and one of the three permitted values, every required section is present, and the report is ≤ ~600 words (SC-005)
- [X] T032 [P] [US1] Write the live integration test tests/integration/test_full_loop.py, marked `live`, walking idea → questions → answers → verdict against the real API and asserting a schema-valid report and a non-zero recorded cost

### Implementation for User Story 1

- [X] T033 [US1] Implement `ask_questions(idea, attachments, settings)` in src/bie/evaluator.py returning a `Round` of kind `questions` (depends on T016, T018)
- [X] T034 [US1] Implement `evaluate(idea, rounds, attachments, settings)` in src/bie/evaluator.py returning a `Round` of kind `verdict` with sources, research status, usage and cost; budget checks run before the call and actual cost is recorded after it
- [X] T035 [US1] Add `POST /api/questions` and `POST /api/verdict` to src/bie/api.py per contracts/http-api.md, taking the client-held transcript in the body and persisting nothing
- [X] T036 [US1] Add `bie ask`, `bie verdict` and `bie evaluate` to src/bie/cli.py per contracts/cli.md, all calling the same `evaluator.py` functions as the API so the two surfaces cannot drift
- [X] T037 [P] [US1] Restructure web/index.html into two panes on the design committed in `24969dd`: an idea box pane on the left and a conversation pane on the right, keeping the period chrome, banner and marquee; delete the score block, the dimension table and the risk table (FR-031, FR-035)
- [X] T038 [P] [US1] Update web/styles.css: add the two-pane split that stacks idea-above-conversation below the mobile breakpoint, add evaluator and founder turn styles, and delete the `.meter`, dimension-row and score rules that no longer have markup
- [X] T039 [US1] Rewrite web/app.js for the round loop: submit the idea to `/api/questions`, render each turn attributed and in order with the evaluator's numbering preserved, submit answers to `/api/verdict`, render the report section by section with its sources and the round's cost, show the in-progress state and block a second concurrent submission (FR-019, FR-032)
- [X] T040 [US1] Render every failure from the error envelope as a founder-readable message with a retry control in web/app.js, and make sure a failed round leaves the conversation untouched (FR-029, FR-018)
- [X] T041 [US1] Add the copy/export control for a completed report in web/app.js and web/index.html (FR-030)
- [X] T042 [US1] Implement `evals/graders.py` (structural graders plus an LLM-as-judge using `JudgeVerdict` and `judge_model`) and `evals/run.py` printing per-case results, the pass rate and the run's total cost; make T030 and T031 pass

**Checkpoint**: The MVP works end to end — questions, then verdict, with cost and sources shown.

---

## Phase 4: User Story 2 — Being pushed back on, and adding detail (Priority: P2)

**Goal**: Vague answers are sent back rather than assumed, detail can be added at any point,
contradictions are named, and the whole conversation survives a reload.

**Independent Test**: Answer a question vaguely and confirm a re-ask naming the vagueness instead
of a verdict; then answer properly, add contradicting detail, confirm the verdict names the
contradiction, and reload the page to find every round still in order.

### Tests for User Story 2 ⚠️ write first, watch them fail

- [X] T043 [P] [US2] Write failing unit tests in tests/unit/test_evaluator_reask.py: `evaluate()` returns a `Round` of kind `reask` with a non-empty `note` when answers are vague, and never a verdict built on an assumed answer (FR-006)
- [X] T044 [P] [US2] Extend tests/contract/test_verdict_route.py with the discriminated response: `POST /api/verdict` may return `kind: "reask"` with a `QuestionSet`, and the client must be able to branch on `kind` alone
- [X] T045 [P] [US2] Write failing unit tests in tests/unit/test_evaluator_history.py: a re-evaluation carries the original idea plus every answer, added detail and attachment from earlier rounds (FR-021), and a revised idea replaces the original for the next round with the revision visible in the transcript (FR-034)
- [X] T046 [P] [US2] Write the graded eval case `evals/cases/vagueness_reask.yaml` with deliberately vague answers, asserting a re-ask rather than a verdict in at least 90% of cases (SC-006)
- [X] T047 [P] [US2] Write the graded eval case `evals/cases/contradiction_called_out.yaml` asserting the verdict names a contradiction the founder's own answers contain (FR-011)
- [X] T048 [P] [US2] Write failing browser-level tests in tests/contract/test_session_store.py for the session module's pure logic — append round, revise idea, clear session, cumulative cost — extracted from web/app.js so it can be tested without a browser

### Implementation for User Story 2

- [X] T049 [US2] Extend `evaluate()` in src/bie/evaluator.py to return either a verdict or a re-ask round, with the decision made server-side and never by the client
- [X] T050 [US2] Update `POST /api/verdict` in src/bie/api.py to emit the discriminated `kind: "verdict" | "reask"` payload per contracts/http-api.md
- [X] T051 [US2] Implement the session store in web/app.js over IndexedDB (research.md §11): one record per session holding idea, rounds, attachment metadata and cumulative cost, restored on load and scrolled to the latest turn (FR-022)
- [X] T052 [US2] Render re-asks distinctly from first-round questions in web/app.js, showing the note that names what was vague
- [X] T053 [US2] Allow answering across several messages and adding detail at any point in web/app.js, appending each as its own founder turn (FR-033)
- [X] T054 [US2] Make the idea box editable after the conversation starts, recording the revision as a visible transcript entry and sending the revised idea in the next round (FR-034)
- [X] T055 [US2] Add the clear-session control to web/index.html and web/app.js, resetting to an empty idea box and conversation (FR-023)
- [X] T056 [US2] Add `bie verdict --session PATH` session-file read/write to src/bie/cli.py so the CLI has the same multi-round loop as the browser (contracts/cli.md)

**Checkpoint**: US1 and US2 both work independently; sessions survive reloads.

---

## Phase 5: User Story 3 — Attaching evidence (Priority: P3)

**Goal**: Spreadsheets, images, PDFs and text files can be attached to any message, are reasoned
about as known data, and are deleted when the session is cleared.

**Independent Test**: Attach an XLSX and a PNG to an answer and confirm the verdict refers to
specific content from both; attach an oversized and an unsupported file and confirm both are
rejected at selection with the limit named, leaving the rest of the submission intact.

### Tests for User Story 3 ⚠️ write first, watch them fail

- [X] T057 [P] [US3] Write failing unit tests in tests/unit/test_attachments.py: files over `max_attachment_mb` (10 MB) and beyond `max_attachments` (5 per submission) are rejected with the limit named; media type maps to `AttachmentKind`; an unsupported type raises `AttachmentRejected`; a corrupt file comes back `readable: false` with an error rather than failing the batch (FR-026, FR-027)
- [X] T058 [P] [US3] Write failing unit tests in tests/unit/test_sheet_conversion.py: a multi-sheet XLSX converts to text with one section per sheet and the header row preserved; CSV and TXT/MD pass through as text (research.md §7)
- [X] T059 [P] [US3] Write failing contract tests in tests/contract/test_attachments_route.py: `POST /api/attachments` returns 201 with one `Attachment` per file including `file_id` for images and PDFs; 400 naming the limit for rejects; `DELETE /api/attachments` returns 204 and treats an already-deleted id as success
- [X] T060 [P] [US3] Write the graded eval case `evals/cases/attachment_grounding.yaml` asserting the verdict quotes a figure that exists only in the attached spreadsheet (SC-009)
- [X] T061 [P] [US3] Write the live integration test tests/integration/test_attachment_round.py, marked `live`, uploading an XLSX and a PNG and asserting the verdict references both

### Implementation for User Story 3

- [X] T062 [US3] Implement src/bie/attachments.py: validation against `Settings` limits, kind detection, XLSX conversion via `openpyxl` (one section per sheet, header row preserved, cells tab-separated), CSV/text passthrough, Files API upload for images and PDFs, and deletion by file id (research.md §2)
- [X] T063 [US3] Add `POST /api/attachments` and `DELETE /api/attachments` to src/bie/api.py per contracts/http-api.md
- [X] T064 [US3] Extend src/bie/claude.py to build native image and document content blocks from `file_id` and to inline extracted sheet and text content as delimited data blocks
- [X] T065 [US3] Add the attach control to web/index.html and the upload, name list and per-file remove behaviour to web/app.js, enforcing the same limits client-side from `/api/limits` (FR-025, FR-026)
- [X] T066 [US3] Tell the founder in web/app.js which attachments could not be read and let them proceed without them or cancel (FR-027)
- [X] T067 [US3] Delete uploaded file ids when the session is cleared in web/app.js, and state near the attach control that attachments are sent to Anthropic for the life of the session (research.md §2 risk)
- [X] T068 [US3] Add `--file` to `bie ask` and `bie verdict` in src/bie/cli.py, capped at the same limits

**Checkpoint**: All three user stories work independently.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T069 [P] Write the graded eval case `evals/cases/injection_resistance.yaml` covering an idea, an attachment and a retrieved page that each try to force a PROCEED, asserting the verdict is unmoved (SC-011, research.md §10)
- [X] T070 [P] Write the graded eval case `evals/cases/tone_no_padding.yaml` asserting no encouragement padding or hedging in at least 95% of scored cases (SC-012)
- [X] T071 [P] Write the graded eval case `evals/cases/degraded_research.yaml` asserting a verdict still arrives with claims marked unverified when search is unavailable (SC-014)
- [X] T072 [P] Add a `bie eval run` command to src/bie/cli.py wiring the eval suite to the CLI (contracts/cli.md)
- [ ] T073 [P] Verify the named competitors in a sample of verdicts are real and traceable to a retrieved source, and record the measured rate against SC-013 in specs/001-idea-evaluation-flow/research.md
- [X] T074 [P] Rewrite README.md for the two-step flow: what it does, setup, `bie serve`, the CLI commands, the cost ceilings, and the note that attachments transit to the Anthropic Files API
- [X] T075 Run `/speckit-constitution` to close `TODO(COST_CEILING)` with the chosen $1.50 per round and $5.00 per session, bumping the constitution to 1.0.1
- [X] T076 Delete the dead retro scorer markup, CSS and JS left behind in web/ after T037–T039, and confirm no reference to `overall_score`, `dimensions` or `/api/evaluate` survives anywhere in the repository
- [X] T077 Check the page at mobile width: panes stack idea-above-conversation, the conversation scrolls, and nothing overflows horizontally
- [ ] T078 Run every scenario in specs/001-idea-evaluation-flow/quickstart.md against the running app, including the four failure paths, and fix what fails
- [X] T079 Final gate before merge: `pytest` green, `ruff check .` clean, `python -m evals.run` at or above its threshold, and each of the five constitution principles checked against the diff

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: needs Phase 1 — blocks every user story
- **US1 (Phase 3)**: needs Phase 2. The MVP
- **US2 (Phase 4)**: needs Phase 2; T049–T050 extend the US1 verdict route, so run after Phase 3
- **US3 (Phase 5)**: needs Phase 2; independently testable, and can run in parallel with Phase 4 once Phase 3 is done
- **Polish (Phase 6)**: needs the stories it touches

### Within Each User Story

Tests written and failing → schemas/models → evaluator logic → routes and CLI → UI → evals.
No implementation task starts before its test task is red.

### Parallel Opportunities

- T002, T003, T004 in Setup
- All test-writing tasks marked [P] within a phase — they touch different files
- T005/T007/T009/T011/T013/T015 can all be written before any Phase 2 implementation
- T037 and T038 (HTML and CSS) run alongside each other; T039 depends on both
- Phase 4 and Phase 5 can proceed in parallel after Phase 3
- Every eval case in Phase 6 is independent

---

## Parallel Example: User Story 1

```bash
# Write all six US1 test tasks together, then watch them fail:
Task: "Unit tests for ask_questions in tests/unit/test_evaluator_questions.py"
Task: "Unit tests for evaluate in tests/unit/test_evaluator_verdict.py"
Task: "Contract tests for POST /api/questions in tests/contract/test_questions_route.py"
Task: "Contract tests for POST /api/verdict in tests/contract/test_verdict_route.py"
Task: "Contract tests for bie ask/verdict in tests/contract/test_cli_rounds.py"
Task: "Eval cases in evals/cases/no_verdict_in_step_one.yaml and verdict_structure.yaml"

# Then the two UI files in parallel:
Task: "Two-pane restructure in web/index.html"
Task: "Pane split and turn styles in web/styles.css"
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup
2. Phase 2 Foundational — blocks everything, do not skip T019, it settles a real unknown
3. Phase 3 US1
4. **Stop and validate**: run quickstart.md Scenario 1 and the US1 eval cases
5. Demo: an idea goes in, questions come back, answers produce a verdict

### Incremental Delivery

Setup + Foundational → US1 (MVP, demo) → US2 (push-back and persistence, demo) → US3
(attachments, demo) → Polish. Each story adds value without breaking the one before it.

---

## Status (2026-09-21)

Done: T001–T019, T021–T072, T074–T077, T079. The suite is 164 passing, 3 skipped (the
`live` tests), `ruff` clean.

Blocked on a real API key and real spend, and left unchecked:

- **T020** — the two-call fallback. It is only written if T019 shows the single call is
  rejected, and T019 has not been run. Run `pytest -m live -k structured_output` first.
- **T073** — measuring how many named competitors are real needs live verdicts to measure.
- **T078** — quickstart scenarios 1 to 3 need a key. The failure paths were verified
  against a running server (short idea refused, unsupported attachment rejected, health
  and limits served, page and assets served).

## Notes

- Every implementation task has a failing test before it — the constitution admits no exceptions
- Two tasks carry an unknown that must be resolved against live sources, not recalled: T010 (the
  per-search price) and T019/T020 (structured outputs combined with the web search tool)
- Every model reply validates against a Pydantic schema before it reaches a caller (Principle II)
- Every round reports its cost and refuses to start above the ceiling (Principle III)
- Commit after each task or logical group; stop at any checkpoint to validate a story on its own
