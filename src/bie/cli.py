"""The command line. Every command calls the same functions the HTTP API calls.

Exit codes: 2 idea too short, 3 budget refusal, 4 invalid model output, 5 upstream failure.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from bie.claude import build_client
from bie.config import Settings
from bie.errors import BieError, BudgetExceeded, IdeaTooShort, InvalidModelOutput
from bie.evaluator import ask_questions, evaluate
from bie.schemas import Attachment, FounderMessage, Round

console = Console()
err_console = Console(stderr=True)

app = typer.Typer(
    name="bie",
    help="Evaluate a business idea: questions first, verdict second.",
    no_args_is_help=True,
)
eval_app = typer.Typer(help="Run the graded eval suite.", no_args_is_help=True)
app.add_typer(eval_app, name="eval")

MODEL_OPT = typer.Option(None, "--model", help="Override the model for this run.")
EFFORT_OPT = typer.Option(None, "--effort", help="Override reasoning effort for this run.")
PROMPT_OPT = typer.Option(None, "--prompt-version", help="Override the prompt version.")
JSON_OPT = typer.Option(False, "--json", help="Print the validated result as JSON.")

EXIT_CODES = {
    "idea_too_short": 2,
    "budget_exceeded": 3,
    "invalid_model_output": 4,
}


def _settings(model: str | None, effort: str | None, prompt_version: str | None) -> Settings:
    """Overrides apply to this invocation only, and still go through Settings.

    Deliberately not os.environ: a command must not change the environment of
    anything that runs after it.
    """
    overrides: dict[str, object] = {}
    if model:
        overrides["model"] = model
    if effort:
        overrides["question_effort"] = effort
        overrides["verdict_effort"] = effort
        overrides["effort"] = effort
    if prompt_version:
        overrides["prompt_version"] = prompt_version
    return replace(Settings(), **overrides) if overrides else Settings()


def _fail(exc: BieError) -> None:
    err_console.print(f"[red]{exc.message}[/red]")
    raise typer.Exit(EXIT_CODES.get(exc.code, 5))


def _load_session(path: Path) -> dict:
    if not path.exists():
        err_console.print(f"[red]No session at {path}. Run `bie ask` first.[/red]")
        raise typer.Exit(2)
    return json.loads(path.read_text())


def _save_session(path: Path, session: dict) -> None:
    path.write_text(json.dumps(session, indent=2, default=str))


def _print_questions(round_: Round) -> None:
    if round_.questions.note:
        console.print(f"[yellow]{round_.questions.note}[/yellow]\n")
    for question in round_.questions.questions:
        console.print(f"{question.number}. {question.text}")
    console.print(f"\n[dim]{round_.usage.model} · ${round_.cost_usd:.4f}[/dim]")


def _print_report(round_: Round) -> None:
    report = round_.report
    line = report.verdict.replace("_", " ")
    if report.verdict == "PROCEED_ONLY_AFTER_TESTING":
        line = f"PROCEED ONLY AFTER TESTING {report.verdict_condition}"
    elif report.verdict == "DONT_PROCEED":
        line = "DON'T PROCEED"
    console.print(f"[bold]{line}[/bold]")
    console.print(f"Confidence: {report.confidence} — {report.confidence_movers}\n")
    console.print("[bold]Works because[/bold]")
    for item in report.works_because:
        console.print(f"  · {item}")
    console.print("\n[bold]Fails because[/bold]")
    for failure in sorted(report.fails_because, key=lambda f: f.rank):
        tag = " [dim](guess)[/dim]" if failure.is_guess else ""
        console.print(f"  {failure.rank}. {failure.text}{tag}")
    console.print(f"\n[bold]Riskiest assumption[/bold]\n  {report.riskiest_assumption}")
    plan = report.validation_plan
    console.print(f"\n[bold]Validation plan[/bold] ({plan.duration_days} days)")
    for step in plan.steps:
        console.print(f"  · {step}")
    console.print(f"  Pass: {plan.pass_threshold}")
    console.print(f"  Fail: {plan.fail_threshold}")
    console.print("\n[bold]Research[/bold]")
    for direction in report.research_directions:
        who = f" ({direction.competitor})" if direction.competitor else ""
        console.print(f"  · {direction.question}{who} — {direction.where_to_look}")
    console.print("\n[bold]Kill criteria[/bold]")
    for item in report.kill_criteria:
        console.print(f"  · {item}")
    if report.contradictions:
        console.print("\n[bold]Contradictions in your answers[/bold]")
        for item in report.contradictions:
            console.print(f"  · {item}")
    if round_.sources:
        console.print("\n[bold]Sources[/bold]")
        for source in round_.sources:
            console.print(f"  · {source.title or source.url} — {source.url}")
    if round_.research_status != "ok":
        console.print(
            f"\n[yellow]Research was {round_.research_status}: "
            "treat unsourced claims as unverified.[/yellow]"
        )
    console.print(f"\n[dim]{round_.usage.model} · ${round_.cost_usd:.4f}[/dim]")


def _attachments(paths: list[str] | None) -> list[Attachment]:
    if not paths:
        return []
    from bie.attachments import prepare_files

    return prepare_files([Path(p) for p in paths], client=build_client())


def _emit(round_: Round, as_json: bool, printer: Any) -> None:
    if as_json:
        console.print_json(round_.model_dump_json())
    else:
        printer(round_)


@app.command()
def ask(
    idea: str = typer.Argument(..., help="The business idea, in your own words."),
    session: str = typer.Option(None, "--session", help="Write the session to this file."),
    file: list[str] = typer.Option(None, "--file", help="Attach a file (repeatable)."),
    model: str = MODEL_OPT,
    effort: str = EFFORT_OPT,
    prompt_version: str = PROMPT_OPT,
    as_json: bool = JSON_OPT,
) -> None:
    """Round one: get the questions."""
    settings = _settings(model, effort, prompt_version)
    try:
        attachments = _attachments(file)
        round_ = ask_questions(
            idea, attachments=attachments, settings=settings, client=build_client()
        )
    except BieError as exc:
        _fail(exc)
    if session:
        _save_session(
            Path(session),
            {
                "idea": idea,
                "prompt_version": settings.prompt_version,
                "rounds": [json.loads(round_.model_dump_json())],
                "attachments": [json.loads(a.model_dump_json()) for a in attachments],
                "total_cost_usd": round_.cost_usd,
            },
        )
    _emit(round_, as_json, _print_questions)


@app.command()
def verdict(
    session: str = typer.Option(..., "--session", help="Path to the session JSON file."),
    answers: str = typer.Option(None, "--answers", help="Your answers to the questions."),
    file: list[str] = typer.Option(None, "--file", help="Attach a file (repeatable)."),
    model: str = MODEL_OPT,
    effort: str = EFFORT_OPT,
    prompt_version: str = PROMPT_OPT,
    as_json: bool = JSON_OPT,
) -> None:
    """Round two onwards: answer the questions and get the verdict."""
    settings = _settings(model, effort, prompt_version)
    path = Path(session)
    saved = _load_session(path)
    try:
        new_attachments = _attachments(file)
        attachments = [Attachment.model_validate(a) for a in saved.get("attachments", [])]
        attachments += new_attachments
        message = FounderMessage(
            text=answers or "", attachment_ids=[a.id for a in new_attachments]
        )
        round_ = evaluate(
            saved["idea"],
            rounds=[Round.model_validate(r) for r in saved["rounds"]],
            answers=[message],
            attachments=attachments,
            settings=settings,
            client=build_client(),
            spent=saved.get("total_cost_usd", 0.0),
        )
    except BieError as exc:
        _fail(exc)
    saved["rounds"].append(json.loads(round_.model_dump_json()))
    saved["attachments"] = [json.loads(a.model_dump_json()) for a in attachments]
    saved["total_cost_usd"] = saved.get("total_cost_usd", 0.0) + round_.cost_usd
    _save_session(path, saved)
    _emit(round_, as_json, _print_report if round_.kind == "verdict" else _print_questions)


@app.command()
def evaluate_cmd(
    idea: str = typer.Argument(..., help="The business idea."),
    answers_file: str = typer.Option(None, "--answers-file", help="Answers, for scripting."),
    model: str = MODEL_OPT,
    effort: str = EFFORT_OPT,
    prompt_version: str = PROMPT_OPT,
    as_json: bool = JSON_OPT,
) -> None:
    """Both rounds in one go, for scripts and evals. Never invents the answers."""
    settings = _settings(model, effort, prompt_version)
    if not answers_file:
        err_console.print(
            "[red]--answers-file is required: the evaluator will not answer its own "
            "questions.[/red]"
        )
        raise typer.Exit(2)
    try:
        first = ask_questions(idea, settings=settings, client=build_client())
        second = evaluate(
            idea,
            rounds=[first],
            answers=[FounderMessage(text=Path(answers_file).read_text())],
            settings=settings,
            client=build_client(),
            spent=first.cost_usd,
        )
    except BieError as exc:
        _fail(exc)
    _emit(second, as_json, _print_report if second.kind == "verdict" else _print_questions)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    """Serve the web page and the API."""
    import uvicorn

    uvicorn.run("bie.api:app", host=host, port=port, reload=reload)


@eval_app.command("run")
def eval_run(
    cases: str = typer.Option(None, "--cases", help="Directory of eval cases."),
    production: bool = typer.Option(
        False, "--production", help="Use the real model and effort instead of the cheap ones."
    ),
    as_json: bool = JSON_OPT,
) -> None:
    """Run the graded eval suite and report the pass rate and cost."""
    from evals.run import main

    raise typer.Exit(main(cases_dir=cases, as_json=as_json, production=production))


# `evaluate` is the command name; the function is suffixed to avoid shadowing the import.
app.command(name="evaluate")(evaluate_cmd)
app.registered_commands = [c for c in app.registered_commands if c.name != "evaluate-cmd"]

__all__ = ["BudgetExceeded", "IdeaTooShort", "InvalidModelOutput", "app", "build_client"]
