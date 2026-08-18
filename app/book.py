"""Whole-book processing (Phases B + C).

Sequential, page by page, constant memory. A failed page is recorded and
the run continues. Already-successful pages are skipped on re-runs, so a
book can be resumed without re-OCRing what worked.

Output layout (data/output/<book-name>/):
    README.md
    metadata.json
    book.md
    pages/001.md, 002.md, ...
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from . import pdf
from .engines.base import OCREngine
from .markdown import split_front_matter
from .pipeline import process_page

OUTPUT_DIR = Path("data/output")

ProgressCallback = Callable[[int, int, str], None]  # (page, total, message)


def _page_already_ok(page_file: Path) -> bool:
    if not page_file.exists():
        return False
    front_matter, _ = split_front_matter(page_file.read_text(encoding="utf-8"))
    return "status: ok" in front_matter


def process_book(
    pdf_path: str | Path,
    engine: OCREngine,
    book_name: Optional[str] = None,
    output_root: str | Path = OUTPUT_DIR,
    work_dir: str | Path | None = None,
    dpi: int = 300,
    resume: bool = True,
    on_progress: Optional[ProgressCallback] = None,
) -> dict:
    """Process a full PDF into the §11 output structure; returns a summary dict."""
    pdf_path = Path(pdf_path)
    book_name = book_name or pdf_path.stem
    total = pdf.get_page_count(pdf_path)

    out_dir = Path(output_root) / book_name
    pages_dir = out_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    def report(page: int, message: str) -> None:
        if on_progress:
            on_progress(page, total, message)

    pages_summary: list[dict] = []
    for page_number in range(1, total + 1):
        page_file = pages_dir / f"{page_number:03d}.md"

        if resume and _page_already_ok(page_file):
            report(page_number, f"تخطي الصفحة {page_number} (منجزة سابقًا)")
            pages_summary.append({"page": page_number, "status": "ok", "skipped": True})
            continue

        report(page_number, f"OCR الصفحة {page_number}...")
        result, markdown = process_page(
            pdf_path, page_number, engine,
            book_name=book_name, work_dir=work_dir, dpi=dpi,
        )
        page_file.write_text(markdown, encoding="utf-8")

        entry: dict = {"page": page_number, "status": result.status}
        if result.status == "error":
            entry["error"] = result.error
        pages_summary.append(entry)

    report(total, "إنشاء book.md...")
    _write_book_md(out_dir, book_name, total)

    failed = [p for p in pages_summary if p["status"] == "error"]
    metadata = {
        "book_name": book_name,
        "author": None,
        "original_filename": pdf_path.name,
        "page_count": total,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "ocr_engine": engine.name,
        "ocr_engine_version": engine.version(),
        "processing_settings": {"dpi": dpi, "lang": getattr(engine, "lang", None)},
        "verification_status": "unverified",
        "pages": pages_summary,
        "failed_pages": [p["page"] for p in failed],
    }
    (out_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    (out_dir / "README.md").write_text(
        f"# {book_name}\n\n"
        f"ناتج تحويل OCR محلي (محرك: {engine.name}).\n\n"
        f"- `book.md` — الكتاب كاملًا بترتيب الصفحات.\n"
        f"- `pages/` — ملف لكل صفحة PDF أصلية (المصدر الأول للحقيقة).\n"
        f"- `metadata.json` — تفاصيل المعالجة وحالة كل صفحة.\n"
        f"- النص مستخرج آليًا وغير مُراجَع (verified: false).\n",
        encoding="utf-8",
    )

    report(total, "اكتمل")
    return metadata


def _write_book_md(out_dir: Path, book_name: str, total: int) -> None:
    """Concatenate page bodies in order. pages/*.md stay the source of truth."""
    parts = [f"# {book_name}\n"]
    for page_number in range(1, total + 1):
        page_file = out_dir / "pages" / f"{page_number:03d}.md"
        if not page_file.exists():
            continue
        _, body = split_front_matter(page_file.read_text(encoding="utf-8"))
        # page heading inside body is already "# الصفحة N" — demote to "##"
        body = "\n".join(
            f"#{line}" if line.startswith("# ") else line
            for line in body.splitlines()
        )
        parts.append(body.rstrip("\n") + "\n")
    (out_dir / "book.md").write_text("\n".join(parts), encoding="utf-8")
