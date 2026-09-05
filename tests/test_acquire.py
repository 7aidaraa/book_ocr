"""End-to-end: mock library -> policy -> download -> verify -> process_book.

Proves the whole idea works with no network and no real source, and that the
acquisition layer hands the existing pipeline a plain local PDF.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import jobs as jobstates
from app.acquire import AcquisitionError, acquire_pdf, run_acquisition
from app.booksources.base import BookCandidate
from app.booksources.resolver import parse_query, resolve
from app.booksources.sources.mock import MOCK_HOST, MockLibrarySource
from app.engines.base import OCREngine
from app.jobs import JobStore
from app.models import Block
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
def library(tmp_path):
    pdf = make_fixture(tmp_path / "fixture.pdf", pages=3)
    return MockLibrarySource([{
        "slug": "qatr",
        "title": "شرح قطر الندى وبل الصدى",
        "author": "ابن هشام",
        "pages": 3,
        "pdf_url": f"https://{MOCK_HOST}/files/qatr.pdf",
        "local_file": str(pdf),
        "file_type": "pdf",
    }])


def test_search_to_verified_pdf(library, tmp_path):
    resolution = resolve(parse_query("شرح قطر الندى - ابن هشام"), [library])
    assert resolution.candidates, "the mock library should answer"
    candidate = resolution.candidates[0]
    assert candidate.pdf_url.startswith("https://")

    path, record = acquire_pdf(library, candidate, tmp_path / "work")

    assert path.is_file() and path.read_bytes().startswith(b"%PDF-")
    assert record["pages"] == 3
    assert record["source"]["id"] == "mock"
    assert len(record["sha256"]) == 64


def test_full_job_reaches_process_book_and_writes_markdown(library, tmp_path):
    store = JobStore(tmp_path / "jobs")
    resolution = resolve(parse_query("شرح قطر الندى"), [library])
    candidate = resolution.candidates[0]
    job = store.create("acquire", title=candidate.title)

    result = run_acquisition(
        store, job["id"], library, candidate, MockEngine(),
        output_root=tmp_path / "out", book_name="qatr", dpi=72,
    )

    assert result["state"] == jobstates.COMPLETED
    book_md = tmp_path / "out" / "qatr" / "book.md"
    assert book_md.is_file()
    text = book_md.read_text(encoding="utf-8")
    assert "نص تجريبي" in text
    # §21: page provenance survives the new path unchanged
    assert "source_page: 1" in (tmp_path / "out" / "qatr" / "pages" / "001.md").read_text(
        encoding="utf-8")
    assert result["provenance"]["sha256"]


def test_downloaded_pdf_is_deleted_after_processing(library, tmp_path):
    store = JobStore(tmp_path / "jobs")
    candidate = resolve(parse_query("شرح قطر الندى"), [library]).candidates[0]
    job = store.create("acquire", title=candidate.title)

    run_acquisition(store, job["id"], library, candidate, MockEngine(),
                    output_root=tmp_path / "out", book_name="qatr", dpi=72)

    from app.acquire import WORK_ROOT
    assert not (WORK_ROOT / job["id"]).exists()      # §10: no retained library


def test_html_error_page_never_reaches_ocr(tmp_path):
    library = MockLibrarySource([{
        "slug": "trap", "title": "كتاب", "author": None,
        "pdf_url": f"https://{MOCK_HOST}/files/trap.pdf",
        "body": b"<html><body>403 Forbidden</body></html>",
        "content_type": "text/html",
    }])
    candidate = resolve(parse_query("كتاب"), [library]).candidates[0]
    with pytest.raises(AcquisitionError, match="PDF"):
        acquire_pdf(library, candidate, tmp_path / "work")
    assert not (tmp_path / "work" / "source.pdf").exists()


def test_job_failure_is_recorded_not_raised(tmp_path):
    library = MockLibrarySource([{
        "slug": "trap", "title": "كتاب", "author": None,
        "pdf_url": f"https://{MOCK_HOST}/files/trap.pdf",
        "body": b"<html>nope</html>",
    }])
    store = JobStore(tmp_path / "jobs")
    candidate = resolve(parse_query("كتاب"), [library]).candidates[0]
    job = store.create("acquire", title="كتاب")

    result = run_acquisition(store, job["id"], library, candidate, MockEngine(),
                             output_root=tmp_path / "out", dpi=72)

    assert result["state"] == jobstates.FAILED
    assert "PDF" in result["error"]
    assert store.get(job["id"])["state"] == jobstates.FAILED
