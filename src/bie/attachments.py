"""What a founder attaches, and what the evaluator can do with it.

Images and PDFs go to the Files API and travel as ids, so the bytes cross the wire
once however many rounds follow. Spreadsheets and text are converted here, because
the model reads text and does not read XLSX.
"""

from __future__ import annotations

import csv
import io
import logging
import mimetypes
import uuid
from pathlib import Path
from typing import Any

from bie.config import ALLOWED_MEDIA_TYPES, Settings
from bie.errors import AttachmentRejected
from bie.schemas import Attachment

EXTENSION_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".md": "text/markdown",
}
MAX_SHEET_ROWS = 500

logger = logging.getLogger(__name__)


def media_type_for(filename: str, declared: str | None = None) -> str:
    if declared and declared in ALLOWED_MEDIA_TYPES:
        return declared
    suffix = Path(filename).suffix.lower()
    if suffix in EXTENSION_TYPES:
        return EXTENSION_TYPES[suffix]
    guessed, _ = mimetypes.guess_type(filename)
    if guessed in ALLOWED_MEDIA_TYPES:
        return guessed
    raise AttachmentRejected(
        f"{filename} is not a file type we can read. Attach an image, a PDF, a "
        "spreadsheet (XLSX or CSV), or a text file."
    )


def sheet_to_text(data: bytes) -> str:
    """One section per sheet, header row kept, cells tab separated."""
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    sections = []
    for worksheet in workbook.worksheets:
        lines = [f"# {worksheet.title}"]
        for index, row in enumerate(worksheet.iter_rows(values_only=True)):
            if index >= MAX_SHEET_ROWS:
                lines.append(f"... truncated at {MAX_SHEET_ROWS} rows")
                break
            if row is None or all(cell is None for cell in row):
                continue
            lines.append("\t".join("" if cell is None else str(cell) for cell in row))
        sections.append("\n".join(lines))
    workbook.close()
    return "\n\n".join(sections)


def csv_to_text(data: bytes) -> str:
    reader = csv.reader(io.StringIO(data.decode("utf-8", errors="replace")))
    rows = ["\t".join(row) for index, row in enumerate(reader) if index < MAX_SHEET_ROWS]
    return "\n".join(rows)


def _check_limits(count: int, sizes: list[int], settings: Settings) -> None:
    if count > settings.max_attachments:
        raise AttachmentRejected(
            f"That is {count} files. You can attach up to {settings.max_attachments} "
            "at a time."
        )
    for size in sizes:
        if size > settings.max_attachment_bytes:
            raise AttachmentRejected(
                f"That file is larger than the {settings.max_attachment_mb} MB limit."
            )


def prepare_uploads(
    files: list[tuple[str, str | None, bytes]],
    *,
    client: Any,
    settings: Settings | None = None,
) -> list[Attachment]:
    """Validate, convert and upload. One unreadable file does not fail the batch."""
    settings = settings or Settings()
    _check_limits(len(files), [len(data) for _, _, data in files], settings)

    prepared: list[Attachment] = []
    for filename, declared, data in files:
        media_type = media_type_for(filename, declared)
        kind = ALLOWED_MEDIA_TYPES[media_type]
        attachment = Attachment(
            id=f"att_{uuid.uuid4().hex[:12]}",
            filename=filename,
            kind=kind,
            size_bytes=len(data),
        )
        try:
            if kind == "sheet":
                attachment.text = (
                    csv_to_text(data) if media_type == "text/csv" else sheet_to_text(data)
                )
            elif kind == "text":
                attachment.text = data.decode("utf-8", errors="replace")
            else:
                uploaded = client.files.upload(file=(filename, io.BytesIO(data), media_type))
                attachment.file_id = uploaded.id
        except AttachmentRejected:
            raise
        except Exception as exc:  # noqa: BLE001 - a broken file is a fact, not a crash
            attachment.readable = False
            attachment.error = f"{type(exc).__name__}"
        prepared.append(attachment)
    return prepared


def prepare_files(
    paths: list[Path], *, client: Any, settings: Settings | None = None
) -> list[Attachment]:
    """The CLI's door into the same pipeline."""
    payload = []
    for path in paths:
        if not path.exists():
            raise AttachmentRejected(f"No file at {path}.")
        payload.append((path.name, None, path.read_bytes()))
    return prepare_uploads(payload, client=client, settings=settings)


def delete_files(file_ids: list[str], *, client: Any) -> None:
    """Clearing a session deletes what was uploaded. An id already gone is fine."""
    for file_id in file_ids:
        try:
            client.files.delete(file_id)
        except Exception as exc:  # noqa: BLE001 - deletion is best effort by design
            logger.info("could not delete %s: %s", file_id, type(exc).__name__)


def content_blocks(attachments: list[Attachment]) -> list[dict]:
    """Native blocks for what the model reads directly: images and PDFs."""
    blocks: list[dict] = []
    for attachment in attachments:
        if not attachment.readable or not attachment.file_id:
            continue
        if attachment.kind == "image":
            blocks.append(
                {"type": "image", "source": {"type": "file", "file_id": attachment.file_id}}
            )
        elif attachment.kind == "pdf":
            blocks.append(
                {"type": "document", "source": {"type": "file", "file_id": attachment.file_id}}
            )
    return blocks
