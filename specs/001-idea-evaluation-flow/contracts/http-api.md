# Contract: HTTP API

FastAPI app in `src/bie/api.py`, served by uvicorn, also serving `web/` as static files at `/`.
All bodies are JSON unless noted. Every response body validates against a model in
`src/bie/schemas.py`. The API is stateless: the client sends the session history it holds.

## GET /api/health
200 → `{"status": "ok", "model": "claude-opus-5", "prompt_version": "v3", "has_api_key": true}`.
Never fails when the process is up; `has_api_key` false is reported, not raised.

## GET /api/limits
200 → the numbers the UI must enforce, read from `Settings` so the two cannot drift:
`{"min_idea_chars": 40, "max_attachments": 5, "max_attachment_bytes": 10485760,
"allowed_media_types": [...], "max_cost_per_round_usd": 1.5, "max_cost_per_session_usd": 5.0}`.

## POST /api/attachments
`multipart/form-data`, one or more `files`. Validates type and size, converts sheets and text to
text, uploads images and PDFs to the Files API.
201 → `{"attachments": [Attachment, ...]}` — each carries `id`, `filename`, `kind`, `size_bytes`,
`file_id`, `text`, `readable`, `error`. An unreadable file comes back with `readable: false` and a
message rather than failing the whole call (FR-027).
400 → unsupported type or over-size, naming the limit (FR-026).

## POST /api/questions
Body: `{"idea": str, "attachments": [Attachment, ...]}`.
Starts a session's first round.
200 → `{"kind": "questions", "questions": QuestionSet, "usage": Usage, "cost_usd": float}`.
422 → idea shorter than `min_idea_chars` (FR-002), before any model call.
402 → `BudgetExceeded`, with the projected cost and the ceiling (FR-020).
502 → upstream unavailable, timed out, or rate-limited, with a retryable flag (FR-029).
500 → `InvalidModelOutput`; the reply failed schema validation and is not returned (FR-018).
A response whose questions contain a verdict is rejected by validation, so step 1 cannot leak one.

## POST /api/verdict
Body: `{"idea": str, "rounds": [RoundInput, ...], "attachments": [Attachment, ...]}` where
`RoundInput` is `{"kind", "user_text", "output"}` — the transcript the browser holds.
The server decides whether the answers are specific enough; the client does not.
200 → either
`{"kind": "verdict", "report": VerdictReport, "sources": [Source], "research_status": "ok",
"usage": Usage, "cost_usd": float}`
or `{"kind": "reask", "questions": QuestionSet, "usage": Usage, "cost_usd": float}` when the
answers were vague (FR-006). The client renders the discriminator, never guesses from shape.
Same 402 / 422 / 500 / 502 semantics as `/api/questions`.
`research_status` of `degraded` or `unavailable` still returns 200 with a verdict (FR-016).

## DELETE /api/attachments
Body: `{"file_ids": [str, ...]}`. Deletes uploaded files when a session is cleared (FR-023).
204 on success; a file id already gone is not an error.

## Error envelope
Every 4xx/5xx body is `{"error": {"code": str, "message": str, "retryable": bool}}` with `code` in
`idea_too_short | attachment_rejected | budget_exceeded | invalid_model_output | upstream_error |
upstream_timeout | rate_limited`. `message` is written for the founder; internal detail is logged,
never returned (FR-029).

## Timeouts
Server-side call deadline 180 s; the verdict route streams internally and finalizes, so a long
research round does not trip an HTTP timeout. Clients should not retry automatically on 502 —
the retry is the founder's, per the spec's retry-option requirement.
