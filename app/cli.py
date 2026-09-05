"""Manual CLI.

Usage:
    python -m app.cli path/to/book.pdf              # whole book
    python -m app.cli path/to/book.pdf --page 1     # single page
    python -m app.cli sources                       # book sources + status
    python -m app.cli search "شرح قطر الندى"        # search enabled sources
    python -m app.cli probe                         # re-check source reachability

The PDF form is unchanged; the sub-commands are additive so no existing
invocation breaks.
"""

from __future__ import annotations

import argparse
import sys


SUBCOMMANDS = ("sources", "search", "probe")


def _cmd_sources() -> int:
    from .booksources.registry import build_registry

    for entry in build_registry():
        status = entry.status
        flags = "".join(
            letter if getattr(status, field) else "-"
            for letter, field in zip("drstc", ("discovered", "reachable", "searchable",
                                               "downloadable", "terms_checked"))
        )
        state = "ENABLED" if entry.runnable() else "disabled"
        print(f"{entry.id:10} [{flags}] {state:8} {entry.name}")
        if status.reason:
            print(f"{'':10}  ↳ {status.reason}")
    return 0


def _cmd_search(text: str, author: str | None) -> int:
    from .booksources.registry import enabled_sources
    from .booksources.resolver import parse_query, resolve

    sources = enabled_sources()
    if not sources:
        print("لا يوجد مصدر مفعّل. استخدم رفع PDF يدويًا.", file=sys.stderr)
        return 1

    result = resolve(parse_query(text, author), sources)
    for index, candidate in enumerate(result.candidates, 1):
        meta = " · ".join(filter(None, [
            candidate.author, candidate.volume,
            f"{candidate.pages} صفحة" if candidate.pages else None,
            f"تطابق {candidate.confidence:.0%}",
        ]))
        print(f"{index}. {candidate.title}\n   {meta}\n   {candidate.id}")
    for source_id, reason in result.errors.items():
        print(f"[!] {source_id}: {reason}", file=sys.stderr)
    if result.note:
        print(f"\n{result.note}", file=sys.stderr)
    return 0 if result.candidates else 2


def _cmd_probe() -> int:
    """Re-check sources against reality. Never guesses: a source that cannot
    be reached is reported as such and stays disabled."""
    from .booksources.registry import build_registry

    exit_code = 0
    for entry in build_registry():
        if entry.factory is None:
            print(f"{entry.id:10} UNVERIFIED — {entry.status.reason}")
            exit_code = max(exit_code, 2)
            continue
        try:
            source = entry.factory()   # type: ignore[operator]
            count = len(getattr(source, "catalogue", []))
            print(f"{entry.id:10} reachable — {count} عنصر في الفهرس")
        except Exception as exc:
            print(f"{entry.id:10} FAILED — {type(exc).__name__}: {exc}")
            exit_code = max(exit_code, 1)
    return exit_code


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in SUBCOMMANDS:
        command = sys.argv[1]
        if command == "sources":
            return _cmd_sources()
        if command == "probe":
            return _cmd_probe()
        sub = argparse.ArgumentParser(prog="app.cli search")
        sub.add_argument("query")
        sub.add_argument("--author", default=None)
        parsed = sub.parse_args(sys.argv[2:])
        return _cmd_search(parsed.query, parsed.author)

    parser = argparse.ArgumentParser(description="Arabic Book OCR — local CLI")
    parser.add_argument("pdf", help="path to a local PDF (never modified)")
    parser.add_argument("--page", type=int, default=None,
                        help="1-based page number; omit to process the whole book")
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--no-resume", action="store_true",
                        help="re-OCR pages even if already successful")
    # Tesseract is the default after real-book testing: PaddleOCR's Arabic
    # output drops inter-word spaces (upstream formatter bug), Tesseract keeps them.
    parser.add_argument("--engine", choices=["paddleocr", "tesseract"],
                        default="tesseract")
    args = parser.parse_args()

    if args.engine == "tesseract":
        from .engines.tesseract_engine import TesseractEngine

        engine = TesseractEngine(lang="ar")
    else:
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
