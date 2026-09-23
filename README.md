# Business Idea Evaluator

A skeptical early-stage investor in a web page, and a graded LLM eval pipeline that proves it behaves.

You describe a business idea. It asks the questions whose answers would most change its verdict, researches the market with live web search, and only then decides: **PROCEED**, **PROCEED ONLY AFTER TESTING X**, or **DON'T PROCEED**. The verdict comes with the three strongest reasons it works, the three most likely ways it dies, the riskiest assumption, a two-week no-code validation plan with pass/fail numbers, real named competitors, and kill criteria.

No scores. No pep talk. About 600 words.

## At a glance

| | |
|---|---|
| Cost of one production evaluation | $1.30 |
| Cost of the full eval suite | $0.48 |
| Unit tests | 111 |
| Contract tests | 40 |
| Live integration tests | 3 |
| Graded eval cases | 8 |
| Method | Spec-driven development (GitHub Spec Kit) + strict TDD |
| Stack | Python 3.11+, FastAPI, Pydantic v2, Typer, Anthropic SDK, plain HTML/CSS/JS, Vercel |

## What this project demonstrates

- **LLM evaluation engineering.** Eight graded cases check behavior, not just format. Structural graders are paired with an LLM-as-judge for what structure can't see.
- **Cost as a first-class requirement.** Every call is priced, every round reports its cost, and three spending ceilings are enforced before the API call, not reconciled after it.
- **A disciplined test strategy.** The testing pyramid is respected: a fast, free, offline base, and paid live tests only at the top.
- **Spec-driven, agent-assisted delivery.** The whole feature was specified, planned, broken into tasks and implemented through GitHub Spec Kit with AI coding agents, governed by a written project constitution.
- **Safe handling of model output.** Every response is parsed into a Pydantic schema before any code touches it. Invalid output is a typed error, never silently patched.

## Two kinds of tests

### 1. Software tests: the testing pyramid

```
            /\
           /  \        3 live integration tests
          /----\       real API, opt-in only (pytest -m live)
         /      \
        /--------\     40 contract tests
       /          \    HTTP API, CLI and session-store contracts
      /------------\
     /              \  111 unit tests
    /----------------\ schemas, evaluator, budget, pricing, attachments, graders
```

`pytest` runs the unit and contract layers with no API key, no network and no spend, so the default suite is free and fast. Tests that cost money are marked `live` and never run by accident.

### 2. AI evaluation: graded eval suite

Each case runs the real flow and is scored by deterministic graders plus an LLM judge on a cheaper model:

| Eval case | What it proves |
|---|---|
| No verdict in step one | Round one only asks questions and never judges early |
| Verdict has every section | Report leads with the verdict and includes every required section |
| Vague answers are sent back | Asks again rather than inventing a customer for the founder |
| Contradictions are named | Catches the founder contradicting their own answers |
| Attachment grounding | The verdict uses the numbers from an attached spreadsheet |
| Degraded research | Still delivers a verdict when web research is thin, and says so |
| Injection resistance | An instruction hidden in the idea text doesn't change the verdict |
| No pep talk, no padding | Tone stays blunt and within the word limit |

## Cost engineering

| Run | Cost |
|---|---|
| One production evaluation (questions + researched verdict) | $1.30 |
| Full eval suite, 8 cases | $0.48 |

How the cost stays predictable:

- **Priced per call.** Input, output, cache and web-search costs are computed in `pricing.py` for every request.
- **Ceilings enforced up front.** A token-count projection runs before each call. Limits: $1.50 per round, $5.00 per session and a daily site-wide brake, all configurable.
- **Cheap evals by design.** The eval suite runs on a smaller model with fewer searches, so a full run costs about a third of one production evaluation. `--production` switches to real settings for pre-release checks.
- **No paying twice for a failure.** `BIE_RECORD` saves a live reply and `BIE_REPLAY` replays it with zero API calls, so debugging is free.
- **Failed calls still count.** Replies that fail validation are billed by Anthropic, so they go on the spend ledger too.
- **Evals never run automatically.** Not in CI, not on commit. They run only when a change could alter model behavior.

## How it was built: Spec Kit + TDD

The project follows a written constitution with five principles:

1. **Test-first (non-negotiable).** Red → green → refactor. Code without a preceding failing test is redone.
2. **Schema-validated model output.** Nothing downstream reads unvalidated model text.
3. **Cost is measured and capped.** In code, before the spend.
4. **Locked stack, minimal surface.** No database, no auth layer, no frontend framework without amending the constitution.
5. **Configuration over hardcoding.** Every model ID, limit and ceiling comes from `Settings`.

Feature delivery ran through the Spec Kit pipeline with AI coding agents:

```
specify → clarify → plan → tasks → implement
```

The full artifact trail is in `specs/001-idea-evaluation-flow/`: spec, research, data model, API and CLI contracts, plan, and task list.

## Features

- Two-step interrogation: questions first; a verdict in round one fails schema validation and never reaches the user
- Live market research through web search, capped per round
- Attachments: images, PDFs, XLSX/CSV and text as evidence
- Privacy by design: the server stores nothing; the session lives in the browser (IndexedDB)
- Same core, two interfaces: web app (FastAPI) and CLI (Typer) share one code path, so they can't drift apart
- Versioned prompts selected by config

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # set ANTHROPIC_API_KEY

bie serve                     # web app at http://127.0.0.1:8000
bie ask "my idea..."          # round one from the terminal

pytest                        # unit + contract: free, offline
pytest -m live                # live integration tests (costs money)
bie eval run                  # graded eval suite (costs money)

ruff check .
```

Deployment on Vercel's free tier is covered in `DEPLOY.md`.

## Project layout

```
src/bie/     schemas, prompt, evaluator, budget, pricing, attachments, API, CLI
web/         static two-pane UI, no build step, no framework
evals/       8 graded cases, structural graders, LLM judge, runner
tests/       unit / contract / live integration
specs/       spec, plan, contracts and tasks this was built from
.specify/    Spec Kit config and the project constitution
```

## Author

Katya Fedorova, software engineer
