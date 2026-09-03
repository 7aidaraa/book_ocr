"""PageResult -> Markdown. Conservative by design.

- No AI correction, no diacritics added or removed, no line merging.
- No global whitespace collapsing (would destroy poetry/footnotes/tables).
- Only per-line trailing-whitespace strip.
"""

from __future__ import annotations

from .models import Block, PageResult


def _clean_conservative(text: str) -> str:
    # Arabic-safe: strip trailing spaces per line only; keep all line breaks,
    # diacritics, and internal spacing exactly as OCR produced them.
    return "\n".join(line.rstrip() for line in text.splitlines()).strip("\n")


def _render_block(block: Block) -> str:
    text = _clean_conservative(block.text)
    if block.type == "title":
        return f"## {text}"
    return text


def render_page_body(page: PageResult) -> str:
    """Page content without front matter (used by both NNN.md and book.md)."""
    lines = [f"# الصفحة {page.page_number}", ""]

    if page.status == "error":
        # An error page must never masquerade as an empty success.
        lines.append(f"> ⚠ فشلت معالجة هذه الصفحة: {page.error}")
        return "\n".join(lines) + "\n"

    body_parts: list[str] = []
    footnotes: list[str] = []
    for block in page.ordered_blocks():
        rendered = _render_block(block)
        if not rendered:
            continue
        if block.type == "footnote":
            footnotes.append(rendered)
        else:
            body_parts.append(rendered)

    lines.append("\n\n".join(body_parts))

    if footnotes:
        lines += ["", "***", "", "## الحواشي", ""]
        lines.append("\n\n".join(footnotes))

    return "\n".join(lines) + "\n"


def page_confidence(page: PageResult) -> float | None:
    """Mean engine confidence over the page's blocks (0–1), or None if the
    engine reports none. This is OCR self-confidence, NOT accuracy."""
    confs = [b.confidence for b in page.blocks if b.confidence is not None]
    return round(sum(confs) / len(confs), 3) if confs else None


def render_page_markdown(page: PageResult, book_name: str) -> str:
    """Render one page to Markdown with front matter tying it to its source page."""
    conf = page_confidence(page)
    front_matter = "\n".join(
        [
            "---",
            f"book: {book_name}",
            f"page: {page.page_number}",
            f"source_page: {page.page_number}",
            f"printed_page: {page.printed_page if page.printed_page is not None else 'null'}",
            f"ocr_engine: {page.ocr_engine}",
            f"ocr_confidence: {conf if conf is not None else 'null'}",
            f"status: {page.status}",
            "verified: false",
            "---",
        ]
    )
    return front_matter + "\n\n" + render_page_body(page)


def split_front_matter(markdown_text: str) -> tuple[str, str]:
    """Split a page file into (front_matter, body). Tolerates missing front matter."""
    if markdown_text.startswith("---\n"):
        end = markdown_text.find("\n---\n", 4)
        if end != -1:
            return markdown_text[: end + 5], markdown_text[end + 5 :].lstrip("\n")
    return "", markdown_text
