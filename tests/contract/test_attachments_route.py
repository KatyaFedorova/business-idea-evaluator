"""T059 — POST and DELETE /api/attachments."""

from __future__ import annotations

from fastapi.testclient import TestClient

from bie.api import create_app


class FakeFiles:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def upload(self, *, file, **kwargs):
        return type("FileMetadata", (), {"id": "file_abc"})()

    def delete(self, file_id: str, **kwargs):
        self.deleted.append(file_id)


class FakeClient:
    def __init__(self) -> None:
        self.files = FakeFiles()


def client_for(fake) -> TestClient:
    return TestClient(create_app(client_factory=lambda: fake), raise_server_exceptions=False)


def test_upload_returns_one_attachment_per_file(tmp_attachments):
    fake = FakeClient()
    files = [
        ("files", ("numbers.xlsx", tmp_attachments["xlsx"].read_bytes())),
        ("files", ("shot.png", tmp_attachments["png"].read_bytes(), "image/png")),
    ]
    response = client_for(fake).post("/api/attachments", files=files)
    assert response.status_code == 201
    sheet, image = response.json()["attachments"]
    assert sheet["kind"] == "sheet" and "preorders" in sheet["text"]
    assert image["kind"] == "image" and image["file_id"] == "file_abc"
    assert all(a["readable"] for a in (sheet, image))


def test_an_unsupported_type_is_400_and_names_the_file(tmp_attachments):
    response = client_for(FakeClient()).post(
        "/api/attachments", files=[("files", ("trojan.exe", b"MZ"))]
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "attachment_rejected"
    assert "trojan.exe" in body["error"]["message"]


def test_over_the_size_limit_names_the_limit(monkeypatch):
    monkeypatch.setenv("BIE_MAX_ATTACHMENT_MB", "1")
    response = client_for(FakeClient()).post(
        "/api/attachments", files=[("files", ("fat.txt", b"x" * (2 * 1024 * 1024)))]
    )
    assert response.status_code == 400
    assert "1 MB" in response.json()["error"]["message"]


def test_an_unreadable_file_comes_back_flagged_not_failed():
    response = client_for(FakeClient()).post(
        "/api/attachments", files=[("files", ("broken.xlsx", b"not a spreadsheet"))]
    )
    assert response.status_code == 201
    attachment = response.json()["attachments"][0]
    assert attachment["readable"] is False
    assert attachment["error"]


def test_delete_removes_uploaded_files():
    fake = FakeClient()
    response = client_for(fake).request(
        "DELETE", "/api/attachments", json={"file_ids": ["file_abc", "file_gone"]}
    )
    assert response.status_code == 204
    assert fake.files.deleted == ["file_abc", "file_gone"]
