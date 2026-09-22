"""The HTTP surface. Stateless: the browser holds the session and sends it each round."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from bie.attachments import delete_files, prepare_uploads
from bie.budget import daily_spend
from bie.claude import build_client
from bie.config import ALLOWED_MEDIA_TYPES, Settings
from bie.errors import BieError
from bie.evaluator import ask_questions, evaluate
from bie.schemas import Attachment, FounderMessage, Round

WEB_DIR = Path(__file__).resolve().parents[2] / "web"

logger = logging.getLogger("bie")


class QuestionsRequest(BaseModel):
    idea: str
    attachments: list[Attachment] = Field(default_factory=list)


class DeleteAttachmentsRequest(BaseModel):
    file_ids: list[str] = Field(default_factory=list)


class VerdictRequest(BaseModel):
    idea: str
    rounds: list[Round] = Field(default_factory=list)
    answers: list[FounderMessage] = Field(default_factory=list)
    attachments: list[Attachment] = Field(default_factory=list)
    spent: float = 0.0


def create_app(
    settings: Settings | None = None,
    *,
    mount_static: bool = True,
    client_factory: Callable[[], Any] = build_client,
) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Business Idea Evaluator", version="0.1.0")

    @app.exception_handler(BieError)
    async def _bie_error(request: Request, exc: BieError) -> JSONResponse:
        # The founder sees exc.message. exc.detail is logged and never returned.
        logger.warning(
            "%s on %s: %s | detail=%s",
            exc.code,
            request.url.path,
            exc.message,
            exc.detail or "-",
        )
        return JSONResponse(status_code=exc.status_code, content=exc.as_payload())

    @app.get("/api/health")
    def health() -> dict:
        current = Settings()
        return {
            "status": "ok",
            "model": current.model,
            "prompt_version": current.prompt_version,
            "has_api_key": current.has_api_key,
        }

    @app.get("/api/limits")
    def limits() -> dict:
        current = Settings()
        return {
            "min_idea_chars": current.min_idea_chars,
            "max_attachments": current.max_attachments,
            "max_attachment_bytes": current.max_attachment_bytes,
            "allowed_media_types": sorted(ALLOWED_MEDIA_TYPES),
            "max_cost_per_round_usd": current.max_cost_per_round_usd,
            "max_cost_per_session_usd": current.max_cost_per_session_usd,
            "max_cost_per_day_usd": current.max_cost_per_day_usd,
            "spent_today_usd": round(daily_spend.spent, 4),
            "max_reasks": current.max_reasks,
        }

    # Mounted last, and skippable, because a mount at "/" shadows anything added after it.
    @app.post("/api/questions")
    def questions(request: QuestionsRequest) -> dict:
        """Round one. Questions only — a leaked verdict fails validation upstream."""
        round_ = ask_questions(
            request.idea,
            attachments=request.attachments,
            settings=Settings(),
            client=client_factory(),
        )
        return {
            "kind": "questions",
            "questions": round_.questions,
            "usage": round_.usage,
            "cost_usd": round_.cost_usd,
        }

    @app.post("/api/verdict")
    def verdict(request: VerdictRequest) -> dict:
        """Round two onwards. The client sends the transcript; the server keeps nothing."""
        round_ = evaluate(
            request.idea,
            rounds=request.rounds,
            answers=request.answers,
            attachments=request.attachments,
            settings=Settings(),
            client=client_factory(),
            spent=request.spent,
        )
        return {
            "kind": round_.kind,
            "report": round_.report,
            "questions": round_.questions,
            "sources": round_.sources,
            "research_status": round_.research_status,
            "usage": round_.usage,
            "cost_usd": round_.cost_usd,
        }

    @app.post("/api/attachments", status_code=201)
    async def upload(files: list[UploadFile] = File(...)) -> dict:
        """Read once here; later rounds carry ids and extracted text, not bytes."""
        payload = [(f.filename or "file", f.content_type, await f.read()) for f in files]
        attachments = prepare_uploads(payload, client=client_factory(), settings=Settings())
        return {"attachments": attachments}

    @app.delete("/api/attachments", status_code=204)
    def forget(request: DeleteAttachmentsRequest) -> Response:
        """Clearing a session deletes what it uploaded."""
        delete_files(request.file_ids, client=client_factory())
        return Response(status_code=204)

    # Mounted last, and skippable, because a mount at "/" shadows anything added after it.
    if mount_static and WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()
