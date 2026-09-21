# Contract: CLI

Typer app in `src/bie/cli.py`, exposed as `bie` (already declared in `pyproject.toml`). Every
command calls the same `evaluator.py` functions the HTTP API calls — no second evaluation path.
Human-readable output by default via Rich; `--json` prints the validated model as JSON to stdout.
Errors go to stderr with a non-zero exit code.

## bie ask "IDEA" [--file PATH]... [--json]
Runs the question round. Prints the numbered questions. `--file` may repeat up to the attachment
limit. Exit 2 if the idea is shorter than the minimum, 3 on budget refusal, 4 on invalid model
output, 5 on upstream failure.

## bie verdict --session PATH [--answers TEXT] [--file PATH]... [--json]
Continues a session stored as a local JSON file (the CLI's equivalent of the browser session),
appending answers and producing either a verdict or a re-ask. Writes the updated session back to
the same path. Same exit codes as `ask`.

## bie evaluate "IDEA" [--answers-file PATH] [--json]
Convenience one-shot for scripting and evals: runs the question round, then the verdict round with
answers supplied non-interactively. Refuses to invent answers when none are given.

## bie serve [--host 127.0.0.1] [--port 8000] [--reload]
Runs the FastAPI app with the static UI.

## bie eval run [--cases PATH] [--json]
Runs the graded eval suite in `evals/`, printing per-case results, the pass rate, and the total
cost of the run.

## Global behaviour
`--model`, `--effort`, and `--prompt-version` override `Settings` for one invocation; no model id
is ever hardcoded in a command (Principle V). Every command prints the round's cost, and refuses
to start a round projected to exceed the ceiling (Principle III).
