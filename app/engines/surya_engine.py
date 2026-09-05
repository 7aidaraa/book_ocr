"""Surya engine — evaluation candidate, not the default.

Surya is a transformer OCR stack. Two facts decide whether it can run at all,
and both are checked at construction so a benchmark fails loudly rather than
silently producing empty pages:

1. Version. From 0.20 onward recognition runs through an external inference
   backend (llama.cpp's `llama-server`, or vLLM on a GPU) that pip does not
   install. 0.17.1 is the last release whose recognition is pure PyTorch and
   therefore works from a plain `pip install`.
2. Models. Weights are fetched at first run from models.datalab.to and cached
   on disk. That download must be reachable once.

The engine is imported lazily everywhere, so a machine without Surya keeps
working exactly as before.
"""

from __future__ import annotations

from pathlib import Path

from ..models import Block
from .base import OCREngine

# Last release whose recognition path needs no external inference server.
RECOMMENDED_VERSION = "0.17.1"


class SuryaUnavailable(RuntimeError):
    """Surya cannot run here. The message says what to install or unblock."""


class SuryaEngine(OCREngine):
    name = "surya"

    def __init__(self, lang: str = "ar") -> None:
        self.lang = lang
        self._predictors = None

    def version(self) -> str:
        try:
            import importlib.metadata as md

            return md.version("surya-ocr")
        except Exception:
            return "unknown"

    def _load(self):
        """Build the predictors once. Raises SuryaUnavailable with a reason."""
        if self._predictors is not None:
            return self._predictors
        try:
            from surya.detection import DetectionPredictor
            from surya.foundation import FoundationPredictor
            from surya.recognition import RecognitionPredictor
        except ImportError as exc:
            raise SuryaUnavailable(
                f"surya-ocr is not installed, or this version routes recognition "
                f"through an external inference server. Install the pure-PyTorch "
                f"release: pip install surya-ocr=={RECOMMENDED_VERSION} ({exc})"
            ) from exc

        try:
            foundation = FoundationPredictor()
            self._predictors = (DetectionPredictor(), RecognitionPredictor(foundation))
        except Exception as exc:
            raise SuryaUnavailable(
                f"Surya could not load its weights (first run downloads them from "
                f"models.datalab.to): {type(exc).__name__}: {exc}"
            ) from exc
        return self._predictors

    def process_image(self, image_path: str | Path) -> list[Block]:
        from PIL import Image

        detection, recognition = self._load()
        with Image.open(image_path) as handle:
            image = handle.convert("RGB")
            predictions = recognition([image], det_predictor=detection)

        blocks: list[Block] = []
        for page in predictions:
            for order, line in enumerate(getattr(page, "text_lines", [])):
                text = (getattr(line, "text", "") or "").strip()
                if not text:
                    continue
                bbox = [float(v) for v in (getattr(line, "bbox", None) or [0, 0, 0, 0])]
                confidence = getattr(line, "confidence", None)
                blocks.append(Block(
                    type="text",
                    bbox=bbox,
                    reading_order=order,
                    text=text,
                    confidence=float(confidence) if confidence is not None else None,
                ))
        return blocks


def availability() -> dict:
    """Report whether Surya can run here, without raising. Used by the
    benchmark and the self-test so the reason is always visible."""
    info: dict = {"installed": False, "version": None, "usable": False, "reason": None}
    try:
        import importlib.metadata as md

        info["version"] = md.version("surya-ocr")
        info["installed"] = True
    except Exception:
        info["reason"] = "surya-ocr is not installed"
        return info

    try:
        import surya.foundation  # noqa: F401
    except ImportError:
        info["reason"] = (
            f"surya-ocr {info['version']} routes recognition through an external "
            f"inference server (llama-server / vLLM) that pip does not install; "
            f"pin surya-ocr=={RECOMMENDED_VERSION} for a pure-PyTorch run"
        )
        return info

    info["usable"] = True
    return info
