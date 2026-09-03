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
from .markdown import page_confidence, split_front_matter
from .pipeline import process_page

OUTPUT_DIR = Path("data/output")

# Pages whose mean OCR confidence falls below this are flagged for review.
# Tesseract's ara model sits around 0.80–0.92 on clean body text.
LOW_CONFIDENCE = 0.70

ProgressCallback = Callable[[int, int, str], None]  # (page, total, message)


def _page_already_ok(page_file: Path) -> bool:
    if not page_file.exists():
        return False
    front_matter, _ = split_front_matter(page_file.read_text(encoding="utf-8"))
    return "status: ok" in front_matter


def _page_confidence_from_file(page_file: Path) -> Optional[float]:
    """Recover ocr_confidence from an existing page's front matter (resume)."""
    front_matter, _ = split_front_matter(page_file.read_text(encoding="utf-8"))
    for line in front_matter.splitlines():
        if line.startswith("ocr_confidence:"):
            value = line.split(":", 1)[1].strip()
            return None if value == "null" else float(value)
    return None


def process_book(
    pdf_path: str | Path,
    engine: OCREngine,
    book_name: Optional[str] = None,
    output_root: str | Path = OUTPUT_DIR,
    work_dir: str | Path | None = None,
    dpi: int = 300,
    grayscale: bool = False,
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
            pages_summary.append({
                "page": page_number, "status": "ok", "skipped": True,
                "confidence": _page_confidence_from_file(page_file),
            })
            continue

        report(page_number, f"OCR الصفحة {page_number}...")
        result, markdown = process_page(
            pdf_path, page_number, engine,
            book_name=book_name, work_dir=work_dir,
            dpi=dpi, grayscale=grayscale,
        )
        page_file.write_text(markdown, encoding="utf-8")

        entry: dict = {
            "page": page_number,
            "status": result.status,
            "confidence": page_confidence(result),
        }
        if result.status == "error":
            entry["error"] = result.error
        pages_summary.append(entry)

    report(total, "إنشاء book.md...")
    _write_book_md(out_dir, book_name, total)

    report(total, "إنشاء تقرير المراجعة...")
    quality = _write_review_report(out_dir, book_name, pages_summary)

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
        "quality": quality,
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
        f"- `مراجعة.md` — الصفحات الأقل ثقةً، مرتبة؛ ابدأ المراجعة منها.\n"
        f"- النص مستخرج آليًا وغير مُراجَع (verified: false).\n",
        encoding="utf-8",
    )

    report(total, "اكتمل")
    return metadata


def _write_review_report(out_dir: Path, book_name: str, pages: list[dict]) -> dict:
    """Automatic QA in place of reading every page: rank pages by the engine's
    own confidence so a human (or a later pass) looks only where it matters.

    Confidence is the engine's self-estimate, not measured accuracy — but
    on the books tested it tracks scan quality well (decorative title pages,
    dense footnotes and symbols score lowest).
    """
    scored = [p for p in pages if p.get("confidence") is not None]
    failed = [p["page"] for p in pages if p["status"] == "error"]
    low = sorted(
        (p for p in scored if p["confidence"] < LOW_CONFIDENCE),
        key=lambda p: p["confidence"],
    )
    mean = round(sum(p["confidence"] for p in scored) / len(scored), 3) if scored else None

    lines = [f"# تقرير مراجعة — {book_name}", ""]
    if mean is None:
        lines.append("محرك OCR المستخدم لا يقدّم درجات ثقة؛ لا يمكن ترتيب الصفحات آليًا.")
    else:
        lines += [
            f"- متوسط ثقة OCR: **{mean:.0%}** على {len(scored)} صفحة",
            f"- صفحات تحت حد الثقة ({LOW_CONFIDENCE:.0%}): **{len(low)}**",
            f"- صفحات فشلت كليًا: **{len(failed)}**" + (f" — {failed}" if failed else ""),
            "",
            "> الثقة هنا تقدير المحرك لنفسه، لا دقة مقيسة. لكنها تؤشر بدقة على",
            "> الصفحات المزخرفة والحواشي الكثيفة والرموز — ابدأ المراجعة من الأعلى.",
            "",
        ]
        if low:
            lines += ["| الصفحة | الثقة | الملف |", "|---|---|---|"]
            for p in low:
                n = p["page"]
                lines.append(f"| {n} | {p['confidence']:.0%} | [pages/{n:03d}.md](pages/{n:03d}.md) |")
        else:
            lines.append("كل الصفحات فوق حد الثقة ✓")
    if failed:
        lines += ["", "## صفحات فشلت (لا نص فيها)", ""]
        lines += [f"- [pages/{n:03d}.md](pages/{n:03d}.md)" for n in failed]

    (out_dir / "مراجعة.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "mean_confidence": mean,
        "low_confidence_threshold": LOW_CONFIDENCE,
        "low_confidence_pages": [p["page"] for p in low],
    }


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
