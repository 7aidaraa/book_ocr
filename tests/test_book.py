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
        return [Block(type="text", bbox=[0, 0, 1, 1], reading_order=0,
                      text=f"نص الصفحة {page}.")]

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
