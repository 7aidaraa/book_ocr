"""Phase A tests.

Two tiers:
- Core tests with a mock engine: always run, no models needed.
- PaddleOCR integration test: skipped automatically when paddleocr or its
  models are unavailable (first model download needs internet once).

Run: python -m pytest tests/ -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import pdf
from app.engines.base import OCREngine
from app.markdown import render_page_markdown
from app.models import Block, PageResult
from app.pipeline import process_page
from tests.make_fixture import make_fixture


@pytest.fixture(scope="session")
def fixture_pdf(tmp_path_factory) -> Path:
    return make_fixture(tmp_path_factory.mktemp("input") / "fixture.pdf")


class MockEngine(OCREngine):
    """Deterministic engine for testing the pipeline without OCR models."""

    name = "mock"

    def process_image(self, image_path):
        assert Path(image_path).exists()
        return [
            Block(type="title", bbox=[100, 50, 500, 90], reading_order=0,
                  text="الفصل الأول: في طلب العلم"),
            Block(type="text", bbox=[50, 100, 545, 200], reading_order=1,
                  text="العلم نورٌ يهتدي به الإنسان."),
            Block(type="text", bbox=[150, 220, 450, 280], reading_order=2,
                  text="اطلبِ العلمَ ولا تكسَلْ فما\nأبعدَ الخيرَ على أهلِ الكسَلْ"),
            Block(type="footnote", bbox=[50, 700, 545, 780], reading_order=3,
                  text="1. حاشية تجريبية."),
        ]

    def version(self):
        return "0"


class FailingEngine(OCREngine):
    name = "failing"

    def process_image(self, image_path):
        raise RuntimeError("boom")

    def version(self):
        return "0"


# ---------- PDF layer ----------

def test_page_count_and_render(fixture_pdf, tmp_path):
    assert pdf.get_page_count(fixture_pdf) == 1
    img = pdf.render_page_image(fixture_pdf, 1, tmp_path / "p1.png", dpi=150)
    assert img.exists() and img.stat().st_size > 1000
    # source PDF untouched
    assert fixture_pdf.exists()


def test_render_page_out_of_range(fixture_pdf, tmp_path):
    with pytest.raises(ValueError):
        pdf.render_page_image(fixture_pdf, 99, tmp_path / "x.png")


# ---------- Markdown renderer ----------

def test_markdown_preserves_poetry_lines_and_diacritics():
    page = PageResult(page_number=214, ocr_engine="mock", blocks=[
        Block(type="text", bbox=[0, 0, 1, 1], reading_order=0,
              text="اطلبِ العلمَ ولا تكسَلْ فما  \nأبعدَ الخيرَ على أهلِ الكسَلْ"),
    ])
    md = render_page_markdown(page, "كتاب تجريبي")
    # line break of the verse survives; diacritics survive; trailing spaces stripped
    assert "اطلبِ العلمَ ولا تكسَلْ فما\nأبعدَ الخيرَ على أهلِ الكسَلْ" in md
    assert "source_page: 214" in md
    assert "verified: false" in md


def test_markdown_error_page_is_explicit():
    page = PageResult(page_number=5, status="error", error="OCR crashed",
                      ocr_engine="mock")
    md = render_page_markdown(page, "كتاب")
    assert "status: error" in md
    assert "فشلت معالجة هذه الصفحة" in md


def test_markdown_footnotes_separated():
    page = PageResult(page_number=1, ocr_engine="mock", blocks=[
        Block(type="text", bbox=[0, 0, 1, 1], reading_order=0, text="متن."),
        Block(type="footnote", bbox=[0, 2, 1, 3], reading_order=1, text="1. حاشية."),
    ])
    md = render_page_markdown(page, "كتاب")
    assert "## الحواشي" in md
    assert md.index("متن.") < md.index("## الحواشي") < md.index("1. حاشية.")


# ---------- Pipeline ----------

def test_process_page_with_mock_engine(fixture_pdf, tmp_path):
    result, md = process_page(fixture_pdf, 1, MockEngine(), work_dir=tmp_path)
    assert result.status == "ok"
    assert len(result.blocks) == 4
    assert "## الفصل الأول: في طلب العلم" in md
    # intermediates saved but not required
    assert (tmp_path / "pages" / "001" / "ocr.json").exists()
    assert (tmp_path / "pages" / "001" / "result.md").exists()


def test_process_page_failure_recorded_not_raised(fixture_pdf, tmp_path):
    result, md = process_page(fixture_pdf, 1, FailingEngine(), work_dir=tmp_path)
    assert result.status == "error"
    assert "boom" in (result.error or "")
    assert "فشلت معالجة هذه الصفحة" in md


# ---------- PaddleOCR integration (optional) ----------

@pytest.mark.slow
def test_paddleocr_engine_on_fixture(fixture_pdf, tmp_path):
    pytest.importorskip("paddleocr", reason="paddleocr not installed")
    from app.engines.paddleocr_engine import PaddleOCREngine

    engine = PaddleOCREngine(lang="ar")
    result, md = process_page(fixture_pdf, 1, engine, work_dir=tmp_path, dpi=200)
    assert result.status == "ok", result.error
    assert result.blocks, "expected at least one block from PP-StructureV3"
    text = " ".join(b.text for b in result.blocks)
    # faithful-extraction smoke check: some Arabic must come through
    assert any("؀" <= ch <= "ۿ" for ch in text)
