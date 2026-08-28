"""Single-page pipeline (Phase A).

PDF -> page image -> OCR engine -> PageResult -> Markdown.
Intermediate artifacts live under data/work/<book-id>/pages/NNN/ and are
never required for the final output to remain valid.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import pdf
from .engines.base import OCREngine
from .markdown import render_page_markdown
from .models import PageResult

WORK_DIR = Path("data/work")


def process_page(
    pdf_path: str | Path,
    page_number: int,
    engine: OCREngine,
    book_name: str | None = None,
    work_dir: str | Path | None = None,
    dpi: int = 300,
    grayscale: bool = False,
) -> tuple[PageResult, str]:
    """Process one page; returns (PageResult, markdown).

    A page failure is recorded in the result, never raised past this
    function, so a whole book run can continue.
    """
    pdf_path = Path(pdf_path)
    book_name = book_name or pdf_path.stem
    base = Path(work_dir) if work_dir else WORK_DIR / book_name
    page_dir = base / "pages" / f"{page_number:03d}"

    try:
        image_path = pdf.render_page_image(
            pdf_path, page_number, page_dir / "source.png",
            dpi=dpi, grayscale=grayscale,
        )
        blocks = engine.process_image(image_path)
        result = PageResult(
            page_number=page_number,
            blocks=blocks,
            status="ok",
            ocr_engine=engine.name,
        )
    except Exception as exc:  # one bad page must not kill the book
        result = PageResult(
            page_number=page_number,
            blocks=[],
            status="error",
            error=f"{type(exc).__name__}: {exc}",
            ocr_engine=engine.name,
        )

    markdown = render_page_markdown(result, book_name)

    # Keep intermediates for inspection/benchmarking; deletable at will.
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / "ocr.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (page_dir / "result.md").write_text(markdown, encoding="utf-8")

    return result, markdown
