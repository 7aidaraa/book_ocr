"""OCR engine interface. The rest of the pipeline depends only on this,
never on PaddleOCR/Tesseract directly, so engines are swappable."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import Block


class OCREngine(ABC):
    """Contract: take a page image, return layout-ordered blocks."""

    name: str = "base"

    @abstractmethod
    def process_image(self, image_path: str | Path) -> list[Block]:
        """Run layout analysis + OCR on one page image."""

    @abstractmethod
    def version(self) -> str:
        """Engine/library version string for metadata.json."""
