"""HTTP surface of the book-discovery layer. Mock source only, no network."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.engines.base import OCREngine
from app.models import Block
from app.booksources.sources.mock import MOCK_HOST, MockLibrarySource
from tests.make_fixture import make_fixture


class MockEngine(OCREngine):
    name = "mock"
    lang = "ar"

    def process_image(self, image_path):
        return [Block(type="text", bbox=[0, 0, 10, 10], reading_order=0,
                      text="نص تجريبي", confidence=0.9)]

    def version(self):
        return "mock-1.0"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(main.app.state, "engine_factory", lambda lang: MockEngine())
    from app.jobs import JobStore
    from app.booksources.cache import SearchCache
    monkeypatch.setattr(main, "_book_jobs", JobStore(tmp_path / "jobs"))
    monkeypatch.setattr(main, "_search_cache", SearchCache(tmp_path / "cache.json"))
    monkeypatch.setattr(main, "_offered", {})
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def library(tmp_path, monkeypatch):
    pdf = make_fixture(tmp_path / "fixture.pdf", pages=2)
    source = MockLibrarySource([{
        "slug": "qatr", "title": "شرح قطر الندى وبل الصدى", "author": "ابن هشام",
        "pages": 2, "pdf_url": f"https://{MOCK_HOST}/files/qatr.pdf",
        "local_file": str(pdf), "file_type": "pdf",
    }])
    monkeypatch.setattr(main, "enabled_sources", lambda: [source])
    return source


def test_sources_endpoint_reports_alfeker_as_disabled(client):
    data = client.get("/api/books/sources").json()
    alfeker = next(s for s in data["sources"] if s["id"] == "alfeker")
    assert alfeker["status"]["enabled"] is False
    assert "UNVERIFIED" in alfeker["status"]["reason"]


def test_search_without_an_enabled_source_is_refused(client, monkeypatch):
    monkeypatch.setattr(main, "enabled_sources", lambda: [])
    response = client.post("/api/books/search", json={"query": "شرح قطر الندى"})
    assert response.status_code == 503
    assert "رفع PDF يدويًا" in response.json()["detail"]


def test_search_returns_ranked_candidates(client, library):
    data = client.post("/api/books/search",
                       json={"query": "شرح قطر الندى", "author": "ابن هشام"}).json()
    assert data["candidates"], data
    assert data["candidates"][0]["author"] == "ابن هشام"
    assert data["candidates"][0]["source"] == "mock"


def test_empty_query_refused(client, library):
    assert client.post("/api/books/search", json={"query": "   "}).status_code == 400


def test_acquire_refuses_an_id_we_never_offered(client, library):
    response = client.post("/api/books/acquire", json={"candidate_id": "mock:forged"})
    assert response.status_code == 404


def test_acquire_ignores_any_url_the_client_sends(client, library):
    """The client cannot smuggle a URL: only ids we issued are accepted."""
    response = client.post("/api/books/acquire", json={
        "candidate_id": "mock:qatr",
        "pdf_url": "https://169.254.169.254/latest/meta-data/",
    })
    assert response.status_code == 404   # nothing was offered yet in this session


def test_full_flow_search_then_acquire_then_markdown(client, library):
    search = client.post("/api/books/search", json={"query": "شرح قطر الندى"}).json()
    candidate_id = search["candidates"][0]["id"]

    job = client.post("/api/books/acquire", json={"candidate_id": candidate_id}).json()
    assert job["state"] in ("queued", "downloading", "processing")

    for _ in range(100):
        job = client.get(f"/api/books/jobs/{job['id']}").json()
        if job["state"] in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.05)

    assert job["state"] == "completed", job
    assert job["provenance"]["pages"] == 2
    assert (main.OUTPUT_DIR / job["book_name"] / "book.md").is_file()


def test_jobs_list_and_unknown_job(client, library):
    assert client.get("/api/books/jobs").json() == {"jobs": []}
    assert client.get("/api/books/jobs/deadbeef").status_code == 404


def test_upload_flow_still_works(client, tmp_path, monkeypatch):
    """The old path must be untouched by the new layer."""
    monkeypatch.setattr(main, "INPUT_DIR", tmp_path / "input")
    pdf = make_fixture(tmp_path / "up.pdf", pages=1)
    with pdf.open("rb") as handle:
        uploaded = client.post("/api/upload",
                               files={"file": ("up.pdf", handle, "application/pdf")}).json()
    client.post(f"/api/convert/{uploaded['book_id']}")
    for _ in range(100):
        status = client.get(f"/api/status/{uploaded['book_id']}").json()
        if status["state"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert status["state"] == "done", status
