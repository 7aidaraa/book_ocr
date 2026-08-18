"""Local PDF reading. The source PDF is never modified.

Pages are handled one at a time so whole books never sit in RAM.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf


def get_page_count(pdf_path: str | Path) -> int:
    with pymupdf.open(pdf_path) as doc:
        return doc.page_count


def render_page_image(
    pdf_path: str | Path,
    page_number: int,
    out_path: str | Path,
    dpi: int = 300,
) -> Path:
    """Render one page (1-based) to a PNG file and return its path.

    Opens and closes the document per call: constant memory for huge books.
    """
    pdf_path = Path(pdf_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with pymupdf.open(pdf_path) as doc:
        if not (1 <= page_number <= doc.page_count):
            raise ValueError(
                f"page {page_number} out of range 1..{doc.page_count}"
            )
        page = doc[page_number - 1]
        pix = page.get_pixmap(dpi=dpi)
        pix.save(out_path)
    return out_path
