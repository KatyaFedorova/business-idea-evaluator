"""The two-step engine. Both the API and the CLI call these functions and nothing else.

Round one asks questions and must not evaluate. Round two researches and delivers the
verdict. Everything the founder types, uploads or links to is wrapped in a labelled data
block, because the prompt treats those blocks as material rather than instructions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bie import prompts
from bie.attachments import content_blocks
from bie.budget import check_daily, check_round, check_session, project_round_cost
from bie.claude import build_client, complete, research_tools
from bie.config import Settings
from bie.errors import IdeaTooShort
from bie.schemas import (
    Attachment,
    FinalDecision,
    FounderMessage,
    QuestionSet,
    Round,
    RoundDecision,
)

STEP_ONE = (
    "OPERATOR INSTRUCTION: You are in STEP 1. Ask the numbered questions and nothing else. "
    "Do not evaluate the idea, do not give a verdict, do not hint at one. Fill the given "
    "schema, choosing the topic that best matches each question."
)
STEP_TWO = (
    "OPERATOR INSTRUCTION: You are in STEP 2. The founder has answered. Research the market "
    "before you answer, then fill the given schema. If an answer is vague enough that a verdict "
    "would rest on your assumption rather than their fact, set decision to reask, say in the "
    "note exactly what was vague, and ask again. Otherwise set decision to verdict: lead with "
    "the verdict, label every guess, name real competitors you actually found, point at any "
    "contradiction between the founder's own answers. LENGTH: the whole report must read as "
    "bullets and stay under 300 words. One line per reason, per step, per criterion — no "
    "sentence over 20 words, no preamble, no restating the idea back. Cut rather than run "
    "long; the schema will reject anything that does not fit. The report has no field for "
    "research directions or missing data: name existing products in prior_art and put "
    "anything you would need to check into the validation plan instead."
)
NO_RESEARCH_NOTE = (
    " Research is switched off for this run, so you have no sources: mark every market "
    "claim as a guess and say plainly in your confidence line that nothing was verified."
)
STEP_TWO_FINAL = (
    " This is past the last round of questions allowed in this session: you must give a verdict "
    "now, however thin the answers are, and say plainly in your confidence line what is still "
    "unknown."
)


def _block(label: str, body: str) -> str:
    return f"[{label}]\n{body}\n[/{label}]"


def _attachment_blocks(attachments: list[Attachment]) -> list[str]:
    blocks = []
    for a in attachments:
        if not a.readable:
            blocks.append(_block(f"ATTACHMENT {a.filename}", f"(could not be read: {a.error})"))
        elif a.text:
            blocks.append(_block(f"ATTACHMENT {a.filename}", a.text))
        else:
            blocks.append(
                _block(f"ATTACHMENT {a.filename}", f"({a.kind} file, sent with this message)")
            )
    return blocks


def _by_id(attachments: list[Attachment]) -> dict[str, Attachment]:
    return {a.id: a for a in attachments}


def render_questions(questions: QuestionSet) -> str:
    """How an earlier question round is replayed to the model: as plain text.

    Deliberately not the raw assistant blocks — those carry encrypted search content
    that must be echoed back byte for byte, and this application does not keep them.
    """
    lines = []
    if questions.note:
        lines.append(questions.note)
    lines += [f"{q.number}. {q.text}" for q in questions.questions]
    return "\n".join(lines)


def _founder_turn(
    label: str, messages: list[FounderMessage], attachments: list[Attachment]
) -> list[dict]:
    """Text in labelled blocks, images and PDFs as native content blocks."""
    index = _by_id(attachments)
    parts: list[str] = []
    native: list[dict] = []
    for message in messages:
        if message.text.strip():
            parts.append(_block(label, message.text.strip()))
        carried = [index[i] for i in message.attachment_ids if i in index]
        parts.extend(_attachment_blocks(carried))
        native.extend(content_blocks(carried))
    return [*native, {"type": "text", "text": "\n\n".join(parts)}]


def _transcript(
    idea: str, rounds: list[Round], answers: list[FounderMessage], attachments: list[Attachment]
) -> list[dict]:
    opening = [_block("IDEA", idea.strip())]
    native: list[dict] = []
    first_round = rounds[0] if rounds else None
    if first_round:
        for message in first_round.submission:
            carried = [a for a in attachments if a.id in message.attachment_ids]
            opening.extend(_attachment_blocks(carried))
            native.extend(content_blocks(carried))
    messages: list[dict] = [
        {"role": "user", "content": [*native, {"type": "text", "text": "\n\n".join(opening)}]}
    ]

    for round_ in rounds:
        if round_.questions is not None:
            messages.append({"role": "assistant", "content": render_questions(round_.questions)})
        if round_.kind != "questions" and round_.submission:
            messages.append(
                {
                    "role": "user",
                    "content": _founder_turn("ANSWER", round_.submission, attachments),
                }
            )
    messages.append({"role": "user", "content": _founder_turn("ANSWER", answers, attachments)})
    return messages


def ask_questions(
    idea: str,
    *,
    attachments: list[Attachment] | None = None,
    settings: Settings | None = None,
    client: Any | None = None,
) -> Round:
    """Round one. Refuses a too-short idea before spending anything."""
    settings = settings or Settings()
    attachments = attachments or []
    if len(idea.strip()) < settings.min_idea_chars:
        raise IdeaTooShort(
            f"Tell us a bit more — at least {settings.min_idea_chars} characters. "
            "Two or three sentences about who it is for and how it makes money."
        )
    client = client or build_client()

    system = prompts.load(settings.prompt_version)
    text = "\n\n".join([_block("IDEA", idea.strip()), *_attachment_blocks(attachments)])
    content = [*content_blocks(attachments), {"type": "text", "text": text}]
    messages = [{"role": "user", "content": content}]

    projected = project_round_cost(
        client, model=settings.model, system=system, messages=messages, settings=settings
    )
    check_round(projected, settings)
    check_daily(projected, settings)

    reply = complete(
        client,
        system=system,
        instruction=STEP_ONE,
        messages=messages,
        schema=QuestionSet,
        effort=settings.question_effort,
        settings=settings,
    )
    return Round(
        index=0,
        kind="questions",
        submitted_at=datetime.now(UTC),
        submission=[FounderMessage(text=idea.strip(), attachment_ids=[a.id for a in attachments])],
        questions=reply.parsed,
        usage=reply.usage,
        cost_usd=reply.usage.cost_usd,
    )


def evaluate(
    idea: str,
    *,
    rounds: list[Round],
    answers: list[FounderMessage],
    attachments: list[Attachment] | None = None,
    settings: Settings | None = None,
    client: Any | None = None,
    spent: float = 0.0,
) -> Round:
    """Round two onwards: research, then the verdict."""
    settings = settings or Settings()
    attachments = attachments or []
    client = client or build_client()

    system = prompts.load(settings.prompt_version)
    messages = _transcript(idea, rounds, answers, attachments)
    tools = research_tools(settings) if settings.research_enabled else None

    projected = project_round_cost(
        client,
        model=settings.model,
        system=system,
        messages=messages,
        settings=settings,
        tools=tools,
    )
    check_round(projected, settings)
    check_session(spent=spent, projected=projected, settings=settings)
    check_daily(projected, settings)

    reasks = sum(1 for r in rounds if r.kind == "reask")
    final = reasks >= settings.max_reasks
    instruction = STEP_TWO + (STEP_TWO_FINAL if final else "")
    if not settings.research_enabled:
        instruction += NO_RESEARCH_NOTE

    reply = complete(
        client,
        system=system,
        instruction=instruction,
        messages=messages,
        schema=FinalDecision if final else RoundDecision,
        effort=settings.verdict_effort,
        settings=settings,
        research=settings.research_enabled,
    )
    decision: RoundDecision = reply.parsed
    is_reask = decision.decision == "reask"
    return Round(
        index=len(rounds),
        kind="reask" if is_reask else "verdict",
        submitted_at=datetime.now(UTC),
        submission=answers,
        questions=decision.reask if is_reask else None,
        report=decision.report,
        sources=reply.sources,
        research_status=reply.research_status,
        usage=reply.usage,
        cost_usd=reply.usage.cost_usd,
    )
