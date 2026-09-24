"""Don't pay twice for an answer we already have.

Two caches, both keyed on a hash of everything that could change the answer:

- round one: the questions round a verdict case needs before it can answer. Only one
  case grades it, but every verdict case used to buy it fresh.
- results: a case that passed with the same prompt, code, case file, rubric and settings
  is not run again. `--fresh` ignores both.

A change to the prompt, the evaluator, the schemas, the graders or the rubric changes the
key, so nothing stale is ever reused.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from bie import prompts
from bie.config import Settings
from bie.schemas import Round

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = Path(__file__).parent / ".cache"
RESULTS_PATH = CACHE_DIR / "results.json"

# Code whose change can change what the model returns.
EVALUATOR_SOURCES = ("src/bie/evaluator.py", "src/bie/schemas.py", "src/bie/claude.py")
# Code and data whose change can change how a reply is graded.
GRADING_SOURCES = ("evals/graders.py", "evals/rubric.py", "evals/rubric.yaml", "evals/run.py")


def _hash(*parts: Any) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part if isinstance(part, bytes) else str(part).encode())
        digest.update(b"\0")
    return digest.hexdigest()[:20]


def _sources(paths: tuple[str, ...]) -> list[bytes]:
    return [(ROOT / p).read_bytes() for p in paths]


def _model_settings(settings: Settings) -> tuple:
    return (
        settings.prompt_version,
        settings.model,
        settings.question_effort,
        settings.verdict_effort,
        settings.max_searches,
        settings.max_tokens,
        settings.max_reasks,
    )


def round_one_key(idea: str, settings: Settings) -> str:
    return _hash(
        "round-one",
        prompts.load(settings.prompt_version),
        *_sources(EVALUATOR_SOURCES),
        settings.prompt_version,
        settings.model,
        settings.question_effort,
        idea.strip(),
    )


def case_key(case: dict, attachment_bytes: list[bytes], settings: Settings, rubric: bool) -> str:
    return _hash(
        "case",
        prompts.load(settings.prompt_version),
        *_sources(EVALUATOR_SOURCES),
        *_sources(GRADING_SOURCES),
        Path(case["path"]).read_bytes(),
        *attachment_bytes,
        *_model_settings(settings),
        settings.judge_model if rubric else "no-rubric",
    )


def load_round_one(key: str) -> Round | None:
    path = CACHE_DIR / "round_one" / f"{key}.json"
    if not path.exists():
        return None
    return Round.model_validate_json(path.read_text())


def save_round_one(key: str, round_: Round) -> None:
    path = CACHE_DIR / "round_one" / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(round_.model_dump_json(indent=2))


def load_results() -> dict[str, dict]:
    if not RESULTS_PATH.exists():
        return {}
    try:
        return json.loads(RESULTS_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def save_results(results: dict[str, dict]) -> None:
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(results, indent=2, sort_keys=True))
