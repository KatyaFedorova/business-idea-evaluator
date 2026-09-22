<!--
Sync Impact Report
Version change: none (unversioned template) → 1.0.0 → 1.0.1 (PATCH: named the cost
  ceilings) → 1.1.0 (MINOR: eval runs require explicit per-run permission)
Modified principles:
  [PRINCIPLE_1_NAME] → I. Test-First (NON-NEGOTIABLE)
  [PRINCIPLE_2_NAME] → II. Schema-Validated Model Output
  [PRINCIPLE_3_NAME] → III. Cost Is Measured and Capped
  [PRINCIPLE_4_NAME] → IV. Locked Stack, Minimal Surface
  [PRINCIPLE_5_NAME] → V. Configuration Over Hardcoding
Added sections:
  Technology Constraints (was [SECTION_2_NAME])
  Development Workflow (was [SECTION_3_NAME])
Removed sections: none
Deferred TODOs:
  (closed in 1.0.1: the ceilings are $1.50 per round and $5.00 per session)
  Eval-suite gating was offered and not adopted; evals remain encouraged, not governed.
This report is scratch material for reviewing the amendment and should be deleted
before committing the amended file.
-->

# Business Idea Evaluator Constitution

Business Idea Evaluator (`bie`) scores business ideas with Claude and proves the prompt
works with a graded eval pipeline. This constitution governs how every feature in this
repository is specified, built, and accepted.

## Core Principles

### I. Test-First (NON-NEGOTIABLE)

Test-driven development is mandatory for all code in `src/bie/`. Tests MUST be written
before the implementation, MUST be observed failing for the intended reason, and only
then MUST the implementation be written to make them pass. Red-Green-Refactor is the
required cycle: no refactor lands without a green suite before and after it. A task that
produces implementation code with no preceding failing test is incomplete and MUST be
redone, regardless of whether the code works. `pytest` MUST pass and `ruff` MUST report
no errors before any change is merged.

Rationale: the scoring logic and the model boundary are the two places where silent
breakage is most expensive and least visible, because a wrong score still looks like a
score. Writing the test first is what forces the expected behaviour to be stated before
the code has a chance to define it.

### II. Schema-Validated Model Output

Every response from a Claude call MUST be parsed into a Pydantic model from
`src/bie/schemas.py` before any other code reads it. Unvalidated or partially parsed
model output MUST NOT be passed downstream, persisted, rendered in the web UI, or
returned from an API route. A validation failure is an error: it MUST surface as a
typed, explicit failure with the offending payload available for debugging, and MUST NOT
be silently coerced, patched with defaults, or retried into apparent success. Adding a
field to a response shape means adding it to the schema in the same change.

Rationale: a language model returns text, and text that merely looks like the right
shape will propagate a malformed score through the entire system. The schema is the only
place where "the model answered" becomes "the model answered correctly enough to use".

### III. Cost Is Measured and Capped

Every Claude call MUST record its input tokens, output tokens, and computed cost through
`src/bie/pricing.py`. Every evaluation run MUST expose its total cost to the caller — in
CLI output, in API responses, and in eval reports. A per-evaluation cost ceiling MUST be
enforced in code, not by convention: when a run would exceed the ceiling it MUST stop
with a clear error rather than complete and bill.
TODO(COST_CEILING): choose the ceiling value and the environment variable that carries it.

The eval suite spends money on every case, so it MUST NOT be run without the owner's
explicit permission for that run. Permission is per run and is never implied by a task
list, a checklist item, a merge gate, or a previous approval. It MUST NOT run in CI, on a
commit, on a push, or on a schedule. It SHOULD be run only when a change could alter model
behaviour — the prompt, the schemas, the evaluator, the model or effort settings, or the
graders themselves — and MUST NOT be run for changes that cannot, such as the web UI, the
CLI's presentation, documentation, or test-only edits.

Rationale: this is a tool whose core operation costs real money per invocation, and batch
eval runs multiply that cost by the size of the dataset. A cap enforced in code is the
only kind that survives a loop with a bug in it. The eval suite is the one thing here that
spends without a person asking for an evaluation, which is exactly why asking is required.

### IV. Locked Stack, Minimal Surface

The technology stack is fixed at Python 3.11+, FastAPI, Pydantic v2, Typer, and a
dependency-free static web UI of plain HTML, CSS, and JavaScript. Adding a database, an
authentication layer, a frontend framework, a build step for the web UI, or any other
architectural component REQUIRES amending this constitution first. New runtime
dependencies MUST be justified in the feature's plan; a dependency that replaces fewer
than roughly fifty lines of straightforward code SHOULD be written instead of added.

Rationale: the value of this project is the prompt and the eval pipeline, not the
infrastructure around them. Every component added is a component that has to be
maintained, tested, and understood before anyone can change a prompt.

### V. Configuration Over Hardcoding

All runtime configuration — model IDs, effort level, prompt version, token limits,
concurrency, cost ceilings — MUST be read through `Settings` in `src/bie/config.py` and
overridable by environment variable. Model IDs MUST NOT be hardcoded at call sites.
Invalid configuration MUST fail loudly at construction time, as `Settings.__post_init__`
already does for effort levels. Secrets MUST come from the environment and MUST NOT be
committed; `.env.example` MUST list every variable the application reads, with no real
values in it.

Rationale: changing the model or the prompt version is the most common experiment this
project runs. If that requires a code edit, every experiment becomes a diff, and every
diff becomes a chance to ship the experiment by accident.

## Technology Constraints

Runtime is Python 3.11 or newer. Application code lives in `src/bie/`, tests in `tests/`,
the graded eval pipeline in `evals/`, and the static UI in `web/`. The package exposes a
CLI entry point `bie` via Typer and an HTTP surface via FastAPI; both MUST go through the
same underlying functions, so that the CLI and the API cannot drift into different
answers for the same input. Anthropic access uses the official `anthropic` SDK with
`ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` supplied by the environment. Linting is
`ruff` at a line length of 100. Testing is `pytest` with `asyncio_mode = "auto"`.

## Development Workflow

Feature work follows the Spec Kit flow: `/speckit-specify` to write the spec,
`/speckit-clarify` when the spec has open questions, `/speckit-plan` for the technical
design, `/speckit-tasks` for the ordered task list, and `/speckit-implement` to build it.
Each feature is developed on its own branch. Before a branch merges: every task in
`tasks.md` is complete or explicitly deferred in writing, `pytest` passes, `ruff` reports
no errors, and the change is checked against each principle above. The eval suite is not
part of that gate: it runs only when the owner asks for it, per Principle III. A change that violates
a principle MUST either be reworked or accompanied by an amendment to this constitution
in the same branch — never merged as a silent exception.

## Governance

This constitution supersedes all other development practices in this repository. Where a
plan, a task list, an agent instruction, or existing code conflicts with it, this document
wins and the conflicting artifact is what changes.

The repository owner is the sole author and approver of amendments. An amendment is a
commit that modifies this file, states what changed and why, and bumps the version below
according to semantic versioning: MAJOR for removing or redefining a principle in a
backward-incompatible way, MINOR for adding a principle or materially expanding guidance,
PATCH for clarifications and wording. The `Last Amended` date MUST be updated in the same
commit.

Compliance is reviewed at merge time against the Development Workflow gates above.
Complexity that appears to violate Principle IV MUST be justified in the feature's plan
or removed. Unresolved `TODO(...)` markers in this document are open governance debt and
SHOULD be closed before the feature that depends on them is planned.

**Version**: 1.1.0 | **Ratified**: 2026-09-21 | **Last Amended**: 2026-09-22
