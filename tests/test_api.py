"""Phase D+E tests: FastAPI endpoints with a mock engine (no OCR models)."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.engines.base import OCREngine
from app.models import Block
from tests.make_fixture import make_fixture


class MockEngine(OCREngine):
    name = "mock"
    lang = "ar"

    def process_image(self, image_path):
        return [Block(type="text", bbox=[0, 0, 1, 1], reading_order=0,
                      text="نص تجريبي.")]

    def version(self):
        return "0"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "INPUT_DIR", tmp_path / "input")
    monkeypatch.setattr(main, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(main.app.state, "engine_factory", lambda lang: MockEngine())
    monkeypatch.setattr(main, "_jobs", {})
    return TestClient(main.app)


def _upload(client, tmp_path, pages=2):
    pdf_path = make_fixture(tmp_path / "fixture.pdf", pages=pages)
    with pdf_path.open("rb") as f:
        return client.post(
            "/api/upload",
            files={"file": ("كتاب.pdf", f, "application/pdf")},
        )


def test_upload_returns_file_info(client, tmp_path):
    res = _upload(client, tmp_path)
    assert res.status_code == 200
    info = res.json()
    assert info["filename"] == "كتاب.pdf"
    assert info["page_count"] == 2
    assert info["size_bytes"] > 0
    assert info["state"] == "uploaded"


def test_upload_rejects_non_pdf(client, tmp_path):
    res = client.post("/api/upload", files={"file": ("x.txt", b"hi", "text/plain")})
    assert res.status_code == 400


def test_convert_and_poll_to_done(client, tmp_path):
    book_id = _upload(client, tmp_path).json()["book_id"]

    res = client.post(f"/api/convert/{book_id}")
    assert res.status_code == 200

    for _ in range(100):
        s = client.get(f"/api/status/{book_id}").json()
        if s["state"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert s["state"] == "done", s.get("error")
    assert s["current_page"] == s["page_count"] == 2
    assert s["failed_pages"] == []
    assert s["ocr_engine"] == "mock"

    md = client.get(f"/api/result/{book_id}/book.md")
    assert md.status_code == 200
    assert "نص تجريبي." in md.text


def test_convert_unknown_book_and_bad_lang(client, tmp_path):
    assert client.post("/api/convert/nope").status_code == 404
    book_id = _upload(client, tmp_path).json()["book_id"]
    assert client.post(f"/api/convert/{book_id}?lang=xx").status_code == 400


def test_languages_endpoint(client):
    data = client.get("/api/languages").json()
    assert data["default"] == "ar"
    assert "ar" in data["languages"]


def _convert_to_done(client, tmp_path):
    book_id = _upload(client, tmp_path).json()["book_id"]
    client.post(f"/api/convert/{book_id}")
    for _ in range(100):
        s = client.get(f"/api/status/{book_id}").json()
        if s["state"] in ("done", "failed"):
            return s
        time.sleep(0.05)
    return s


def test_reader_and_books_list(client, tmp_path):
    s = _convert_to_done(client, tmp_path)
    assert s["state"] == "done"

    books = client.get("/api/books").json()["books"]
    assert len(books) == 1
    assert books[0]["book_name"] == "كتاب"
    assert books[0]["page_count"] == 2

    page = client.get(books[0]["reader_url"])
    assert page.status_code == 200
    assert "نص تجريبي." in page.text
    assert 'dir="rtl"' in page.text


def test_reader_rejects_missing_and_traversal(client, tmp_path):
    assert client.get("/reader/غير-موجود").status_code == 404
    assert client.get("/reader/%2e%2e%2fetc").status_code == 404
