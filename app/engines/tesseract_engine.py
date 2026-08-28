"""Tesseract engine — the lightweight fallback (~200MB RAM).

Lower Arabic accuracy than PP-StructureV3 and no real layout analysis,
but runs on small free hosts (e.g. Render's 512MB tier). Blocks are
Tesseract's own paragraph groups in its reading order; line breaks
inside a paragraph are preserved.
"""

from __future__ import annotations

from pathlib import Path

from ..models import Block
from .base import OCREngine


class TesseractEngine(OCREngine):
    name = "tesseract"

    def __init__(self, lang: str = "ar") -> None:
        self.lang = lang
        # our API uses ISO codes; tesseract uses its own pack names
        self._tess_lang = {"ar": "ara", "en": "eng", "fa": "fas", "ur": "urd"}.get(
            lang, lang
        )

    def version(self) -> str:
        try:
            import pytesseract

            return str(pytesseract.get_tesseract_version())
        except Exception:
            return "unknown"

    def process_image(self, image_path: str | Path) -> list[Block]:
        import pytesseract
        from pytesseract import Output

        data = pytesseract.image_to_data(
            str(image_path), lang=self._tess_lang, output_type=Output.DICT
        )

        # group words -> lines -> paragraph blocks, keeping tesseract's order
        paragraphs: dict[tuple, dict] = {}
        for i in range(len(data["text"])):
            word = data["text"][i]
            if not word.strip():
                continue
            par_key = (data["block_num"][i], data["par_num"][i])
            line_key = data["line_num"][i]
            par = paragraphs.setdefault(
                par_key,
                {"lines": {}, "bbox": [1e9, 1e9, 0, 0], "confs": []},
            )
            par["lines"].setdefault(line_key, []).append(word)
            x, y = data["left"][i], data["top"][i]
            w, h = data["width"][i], data["height"][i]
            b = par["bbox"]
            par["bbox"] = [min(b[0], x), min(b[1], y), max(b[2], x + w), max(b[3], y + h)]
            conf = float(data["conf"][i])
            if conf >= 0:
                par["confs"].append(conf)

        blocks: list[Block] = []
        for order, (_, par) in enumerate(sorted(paragraphs.items())):
            text = "\n".join(
                " ".join(words) for _, words in sorted(par["lines"].items())
            )
            confs = par["confs"]
            blocks.append(
                Block(
                    type="text",
                    bbox=[float(v) for v in par["bbox"]],
                    reading_order=order,
                    text=text,
                    confidence=round(sum(confs) / len(confs) / 100, 3) if confs else None,
                )
            )
        return blocks
