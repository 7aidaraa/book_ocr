"""Phases B + C tests: whole book -> pages/*.md + book.md + metadata.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.book import process_book
from app.engines.base import OCREngine
from app.models import Block
from tests.make_fixture import make_fixture


@pytest.fixture()
def book_pdf(tmp_path) -> Path:
    return make_fixture(tmp_path / "input" / "كتاب-تجريبي.pdf", pages=3)


class CountingEngine(OCREngine):
    """Mock engine that counts OCR calls (for resume tests)."""

    name = "mock"

    def __init__(self, fail_pages: set[int] | None = None):
        self.calls = 0
        self.fail_pages = fail_pages or set()
        self._current = 0

    def process_image(self, image_path):
        self.calls += 1
        # page number is encoded in the work dir path .../pages/NNN/source.png
        page = int(Path(image_path).parent.name)
        if page in self.fail_pages:
            raise RuntimeError(f"simulated failure on page {page}")
        # confidence falls with page number: 0.9, 0.8, 0.6 — page 3 is "low"
        return [Block(type="text", bbox=[0, 0, 1, 1], reading_order=0,
                      text=f"نص الصفحة {page}.", confidence=1.0 - page * 0.1 - (0.1 if page == 3 else 0))]

    def version(self):
        return "0"


def test_process_book_output_structure(book_pdf, tmp_path):
    engine = CountingEngine()
    progress: list[tuple[int, int, str]] = []

    metadata = process_book(
        book_pdf, engine,
        output_root=tmp_path / "out", work_dir=tmp_path / "work",
        on_progress=lambda p, t, m: progress.append((p, t, m)),
    )

    out = tmp_path / "out" / "كتاب-تجريبي"
    assert (out / "README.md").exists()
    assert (out / "metadata.json").exists()
    assert (out / "book.md").exists()
    for n in (1, 2, 3):
        assert (out / "pages" / f"{n:03d}.md").exists()

    assert metadata["page_count"] == 3
    assert metadata["failed_pages"] == []
    assert metadata["verification_status"] == "unverified"
    assert metadata["ocr_engine"] == "mock"

    book_md = (out / "book.md").read_text(encoding="utf-8")
    assert book_md.startswith("# كتاب-تجريبي")
    assert "## الصفحة 1" in book_md and "## الصفحة 3" in book_md
    assert "نص الصفحة 2." in book_md
    assert "---" not in book_md.split("\n\n")[0]  # no front matter leaked

    assert engine.calls == 3
    assert progress and progress[-1][2] == "اكتمل"


def test_review_report_ranks_low_confidence_pages(book_pdf, tmp_path):
    engine = CountingEngine()
    metadata = process_book(
        book_pdf, engine,
        output_root=tmp_path / "out", work_dir=tmp_path / "work",
    )
    out = tmp_path / "out" / "كتاب-تجريبي"
    report = (out / "مراجعة.md").read_text(encoding="utf-8")

    # page 3 (0.6) is below the 0.70 threshold; pages 1 (0.9) and 2 (0.8) are not
    assert metadata["quality"]["low_confidence_pages"] == [3]
    assert "| 3 | 60% |" in report
    assert "| 1 |" not in report and "| 2 |" not in report
    assert metadata["quality"]["mean_confidence"] == round((0.9 + 0.8 + 0.6) / 3, 3)

    # front matter carries the page's confidence, and resume recovers it
    page3 = (out / "pages" / "003.md").read_text(encoding="utf-8")
    assert "ocr_confidence: 0.6" in page3
    again = process_book(book_pdf, CountingEngine(),
                         output_root=tmp_path / "out", work_dir=tmp_path / "work")
    assert again["quality"]["low_confidence_pages"] == [3]


def test_process_book_failed_page_recorded_and_run_continues(book_pdf, tmp_path):
    engine = CountingEngine(fail_pages={2})
    metadata = process_book(
        book_pdf, engine,
        output_root=tmp_path / "out", work_dir=tmp_path / "work",
    )
    assert metadata["failed_pages"] == [2]

    out = tmp_path / "out" / "كتاب-تجريبي"
    page2 = (out / "pages" / "002.md").read_text(encoding="utf-8")
    assert "status: error" in page2
    assert "فشلت معالجة هذه الصفحة" in page2
    # neighbours still succeeded
    assert "status: ok" in (out / "pages" / "003.md").read_text(encoding="utf-8")


def test_process_book_resume_skips_ok_and_retries_failed(book_pdf, tmp_path):
    first = CountingEngine(fail_pages={2})
    process_book(book_pdf, first,
                 output_root=tmp_path / "out", work_dir=tmp_path / "work")
    assert first.calls == 3

    # second run: only the failed page is re-OCRed
    second = CountingEngine()
    metadata = process_book(book_pdf, second,
                            output_root=tmp_path / "out", work_dir=tmp_path / "work")
    assert second.calls == 1
    assert metadata["failed_pages"] == []
    skipped = [p["page"] for p in metadata["pages"] if p.get("skipped")]
    assert skipped == [1, 3]
