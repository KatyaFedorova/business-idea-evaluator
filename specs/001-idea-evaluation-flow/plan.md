# Implementation Plan: Guided Idea Evaluation Flow

**Branch**: `001-idea-evaluation-flow` | **Date**: 2026-09-21 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-idea-evaluation-flow/spec.md`

## Summary

Build the two-step evaluation loop the owner's prompt describes: a founder types an idea, the
system replies with clarifying questions only, and a verdict report arrives only after those
questions are answered. All application logic is Python — a `bie` package holding the schemas,
the prompt, the attachment pipeline, the evaluation engine, a FastAPI surface, and a Typer CLI.
The browser keeps the session; the server keeps nothing. Evaluation runs against `claude-opus-5`
with the server-side web search tool for live research, structured outputs for a schema-valid
report, and the Files API so attachments are uploaded once and referenced by id in later rounds.

This replaces the scaffolded one-shot scorer: the existing `IdeaEvaluation` schema (five 1–10
dimensions, `overall_score`) has no counterpart in the supplied prompt and is removed. The UI is
rebuilt on the design pushed in commit `24969dd` ("Rework the page: one-pager, 90s styling"),
keeping its period navy/yellow chrome, bevelled controls and marquee, and changing the structure:
the single column of idea → scored verdict → follow-up chat becomes two panes, idea box left and
conversation right, with the score block deleted and the conversation promoted from a footnote to
the main event.

## Technical Context

**Language/Version**: Python 3.11+ (all application logic; the browser layer stays plain
HTML/CSS/JS, since a browser runs JavaScript and the constitution fixes a dependency-free UI)

**Primary Dependencies**: `anthropic` (Messages API, web search server tool, structured outputs,
Files API), FastAPI + uvicorn, Pydantic v2, Typer + Rich, python-dotenv, PyYAML. New: `openpyxl`
(XLSX → text), `python-multipart` (FastAPI multipart uploads)

**Storage**: None server-side. Session state lives in the browser (IndexedDB); attachments live
in the Anthropic Files API for the life of the session and are deleted when the session is cleared

**Testing**: pytest (`asyncio_mode = "auto"`), TDD mandatory per constitution; unit tests on
recorded fixtures, contract tests for the HTTP and CLI surfaces, a small live-API integration
suite behind a marker, and the graded eval suite in `evals/`

**Target Platform**: Local/self-hosted uvicorn server; desktop and mobile browsers

**Project Type**: Single Python project serving a static UI (web service + CLI over one core)

**Performance Goals**: Question round under ~20 s; verdict round with live research under ~120 s
with a visible in-progress state throughout; no request exceeds a 180 s server timeout

**Constraints**: Per-round cost ceiling enforced in code (default $1.50/round, $5.00/session);
verdict report ~600 words or fewer; 5 attachments per submission at 10 MB each; every model reply
validated against a Pydantic schema before it reaches the UI

**Scale/Scope**: Single-user-at-a-time self-hosted tool; tens of sessions per day, a handful of
rounds each. Roughly 9 Python modules, ~25 HTTP/CLI contract tests, ~20 eval cases

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|---|---|---|
| I. Test-First | Every module has a failing test written and observed before implementation; `tasks.md` must order tests ahead of code | PASS — planned task order enforces it |
| II. Schema-Validated Model Output | All three model replies (`QuestionSet`, `ReAsk`, `VerdictReport`) are Pydantic models produced via structured outputs and validated before use; validation failure is a typed error, never a patched result | PASS |
| III. Cost Measured and Capped | Every call records usage via `pricing.cost_usd`; `budget.py` enforces a per-round and per-session ceiling before the call and after it; cost is returned to the UI. Closes `TODO(COST_CEILING)` with $1.50/round, $5.00/session, both env-overridable | PASS — constitution amendment needed only to record the chosen numbers |
| IV. Locked Stack, Minimal Surface | Python 3.11 + FastAPI + Pydantic + Typer + dependency-free UI. No database (IndexedDB is browser-native), no auth, no frontend framework, no build step. Two new dependencies justified below | PASS |
| V. Configuration Over Hardcoding | Model ids, effort, prompt version, ceilings, attachment limits, search budget all added to `Settings`; invalid values fail at construction | PASS |

**Dependency justification (Principle IV)**: `openpyxl` — parsing the XLSX zip/XML format by hand
is far beyond the fifty-line threshold, and XLSX is one of the file types the owner named.
`python-multipart` — FastAPI requires it to accept file uploads at all; it is the framework's own
prerequisite, not an alternative to code we could write.

**Post-design re-check**: PASS. No new components entered the design in Phase 1. The two items
that deserve the owner's eye are recorded as risks in `research.md`: attachments transit to the
Anthropic Files API (third-party retention, mitigated by deleting file ids on session clear), and
web search adds a per-search charge on top of tokens, which the ceiling must account for.

## Project Structure

### Documentation (this feature)

```text
specs/001-idea-evaluation-flow/
├── plan.md                  # This file
├── spec.md                  # Feature specification
├── evaluation-prompt.md     # Owner-supplied prompt, v1 transcription
├── research.md              # Phase 0 output
├── data-model.md            # Phase 1 output
├── quickstart.md            # Phase 1 output
├── contracts/
│   ├── http-api.md          # FastAPI surface
│   └── cli.md               # Typer surface
├── checklists/
│   └── requirements.md      # Spec quality checklist
└── tasks.md                 # Created by /speckit-tasks, not here
```

### Source Code (repository root)

```text
src/bie/
├── __init__.py              # exists
├── config.py                # extend: ceilings, limits, search budget, effort per phase
├── pricing.py               # extend: per-search web search cost
├── schemas.py               # REWRITE: question/re-ask/verdict models, sources, usage
├── prompts/
│   ├── __init__.py          # loader: read versioned prompt text by BIE_PROMPT_VERSION
│   └── v3_interrogator.md   # the owner's prompt, split into system + step framing
├── claude.py                # NEW: client construction, one call path, usage → Usage
├── budget.py                # NEW: projected + actual cost, ceiling enforcement, errors
├── attachments.py           # NEW: validate, convert (XLSX/CSV → text), Files API upload/delete
├── evaluator.py             # NEW: ask_questions() and evaluate() — the two-step engine
├── api.py                   # NEW: FastAPI app, routes, error mapping, static UI mount
└── cli.py                   # NEW: Typer app (`bie`), referenced by pyproject but missing

tests/
├── unit/                    # schemas, budget, attachments, prompt loader, pricing
├── contract/                # HTTP routes and CLI commands against fakes
└── integration/             # live-API tests behind the `live` marker

evals/
├── cases/                   # graded cases: no-verdict-in-step-1, vagueness, injection, tone
├── graders.py               # structural + LLM-as-judge graders
└── run.py                   # eval runner, reports pass rate and total cost

web/
├── index.html               # restructure to two panes: idea box left, conversation right
├── app.js                   # rewrite: IndexedDB session, turn rendering, uploads, re-ask loop
└── styles.css               # keep committed 90s chrome; add pane split, turn bubbles, drop
                             # the score/dimension/meter rules
```

**Structure Decision**: Single Python project, keeping the existing `src/bie` package layout the
repository already uses. The committed UI's `POST /api/evaluate` and streamed `POST /api/chat`
calls are superseded by the routes in `contracts/http-api.md`; neither endpoint was ever
implemented server-side, so nothing is being broken, only replaced. The CLI and the HTTP API are thin shells over `evaluator.py`, which is
what keeps the constitution's requirement that both surfaces cannot drift into different answers.
No `backend/` + `frontend/` split: the UI is three static files served by the same app.

## Complexity Tracking

> No constitution violations. The table is left empty deliberately.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
