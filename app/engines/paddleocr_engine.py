"""PaddleOCR / PP-StructureV3 engine.

Heavy imports are lazy: importing this module is cheap; the pipeline is
loaded on first use. Models are downloaded once by PaddleOCR into its
local cache; after that, OCR runs fully offline.
"""

from __future__ import annotations

from pathlib import Path

from ..models import Block
from .base import OCREngine

# PP-StructureV3 block labels -> our block types (conservative mapping).
_LABEL_MAP = {
    "text": "text",
    "paragraph_title": "title",
    "doc_title": "title",
    "table": "table",
    "figure": "figure",
    "image": "figure",
    "footnote": "footnote",
    "figure_title": "text",
    "chart_title": "text",
    "abstract": "text",
    "content": "text",
    "formula": "text",
}


class PaddleOCREngine(OCREngine):
    name = "paddleocr"

    def __init__(self, lang: str = "ar") -> None:
        self.lang = lang
        self._pipeline = None

    def _load(self):
        if self._pipeline is None:
            from paddleocr import PPStructureV3

            # PP-StructureV3 handles layout detection + reading order;
            # recognition model follows the requested language.
            self._pipeline = PPStructureV3(
                lang=self.lang,
                use_doc_orientation_classify=True,
                use_doc_unwarping=False,       # conservative: no aggressive rectification
                use_table_recognition=True,
                use_formula_recognition=False,  # not needed for MVP, saves a model
            )
        return self._pipeline

    def version(self) -> str:
        try:
            from importlib.metadata import version

            return version("paddleocr")
        except Exception:
            return "unknown"

    def process_image(self, image_path: str | Path) -> list[Block]:
        pipeline = self._load()
        results = pipeline.predict(str(image_path))

        blocks: list[Block] = []
        order = 0
        for res in results:
            parsing_list = getattr(res, "json", {}).get("res", {}).get(
                "parsing_res_list", []
            )
            for item in parsing_list:
                label = str(item.get("block_label", "text"))
                text = str(item.get("block_content", "") or "")
                if not text.strip():
                    continue
                bbox = [float(v) for v in (item.get("block_bbox") or [0, 0, 0, 0])]
                blocks.append(
                    Block(
                        type=_LABEL_MAP.get(label, "text"),
                        bbox=bbox,
                        # trust PP-StructureV3's parsing order; our own RTL
                        # ordering layer can refine this later without
                        # touching the engine
                        reading_order=order,
                        text=text,
                        confidence=None,
                    )
                )
                order += 1
        return blocks
