# Business Idea Evaluator

A skeptical early-stage investor in a web page. You describe a business idea; it asks you the
questions whose answers would most change its verdict, and only once you have answered does it
tell you PROCEED, PROCEED ONLY AFTER TESTING X, or DON'T PROCEED — with the reasons, the riskiest
assumption, a two-week no-code validation plan, named competitors, and kill criteria.

No scores. No pep talk.

See `specs/001-idea-evaluation-flow/` for the specification, plan and tasks.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env    # then set ANTHROPIC_API_KEY
```

## Run

```bash
bie serve          # http://127.0.0.1:8000
bie ask "..."      # question round from the CLI
pytest             # unit + contract tests (no API key needed)
ruff check .
```
