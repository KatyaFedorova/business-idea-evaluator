"""T057 — what a founder may attach, and what happens when they attach something else."""

from __future__ import annotations

import pytest

from bie.attachments import delete_files, prepare_files, prepare_uploads
from bie.config import Settings
from bie.errors import AttachmentRejected


class FakeFiles:
    def __init__(self) -> None:
        self.uploaded: list[str] = []
        self.deleted: list[str] = []

    def upload(self, *, file, **kwargs):
        name = file[0] if isinstance(file, tuple) else getattr(file, "name", "f")
        self.uploaded.append(name)
        return type("FileMetadata", (), {"id": f"file_{len(self.uploaded)}"})()

    def delete(self, file_id: str, **kwargs):
        self.deleted.append(file_id)


class FakeClient:
    def __init__(self) -> None:
        self.files = FakeFiles()


def test_a_spreadsheet_becomes_text_and_never_leaves_as_a_file(tmp_attachments):
    client = FakeClient()
    [sheet] = prepare_files([tmp_attachments["xlsx"]], client=client)
    assert sheet.kind == "sheet"
    assert sheet.file_id is None
    assert "preorders" in sheet.text
    assert "signups" in sheet.text
    assert client.files.uploaded == []


def test_an_image_is_uploaded_and_referenced_by_id(tmp_attachments):
    client = FakeClient()
    [image] = prepare_files([tmp_attachments["png"]], client=client)
    assert image.kind == "image"
    assert image.file_id == "file_1"
    assert image.text is None
    assert client.files.uploaded == ["shot.png"]


def test_text_and_csv_pass_through_as_text(tmp_attachments):
    client = FakeClient()
    csv_file, txt = prepare_files(
        [tmp_attachments["csv"], tmp_attachments["txt"]], client=client
    )
    assert csv_file.kind == "sheet" and "tiktok" in csv_file.text
    assert txt.kind == "text" and "three of five" in txt.text


def test_an_unsupported_type_is_rejected_by_name(tmp_path):
    binary = tmp_path / "trojan.exe"
    binary.write_bytes(b"MZ")
    with pytest.raises(AttachmentRejected) as exc:
        prepare_files([binary], client=FakeClient())
    assert "trojan.exe" in str(exc.value)


def test_an_oversized_file_names_the_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("BIE_MAX_ATTACHMENT_MB", "1")
    fat = tmp_path / "fat.txt"
    fat.write_text("x" * (2 * 1024 * 1024))
    with pytest.raises(AttachmentRejected) as exc:
        prepare_files([fat], client=FakeClient(), settings=Settings())
    assert "1 MB" in str(exc.value)


def test_too_many_files_names_the_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("BIE_MAX_ATTACHMENTS", "2")
    paths = []
    for i in range(3):
        path = tmp_path / f"n{i}.txt"
        path.write_text("hello")
        paths.append(path)
    with pytest.raises(AttachmentRejected) as exc:
        prepare_files(paths, client=FakeClient(), settings=Settings())
    assert "2" in str(exc.value)


def test_an_unreadable_file_is_flagged_not_fatal(tmp_path):
    broken = tmp_path / "broken.xlsx"
    broken.write_bytes(b"this is not a spreadsheet")
    good = tmp_path / "fine.txt"
    good.write_text("readable")
    client = FakeClient()
    broken_result, good_result = prepare_files([broken, good], client=client)
    assert broken_result.readable is False
    assert broken_result.error
    assert good_result.readable is True


def test_uploads_carry_the_declared_media_type(tmp_attachments):
    client = FakeClient()
    data = tmp_attachments["png"].read_bytes()
    [image] = prepare_uploads([("shot.png", "image/png", data)], client=client)
    assert image.kind == "image"
    assert image.size_bytes == len(data)
    assert image.file_id == "file_1"


def test_deleting_is_forgiving_of_ids_that_are_already_gone():
    client = FakeClient()

    def boom(file_id, **kwargs):
        raise RuntimeError("404")

    client.files.delete = boom
    delete_files(["file_1"], client=client)  # must not raise
