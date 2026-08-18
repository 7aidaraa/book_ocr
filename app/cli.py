"""Manual CLI (Phases A–C).

Usage:
    python -m app.cli path/to/book.pdf              # whole book
    python -m app.cli path/to/book.pdf --page 1     # single page (Phase A)
"""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Arabic Book OCR — local CLI")
    parser.add_argument("pdf", help="path to a local PDF (never modified)")
    parser.add_argument("--page", type=int, default=None,
                        help="1-based page number; omit to process the whole book")
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--no-resume", action="store_true",
                        help="re-OCR pages even if already successful")
    args = parser.parse_args()

    from .engines.paddleocr_engine import PaddleOCREngine

    engine = PaddleOCREngine(lang="ar")

    if args.page is not None:
        from .pipeline import process_page

        result, markdown = process_page(args.pdf, args.page, engine, dpi=args.dpi)
        print(markdown)
        if result.status == "error":
            print(f"[error] page {result.page_number}: {result.error}", file=sys.stderr)
            return 1
        print(f"[ok] page {result.page_number}: {len(result.blocks)} blocks", file=sys.stderr)
        return 0

    from .book import process_book

    def on_progress(page: int, total: int, message: str) -> None:
        print(f"[{page}/{total}] {message}", file=sys.stderr)

    metadata = process_book(
        args.pdf, engine, dpi=args.dpi,
        resume=not args.no_resume, on_progress=on_progress,
    )
    failed = metadata["failed_pages"]
    print(f"\nتم: {metadata['page_count']} صفحة، فشل منها {len(failed)}"
          + (f" {failed}" if failed else ""), file=sys.stderr)
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
