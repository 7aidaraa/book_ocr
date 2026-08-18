"""Structured page data — the pipeline's internal representation.

Markdown is only a final rendering layer; everything upstream works on
PageResult/Block so engines can be swapped and pages re-rendered without
re-running OCR.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Block:
    """One layout block on a page (paragraph, title, table, figure...)."""

    type: str                      # "text" | "title" | "table" | "figure" | "footnote" | ...
    bbox: list[float]              # [x0, y0, x1, y1] in image pixels
    reading_order: int             # 0-based position in reading sequence
    text: str                      # extracted text, line breaks preserved
    confidence: Optional[float] = None   # engine OCR confidence, NOT "accuracy"


@dataclass
class PageResult:
    """Result of processing a single PDF page."""

    page_number: int               # 1-based PDF page (source_page)
    blocks: list[Block] = field(default_factory=list)
    status: str = "ok"             # "ok" | "error"
    error: Optional[str] = None
    ocr_engine: str = ""
    printed_page: Optional[int] = None   # never guessed; None unless detected with confidence

    def to_dict(self) -> dict:
        return asdict(self)

    def ordered_blocks(self) -> list[Block]:
        return sorted(self.blocks, key=lambda b: b.reading_order)
