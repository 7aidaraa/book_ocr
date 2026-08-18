"""Phase-A manual test entry point.

Usage:
    python -m app.cli path/to/book.pdf --page 1
"""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Arabic Book OCR — single page (Phase A)")
    parser.add_argument("pdf", help="path to a local PDF (never modified)")
    parser.add_argument("--page", type=int, default=1, help="1-based PDF page number")
    parser.add_argument("--dpi", type=int, default=300)
    args = parser.parse_args()

    from .engines.paddleocr_engine import PaddleOCREngine
    from .pipeline import process_page

    engine = PaddleOCREngine(lang="ar")
    result, markdown = process_page(args.pdf, args.page, engine, dpi=args.dpi)

    print(markdown)
    if result.status == "error":
        print(f"[error] page {result.page_number}: {result.error}", file=sys.stderr)
        return 1
    print(
        f"[ok] page {result.page_number}: {len(result.blocks)} blocks "
        f"(engine={result.ocr_engine} v{engine.version()})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
