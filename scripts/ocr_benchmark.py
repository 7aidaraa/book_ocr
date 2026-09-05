"""Same pages, same images, several engines — measured, not impressions.

Design rules this obeys:

- One rendered PNG per page, shared by every engine. Nobody gets an easier
  image (§4).
- Accuracy is measured on RAW engine output — blocks joined in reading order,
  before any Markdown rendering or cleaning (§7). A second, separate pass
  measures the final Markdown so both questions get their own number.
- Two normalisation readings, strict and normalized, always side by side (§8).
- An engine that cannot run is recorded with its reason. It is never skipped
  silently and never guessed at.
"""

from __future__ import annotations

import json
import platform
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import pdf                                            # noqa: E402
from app.markdown import render_page_body                      # noqa: E402
from app.models import PageResult                              # noqa: E402
from app.ocr_eval import arabic_ratio, measure_both            # noqa: E402
from scripts.make_benchmark_dataset import DATASET_DIR, build  # noqa: E402

OUT_DIR = Path("data/work/ocr-benchmark")
ENGINES = ("tesseract", "surya", "paddleocr")


def peak_rss_mb() -> Optional[float]:
    """Peak resident memory of this process, or None where unavailable."""
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux reports KB, macOS bytes.
        return round(peak / (1024 if sys.platform != "darwin" else 1024 ** 2), 1)
    except ImportError:
        try:
            import psutil

            return round(psutil.Process().memory_info().rss / 1024 ** 2, 1)
        except Exception:
            return None


def environment() -> dict:
    """Everything that could explain a timing difference later."""
    import importlib.metadata as md

    def version(package: str) -> Optional[str]:
        try:
            return md.version(package)
        except Exception:
            return None

    info = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "cpu_count": None,
        "ram_gb": None,
        "gpu": None,
        "cuda": None,
        "packages": {p: version(p) for p in
                     ("pymupdf", "pytesseract", "surya-ocr", "torch",
                      "paddleocr", "paddlepaddle", "ocrmypdf", "transformers")},
        "tesseract_binary": None,
    }
    try:
        import os

        info["cpu_count"] = os.cpu_count()
    except Exception:
        pass
    try:
        import psutil

        info["ram_gb"] = round(psutil.virtual_memory().total / 1024 ** 3, 1)
    except Exception:
        pass
    if shutil.which("tesseract"):
        try:
            import pytesseract

            info["tesseract_binary"] = str(pytesseract.get_tesseract_version())
        except Exception:
            info["tesseract_binary"] = "present"
    try:
        import torch

        info["gpu"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else False
        info["cuda"] = torch.version.cuda if torch.cuda.is_available() else None
    except Exception:
        pass
    return info


def make_engine(name: str):
    """Build an engine, or return (None, reason). Never raises."""
    try:
        if name == "tesseract":
            from app.engines.tesseract_engine import TesseractEngine

            if not shutil.which("tesseract"):
                return None, "the tesseract binary is not on PATH"
            return TesseractEngine(lang="ar"), None
        if name == "surya":
            from app.engines.surya_engine import SuryaEngine, SuryaUnavailable, availability

            state = availability()
            if not state["usable"]:
                return None, state["reason"]
            engine = SuryaEngine(lang="ar")
            try:
                engine._load()                    # fail now, not mid-benchmark
            except SuryaUnavailable as exc:
                return None, str(exc)
            return engine, None
        if name == "paddleocr":
            import importlib.util

            if importlib.util.find_spec("paddleocr") is None:
                return None, "paddleocr is not installed"
            from app.engines.paddleocr_engine import PaddleOCREngine

            return PaddleOCREngine(lang="ar"), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return None, f"unknown engine: {name}"


@dataclass
class PageRun:
    page_number: int
    page_id: str
    description: str
    seconds: float
    blocks: int
    status: str
    error: Optional[str] = None
    raw_text: str = ""
    markdown: str = ""


def run_engine(name: str, engine, images: list[tuple[int, str, str, Path]]) -> list[PageRun]:
    runs: list[PageRun] = []
    for page_number, page_id, description, image_path in images:
        started = time.perf_counter()
        try:
            blocks = engine.process_image(image_path)
            status, error = "ok", None
        except Exception as exc:
            blocks, status, error = [], "error", f"{type(exc).__name__}: {exc}"
        elapsed = time.perf_counter() - started

        ordered = sorted(blocks, key=lambda b: b.reading_order)
        raw = "\n".join(b.text for b in ordered)   # RAW: no cleaning, no headers
        page_result = PageResult(page_number=page_number, blocks=blocks,
                                 status=status, error=error, ocr_engine=name)
        runs.append(PageRun(
            page_number=page_number, page_id=page_id, description=description,
            seconds=round(elapsed, 3), blocks=len(blocks), status=status,
            error=error, raw_text=raw,
            markdown=render_page_body(page_result),
        ))
    return runs


def score(runs: list[PageRun], truths: dict[str, str]) -> dict:
    pages = []
    for run in runs:
        truth = truths[run.page_id]
        pages.append({
            "page_number": run.page_number,
            "page_id": run.page_id,
            "description": run.description,
            "status": run.status,
            "error": run.error,
            "seconds": run.seconds,
            "blocks": run.blocks,
            "output_chars": len(run.raw_text),
            "arabic_character_ratio": arabic_ratio(run.raw_text),
            "raw": measure_both(truth, run.raw_text),
            "markdown": measure_both(truth, run.markdown),
        })

    ok = [p for p in pages if p["status"] == "ok"]
    total_seconds = sum(p["seconds"] for p in pages)

    def mean(key: str, reading: str, metric: str) -> Optional[float]:
        values = [p[key][reading][metric] for p in ok]
        return round(sum(values) / len(values), 4) if values else None

    return {
        "page_count": len(pages),
        "successful_pages": len(ok),
        "failed_pages": [p["page_number"] for p in pages if p["status"] != "ok"],
        "seconds_total": round(total_seconds, 2),
        "seconds_per_page": round(total_seconds / len(pages), 2) if pages else None,
        "output_size_chars": sum(p["output_chars"] for p in pages),
        "arabic_character_ratio": (
            round(sum(p["arabic_character_ratio"] for p in ok) / len(ok), 4) if ok else None
        ),
        "cer_strict": mean("raw", "strict", "cer"),
        "wer_strict": mean("raw", "strict", "wer"),
        "cer_normalized": mean("raw", "normalized", "cer"),
        "wer_normalized": mean("raw", "normalized", "wer"),
        "cer_markdown_normalized": mean("markdown", "normalized", "cer"),
        "pages": pages,
    }


def run(engines: tuple[str, ...] = ENGINES, dpi: int = 200,
        out_dir: str | Path = OUT_DIR, dataset_dir: str | Path = DATASET_DIR,
        pdf_path: Optional[str | Path] = None) -> dict:
    """Run the benchmark and write benchmark.json + report.md. Returns the result."""
    out_dir, dataset_dir = Path(out_dir), Path(dataset_dir)
    manifest_path = dataset_dir / "manifest.json"
    if not manifest_path.exists():
        build(dataset_dir, dpi=dpi)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    source_pdf = Path(pdf_path) if pdf_path else Path(manifest["pdf"])
    truths = {
        page["id"]: (dataset_dir / page["ground_truth"]).read_text(encoding="utf-8").strip()
        for page in manifest["pages"]
    }

    # Render every page once; all engines read the very same PNG.
    images_dir = out_dir / "images"
    images: list[tuple[int, str, str, Path]] = []
    for page in manifest["pages"]:
        image = pdf.render_page_image(
            source_pdf, page["page_number"],
            images_dir / f"{page['id']}.png", dpi=dpi,
        )
        images.append((page["page_number"], page["id"], page["description"], image))

    results: dict = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "environment": environment(),
        "dataset": {
            "pdf": str(source_pdf),
            "dpi": dpi,
            "page_count": len(images),
            "pages": [{"page_number": n, "id": i, "description": d} for n, i, d, _ in images],
            "ground_truth": "exact source text the pages were rendered from",
        },
        "engines": {},
    }

    for name in engines:
        engine, reason = make_engine(name)
        if engine is None:
            results["engines"][name] = {"available": False, "reason": reason}
            print(f"[skip] {name}: {reason}", file=sys.stderr)
            continue
        print(f"[run ] {name} ...", file=sys.stderr)
        runs = run_engine(name, engine, images)
        summary = score(runs, truths)
        summary.update({
            "available": True,
            "version": engine.version(),
            "peak_rss_mb_after_run": peak_rss_mb(),
        })
        results["engines"][name] = summary

        texts = out_dir / "raw" / name
        texts.mkdir(parents=True, exist_ok=True)
        for item in runs:
            (texts / f"{item.page_id}.txt").write_text(item.raw_text, encoding="utf-8")

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "benchmark.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(render_report(results, truths), encoding="utf-8")
    return results


def _fmt(value, suffix: str = "") -> str:
    return "—" if value is None else f"{value}{suffix}"


def render_report(results: dict, truths: dict[str, str]) -> str:
    env = results["environment"]
    live = {n: e for n, e in results["engines"].items() if e.get("available")}
    dead = {n: e for n, e in results["engines"].items() if not e.get("available")}

    lines = [
        "# مقارنة محركات OCR العربية",
        "",
        f"وقت التوليد: {results['generated_at']}",
        "",
        "## البيئة (Environment)",
        "",
        "| البند | القيمة |",
        "|---|---|",
        f"| Python | {env['python']} |",
        f"| النظام | {env['platform']} |",
        f"| المعالج | {env['processor']} · {_fmt(env['cpu_count'])} نواة |",
        f"| الذاكرة | {_fmt(env['ram_gb'], ' GB')} |",
        f"| GPU | {env['gpu'] if env['gpu'] else 'لا يوجد'} |",
        f"| CUDA | {_fmt(env['cuda'])} |",
        f"| Tesseract | {_fmt(env['tesseract_binary'])} |",
        "",
        "الحزم: " + "، ".join(
            f"`{k}={v}`" for k, v in env["packages"].items() if v) or "—",
        "",
        "## مجموعة الاختبار (Dataset)",
        "",
        f"ملف واحد، {results['dataset']['page_count']} صفحة، "
        f"{results['dataset']['dpi']} نقطة/بوصة — **نفس الصورة لكل محرك**.",
        "",
        "| # | النوع | الوصف |",
        "|---|---|---|",
    ]
    for page in results["dataset"]["pages"]:
        lines.append(f"| {page['page_number']} | `{page['id']}` | {page['description']} |")

    lines += ["", "## النتائج", ""]
    if not live:
        lines.append("**لم يعمل أي محرك.** الأسباب أدناه.")
    else:
        lines += [
            "| المحرك | الإصدار | ث/صفحة | CER صارم | WER صارم | "
            "CER مطبَّع | WER مطبَّع | نجحت | فشلت |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for name, data in live.items():
            lines.append(
                f"| {name} | {data['version']} | {_fmt(data['seconds_per_page'])} | "
                f"{_fmt(data['cer_strict'])} | {_fmt(data['wer_strict'])} | "
                f"{_fmt(data['cer_normalized'])} | {_fmt(data['wer_normalized'])} | "
                f"{data['successful_pages']}/{data['page_count']} | "
                f"{len(data['failed_pages'])} |"
            )
        lines += [
            "",
            "«صارم» = بلا تطبيع (كل همزة وكل حركة تُحسب خطأً). "
            "«مطبَّع» = بعد فولدة أإآ→ا، ى→ي، ة→ه، وحذف التشكيل والتطويل، "
            "وتوحيد الأرقام وعلامات الترقيم.",
            "",
            "### لكل صفحة (CER مطبَّع، على النص الخام)",
            "",
        ]
        header = "| # | النوع | " + " | ".join(live) + " |"
        lines += [header, "|" + "---|" * (len(live) + 2)]
        first = next(iter(live.values()))
        for index, page in enumerate(first["pages"]):
            cells = []
            for data in live.values():
                item = data["pages"][index]
                cells.append("فشل" if item["status"] != "ok"
                             else str(item["raw"]["normalized"]["cer"]))
            lines.append(f"| {page['page_number']} | `{page['page_id']}` | "
                         + " | ".join(cells) + " |")

        lines += ["", "### السرعة والموارد", "",
                  "| المحرك | ثوانٍ كليًا | ث/صفحة | ذروة الذاكرة | حجم الناتج |",
                  "|---|---|---|---|---|"]
        for name, data in live.items():
            lines.append(
                f"| {name} | {_fmt(data['seconds_total'])} | "
                f"{_fmt(data['seconds_per_page'])} | "
                f"{_fmt(data.get('peak_rss_mb_after_run'), ' MB')} | "
                f"{data['output_size_chars']} حرفًا |")

    if dead:
        lines += ["", "## محركات لم تعمل (Failures)", "",
                  "| المحرك | السبب |", "|---|---|"]
        for name, data in dead.items():
            lines.append(f"| {name} | {data['reason']} |")

    lines += [
        "",
        "## حدود هذا القياس",
        "",
        "- الصفحات مُولَّدة، والنص المرجعي هو مصدر التوليد نفسه — فالمرجع دقيق"
        " تمامًا، لكن الصفحة أنظف من مسح ضوئي حقيقي. **هذه الأرقام حدٌّ أدنى"
        " للخطأ، لا تنبؤ بكتاب ممسوح.**",
        "- الصفحة الثامنة وحدها مشوَّهة عمدًا (ميل، ضبابية، ضجيج، ضغط) لتقريب"
        " الصورة من واقع المسح.",
        "- الحكم النهائي يحتاج تشغيل المقارنة نفسها على كتاب حقيقي.",
        "",
        "## الخلاصة",
        "",
        "_يملؤها من يقرأ الأرقام أعلاه._",
        "",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    run()
