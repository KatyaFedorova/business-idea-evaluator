# Phase 1 Data Model: Guided Idea Evaluation Flow

All models live in `src/bie/schemas.py` as Pydantic v2 models. Models marked **model output** are
the schemas Claude fills through structured outputs; nothing reaches the UI without validating
against one of them (Principle II).

## Enumerations

```text
RoundKind      = "questions" | "reask" | "verdict"
Confidence     = "low" | "medium" | "high"
VerdictKind    = "PROCEED" | "PROCEED_ONLY_AFTER_TESTING" | "DONT_PROCEED"
ResearchStatus = "ok" | "degraded" | "unavailable"
AttachmentKind = "image" | "pdf" | "sheet" | "text"
QuestionTopic  = "customer" | "alternative" | "willingness_to_pay" | "unfair_advantage"
                 | "resources" | "distribution" | "falsification" | "other"
```

`VerdictKind` keeps the "X" of PROCEED ONLY AFTER TESTING X in a separate `verdict_condition`
field, so the machine-readable verdict stays a closed set while the condition stays free text.

## Core entities

### Question **(model output)**
| Field | Type | Rules |
|---|---|---|
| `number` | int | ≥ 1, unique and contiguous within a set |
| `text` | str | non-empty |
| `topic` | QuestionTopic | maps to the prompt's priority list |

### QuestionSet **(model output)**
| Field | Type | Rules |
|---|---|---|
| `questions` | list[Question] | 3–10 items, numbers contiguous from 1 |
| `note` | str \| None | used only by a re-ask, naming what was vague |
| `contains_verdict` | — | not a field: FR-004 is enforced by a validator rejecting verdict words in `text` |

### ReAsk **(model output)**
A `QuestionSet` with `note` required and non-empty. Modelled as `QuestionSet` plus a discriminator
on the round, not a separate class, so the re-ask path reuses one validator.

### VerdictReport **(model output)**
| Field | Type | Rules |
|---|---|---|
| `verdict` | VerdictKind | required, rendered first |
| `verdict_condition` | str \| None | required when verdict is PROCEED_ONLY_AFTER_TESTING, else must be null |
| `confidence` | Confidence | required |
| `confidence_movers` | str | non-empty — what would move it |
| `works_because` | list[str] | exactly 3 |
| `fails_because` | list[FailureMode] | exactly 3, ordered most-lethal first |
| `riskiest_assumption` | str | non-empty |
| `validation_plan` | ValidationPlan | required |
| `kill_criteria` | list[str] | 1–5 |
| `contradictions` | list[str] | may be empty; FR-011 |
| `prior_art` | list[str] | named existing products when the idea is a worse version; FR-010 |
| `word_count` | int | computed property, not a model-filled field; validated ≤ 400 as a runaway stop. The 300-word target is enforced by per-field `maxLength` limits, which structured outputs applies while the model writes. |

### FailureMode **(model output)**
`rank` (1–3), `text` (non-empty), `is_guess` (bool — Principle/FR-009 labelling).

### ValidationPlan **(model output)**
`assumption_tested`, `steps` (1–8 strings), `who_to_talk_to`, `pass_threshold`,
`fail_threshold`, `duration_days` (1–14, enforcing "under two weeks"), `requires_code` (must be
`False`; a plan that needs code fails validation).

### Source
`url`, `title`, `accessed_at`. Extracted from search result blocks, never model-authored.

### Attachment
`id` (client-side uuid), `filename`, `kind`, `size_bytes`, `file_id` (Anthropic Files API id or
`None` for text-only), `text` (extracted text for sheets and text files), `readable` (bool),
`error` (str \| None). Validation: ≤ 10 MB, kind derived from the media type, ≤ 5 per submission.

### Round
`index` (0-based), `kind` (RoundKind), `submitted_at`, `user_text` (the idea for round 0,
otherwise the answers or added detail), `attachment_ids`, `output` (QuestionSet or VerdictReport),
`sources`, `research_status`, `usage` (Usage), `cost_usd`.

### Session
Client-held. `id`, `created_at`, `idea`, `rounds` (ordered), `attachments`, `total_cost_usd`,
`prompt_version`. The server never persists this; it receives the parts it needs per request.

### Usage *(existing, extended)*
Add `web_searches` (int, default 0) so the per-search charge is visible next to token cost.
Existing fields — model, input/output/cache tokens, latency, `cost_usd` — are unchanged.

### Rubric scores *(eval-only)*
The judge's 1-5 score per dimension of `evals/rubric.yaml` lives in `evals/rubric.py`
(`RubricScores`), not in the app's schemas. It replaces the single-score `JudgeVerdict`.

## Validation rules drawn from requirements

1. A round-0 or re-ask reply that contains a verdict word fails validation (FR-004).
2. `verdict_condition` presence is tied to `VerdictKind` by a model validator (FR-007).
3. `works_because` and `fails_because` must hold exactly three items (FR-008).
4. `requires_code` must be `False` and `duration_days` ≤ 14 (FR-008).
5. Any validation failure raises `InvalidModelOutput`, surfaced as a retryable error — never a
   defaulted or partially filled report (FR-014, Principle II).
6. Attachment limits are enforced twice, in the browser and again server-side (FR-022).

## State transitions

```text
empty ──submit idea──▶ questions
questions ──answers──▶ verdict        (answers judged specific enough)
questions ──answers──▶ reask ──▶ questions   (answers judged vague, FR-006)
verdict ──added detail──▶ verdict     (re-evaluation, FR-008/FR-021)
any ──clear──▶ empty                  (deletes uploaded file ids, FR-023)
```

A round is only appended to the session after its output validates, so a failed round leaves the
session exactly as it was (FR-014, US2 scenario 6).
