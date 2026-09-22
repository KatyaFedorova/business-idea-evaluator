# Business Idea Evaluator

A skeptical early-stage investor in a web page. You describe a business idea; it asks you the
questions whose answers would most change its verdict, and only once you have answered does it
tell you **PROCEED**, **PROCEED ONLY AFTER TESTING X**, or **DON'T PROCEED** — with the three
strongest reasons it works, the three most likely ways it dies, the riskiest assumption, a
two-week no-code validation plan with explicit pass and fail numbers, named competitors it
actually looked up, and kill criteria.

No scores. No pep talk. Around 600 words.

## How it works

Two panes: your idea on the left, the conversation on the right. Round one is questions only —
a reply that contains a verdict fails schema validation and never reaches you. You answer in as
many messages as you like, attaching evidence if you have it. Round two researches the market
with live web search, then returns the verdict. If your answers are vague, it says so and asks
again rather than inventing a customer for you.

The server stores nothing. Your session lives in your browser (IndexedDB) and survives a reload;
clearing it deletes the files it uploaded.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env    # then set ANTHROPIC_API_KEY
```

## Run

```bash
bie serve                       # http://127.0.0.1:8000
bie ask "my idea..."            # round one from the terminal
bie verdict --session s.json --answers "..."
bie eval run                    # the graded eval suite — SPENDS MONEY, ask first
```

## Deploy

Free on Vercel Hobby — see [DEPLOY.md](DEPLOY.md). Set `BIE_MAX_ATTACHMENT_MB=4` there,
because Vercel caps request bodies at 4.5 MB.

## The eval suite spends money

`bie eval run` makes ~16 live calls. It is never run automatically: not in CI, not on a
commit, not as a merge gate. Run it only when a change could alter model behaviour — the
prompt, the schemas, the evaluator, the model or effort settings, or the graders — and only
when the owner has asked for that run. See Principle III in `.specify/memory/constitution.md`.

## Develop

```bash
pytest                  # unit + contract tests: no API key, no network, no spend
pytest -m live          # integration tests against the real API (spends money)
ruff check .
```

## What it costs

Every round reports its own cost, and the session total is on screen. Two ceilings are enforced
in code before a call is made, not reconciled afterwards: **$1.50 per round** and **$5.00 per
session** (`BIE_MAX_COST_PER_ROUND_USD`, `BIE_MAX_COST_PER_SESSION_USD`). Live web search is
billed at $10 per 1,000 searches on top of tokens, and is capped per round by `BIE_MAX_SEARCHES`.

## Attachments

Images, PDFs, spreadsheets (XLSX, CSV) and text, up to 5 files of 10 MB each. Spreadsheets are
converted to text here; images and PDFs are uploaded to the Anthropic Files API and referenced by
id, so the bytes cross the wire once however many rounds follow. **Those files stay with Anthropic
for the life of the session** and are deleted when you clear it.

## Layout

```
src/bie/        schemas, prompt, evaluator, budget, attachments, FastAPI app, Typer CLI
web/            the page: two panes, 90s chrome, no build step, no framework
evals/          graded cases, structural graders, an LLM judge, the runner
tests/          unit, contract, and live integration tests
specs/          the specification, plan and tasks this was built from
```

Configuration lives in `.env` and is read in exactly one place, `src/bie/config.py`. The prompt
lives in `src/bie/prompts/` and is versioned; `BIE_PROMPT_VERSION` selects it.
