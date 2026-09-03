"""Side-by-side comparison: Tesseract (current default) vs Surya OCR.

Run on the real machine (Windows terminal), not inside a Cowork VM — Surya
needs PyTorch, which is a heavy install:

    .venv\\Scripts\\python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
    .venv\\Scripts\\python -m pip install surya-ocr
    .venv\\Scripts\\python scripts\\compare_surya.py "C:\\book.pdf" 14 50 150 300

First Surya run downloads its models (~1 GB) once. CPU-only is fine, just slow.
Output: data/work/compare-surya/<page>.md with both texts, timings, and
Surya's mean confidence — send those files back for evaluation. Nothing in
data/output is touched.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import pdf  # noqa: E402
from app.engines.tesseract_engine import TesseractEngine  # noqa: E402

OUT = ROOT / "data" / "work" / "compare-surya"


def run_surya(image_path: Path, out_dir: Path) -> tuple[str, float | None]:
    """Run the surya_ocr CLI on one image; tolerate both old and new CLIs."""
    exe = shutil.which("surya_ocr") or str(Path(sys.executable).with_name("surya_ocr"))
    attempts = [
        [exe, str(image_path), "--output_dir", str(out_dir)],                # surya >= 0.9
        [exe, str(image_path), "--langs", "ar", "--output_dir", str(out_dir)],  # older surya
    ]
    last_err = ""
    for cmd in attempts:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            break
        last_err = (proc.stderr or proc.stdout)[-800:]
    else:
        raise RuntimeError(f"surya_ocr failed:\n{last_err}")

    results = next(out_dir.rglob("results.json"), None)
    if results is None:
        raise RuntimeError("surya_ocr produced no results.json")
    data = json.loads(results.read_text(encoding="utf-8"))
    pages = next(iter(data.values()))          # {stem: [page, ...]}
    lines = pages[0].get("text_lines", [])
    text = "\n".join(l.get("text", "") for l in lines)
    confs = [l["confidence"] for l in lines if l.get("confidence") is not None]
    mean = round(sum(confs) / len(confs), 3) if confs else None
    return text, mean


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    book = Path(sys.argv[1])
    pages = [int(p) for p in sys.argv[2:]]
    OUT.mkdir(parents=True, exist_ok=True)
    tess = TesseractEngine(lang="ar")

    for n in pages:
        print(f"\n=== الصفحة {n} ===")
        img = pdf.render_page_image(book, n, OUT / f"{n:03d}.png", dpi=300)

        t0 = time.time()
        t_blocks = tess.process_image(img)
        t_time = time.time() - t0
        t_text = "\n\n".join(b.text for b in t_blocks)
        t_conf = [b.confidence for b in t_blocks if b.confidence is not None]
        t_mean = round(sum(t_conf) / len(t_conf), 3) if t_conf else None

        s_dir = OUT / f"surya-{n:03d}"
        shutil.rmtree(s_dir, ignore_errors=True)
        t0 = time.time()
        try:
            s_text, s_mean = run_surya(img, s_dir)
            s_err = None
        except Exception as exc:  # keep going; report the failure in the file
            s_text, s_mean, s_err = "", None, str(exc)
        s_time = time.time() - t0

        report = "\n".join([
            f"# مقارنة الصفحة {n}",
            "",
            f"| | Tesseract | Surya |",
            f"|---|---|---|",
            f"| الزمن | {t_time:.1f} ث | {s_time:.1f} ث |",
            f"| الثقة (تقدير المحرك) | {t_mean} | {s_mean} |",
            "",
            "## Tesseract",
            "",
            t_text or "(لا نص)",
            "",
            "## Surya",
            "",
            (s_text or "(لا نص)") if not s_err else f"✗ فشل: {s_err}",
            "",
        ])
        out_file = OUT / f"{n:03d}.md"
        out_file.write_text(report, encoding="utf-8")
        print(f"Tesseract {t_time:.1f}s conf={t_mean} | Surya {s_time:.1f}s conf={s_mean}"
              + (f" | Surya error: {s_err[:120]}" if s_err else ""))
        print(f"-> {out_file}")

    print(f"\nأرسل ملفات المقارنة من: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
