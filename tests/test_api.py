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


def test_selftest_reports_engine_health(client):
    r = client.get("/api/selftest")
    assert r.status_code == 200
    d = r.json()
    assert d["engine"] == "mock"
    assert d["status"] == "ok"
    assert "نص تجريبي." in d["text"]


def test_selftest_reports_engine_failure(client, monkeypatch):
    import app.main as m

    class Broken(MockEngine):
        def process_image(self, image_path):
            raise RuntimeError("engine exploded")

    monkeypatch.setattr(m.app.state, "engine_factory", lambda lang: Broken())
    d = client.get("/api/selftest").json()
    assert d["ok"] is False
    assert "engine exploded" in d["error"]


def test_failed_conversion_exposes_first_error(client, tmp_path, monkeypatch):
    import app.main as m

    class Broken(MockEngine):
        def process_image(self, image_path):
            raise RuntimeError("engine exploded")

    monkeypatch.setattr(m.app.state, "engine_factory", lambda lang: Broken())
    s = _convert_to_done(client, tmp_path)
    assert s["state"] == "done"
    assert len(s["failed_pages"]) == 2
    assert "engine exploded" in s["first_error"]


def test_hub_gpu_session_flow(client, monkeypatch):
    monkeypatch.setenv("HUB_MODE", "1")
    monkeypatch.setenv("HUB_TOKEN", "secret1")
    import app.main as m
    monkeypatch.setattr(m, "_gpu", {"url": None, "ts": 0.0})

    assert client.get("/api/config").json()["hub_mode"] is True
    assert client.get("/api/gpu-session").json() == {"online": False, "url": None}

    # wrong token rejected; bad URL rejected
    r = client.post("/api/gpu-session",
                    json={"url": "https://x.trycloudflare.com", "token": "nope"})
    assert r.status_code == 403
    r = client.post("/api/gpu-session",
                    json={"url": "https://evil.example.com", "token": "secret1"})
    assert r.status_code == 400

    r = client.post("/api/gpu-session",
                    json={"url": "https://abc-def.trycloudflare.com/", "token": "secret1"})
    assert r.status_code == 200
    s = client.get("/api/gpu-session").json()
    assert s == {"online": True, "url": "https://abc-def.trycloudflare.com"}


def test_zip_download_and_forget(client, tmp_path):
    s = _convert_to_done(client, tmp_path)
    assert s["state"] == "done"
    book_id = s["book_id"]

    z = client.get(f"/api/result/{book_id}/zip")
    assert z.status_code == 200
    assert z.headers["content-type"] == "application/zip"
    assert len(z.content) > 500

    d = client.delete(f"/api/book/{book_id}")
    assert d.status_code == 200
    # everything about the book is gone
    assert client.get(f"/api/status/{book_id}").status_code == 404
    assert client.get(f"/api/result/{book_id}/zip").status_code == 404
    assert client.get("/api/books").json()["books"] == []
