"""FastAPI server (Phases D + E).

Local-only web UI: upload a PDF, start conversion, poll progress.
No accounts, no cloud, no telemetry. The book never leaves the machine —
the "upload" goes to data/input/ on localhost.
"""

from __future__ import annotations

import shutil
import threading
import uuid
from pathlib import Path

import json
import os as _os

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import pdf
from .book import process_book
from .reader import render_book_html

INPUT_DIR = Path("data/input")
OUTPUT_DIR = Path("data/output")
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# MVP: Arabic only; the API carries lang so more languages slot in later.
SUPPORTED_LANGS = {"ar": "العربية"}

app = FastAPI(title="Arabic Book OCR", docs_url=None, redoc_url=None)

# in-memory job registry (MVP: one local user)
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_engine = None
_engine_lock = threading.Lock()


def get_engine(lang: str):
    """Shared engine instance; models load once per process. Overridable in tests.

    OCR_ENGINE=tesseract selects the lightweight engine (for small hosts);
    default is paddleocr (PP-StructureV3).
    """
    global _engine
    with _engine_lock:
        if _engine is None:
            if _os.environ.get("OCR_ENGINE", "paddleocr").lower() == "tesseract":
                from .engines.tesseract_engine import TesseractEngine

                _engine = TesseractEngine(lang=lang)
            else:
                from .engines.paddleocr_engine import PaddleOCREngine

                _engine = PaddleOCREngine(lang=lang)
        return _engine


@app.get("/api/languages")
def languages() -> dict:
    return {"languages": SUPPORTED_LANGS, "default": "ar"}


@app.post("/api/upload")
async def upload(file: UploadFile) -> dict:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "الملف يجب أن يكون PDF")

    book_id = uuid.uuid4().hex[:12]
    dest_dir = INPUT_DIR / book_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / Path(file.filename).name

    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    try:
        page_count = pdf.get_page_count(dest)
    except Exception as exc:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise HTTPException(400, f"تعذرت قراءة PDF: {exc}")

    with _jobs_lock:
        _jobs[book_id] = {
            "book_id": book_id,
            "filename": dest.name,
            "book_name": dest.stem,
            "pdf_path": str(dest),
            "size_bytes": dest.stat().st_size,
            "page_count": page_count,
            "state": "uploaded",       # uploaded | running | done | failed
            "current_page": 0,
            "message": "",
            "ocr_engine": "paddleocr",
            "failed_pages": [],
            "output_dir": None,
            "error": None,
        }
    return _jobs[book_id]


def _run_job(book_id: str, lang: str) -> None:
    job = _jobs[book_id]

    def on_progress(page: int, total: int, message: str) -> None:
        job["current_page"] = page
        job["message"] = message

    try:
        engine = app.state.engine_factory(lang)  # type: ignore[attr-defined]
        job["ocr_engine"] = engine.name
        metadata = process_book(
            job["pdf_path"], engine,
            book_name=job["book_name"],
            output_root=OUTPUT_DIR,
            # lower DPI / grayscale keep small hosts fast and within memory
            dpi=int(_os.environ.get("OCR_DPI", "300")),
            grayscale=_os.environ.get("OCR_GRAYSCALE", "0") == "1",
            on_progress=on_progress,
        )
        job["failed_pages"] = metadata["failed_pages"]
        job["output_dir"] = str(OUTPUT_DIR / job["book_name"])
        job["state"] = "done"
        job["message"] = "اكتمل التحويل"
    except Exception as exc:
        job["state"] = "failed"
        job["error"] = f"{type(exc).__name__}: {exc}"
        job["message"] = "فشل التحويل"


app.state.engine_factory = get_engine


@app.post("/api/convert/{book_id}")
def convert(book_id: str, lang: str = "ar") -> dict:
    if lang not in SUPPORTED_LANGS:
        raise HTTPException(400, f"لغة غير مدعومة: {lang}")
    with _jobs_lock:
        job = _jobs.get(book_id)
        if job is None:
            raise HTTPException(404, "لا يوجد كتاب بهذا المعرف")
        if job["state"] == "running":
            raise HTTPException(409, "التحويل جارٍ بالفعل")
        job["state"] = "running"
        job["message"] = "بدء المعالجة..."

    threading.Thread(target=_run_job, args=(book_id, lang), daemon=True).start()
    return {"book_id": book_id, "state": "running"}


@app.get("/api/status/{book_id}")
def status(book_id: str) -> dict:
    job = _jobs.get(book_id)
    if job is None:
        raise HTTPException(404, "لا يوجد كتاب بهذا المعرف")
    return job


@app.get("/api/result/{book_id}/book.md")
def result_book_md(book_id: str) -> FileResponse:
    job = _jobs.get(book_id)
    if job is None or job["state"] != "done":
        raise HTTPException(404, "الناتج غير جاهز")
    path = Path(job["output_dir"]) / "book.md"
    return FileResponse(path, media_type="text/markdown; charset=utf-8",
                        filename="book.md")


@app.get("/api/result/{book_id}/zip")
def result_zip(book_id: str) -> FileResponse:
    """Whole output (book.md + pages/ + metadata.json) as one ZIP."""
    job = _jobs.get(book_id)
    if job is None or job["state"] != "done":
        raise HTTPException(404, "الناتج غير جاهز")
    out_dir = Path(job["output_dir"])
    zip_base = out_dir.parent / f"{out_dir.name}"
    zip_path = Path(shutil.make_archive(str(zip_base), "zip", out_dir))
    return FileResponse(zip_path, media_type="application/zip",
                        filename=f"{out_dir.name}.zip")


@app.delete("/api/book/{book_id}")
def delete_book(book_id: str) -> dict:
    """Forget a converted book: remove its upload, output, zip, and job."""
    job = _jobs.get(book_id)
    if job is None:
        raise HTTPException(404, "لا يوجد كتاب بهذا المعرف")
    if job["state"] == "running":
        raise HTTPException(409, "لا يمكن الحذف أثناء التحويل")
    shutil.rmtree(Path(job["pdf_path"]).parent, ignore_errors=True)
    if job["output_dir"]:
        out_dir = Path(job["output_dir"])
        shutil.rmtree(out_dir, ignore_errors=True)
        (out_dir.parent / f"{out_dir.name}.zip").unlink(missing_ok=True)
        shutil.rmtree(Path("data/work") / job["book_name"], ignore_errors=True)
    with _jobs_lock:
        _jobs.pop(book_id, None)
    return {"deleted": book_id}


def _safe_book_dir(book_name: str) -> Path:
    """Resolve a converted book's output dir; reject path tricks."""
    if not book_name or any(s in book_name for s in ("/", "\\", "..", "\0")):
        raise HTTPException(404, "كتاب غير موجود")
    book_dir = OUTPUT_DIR / book_name
    if not (book_dir / "book.md").exists():
        raise HTTPException(404, "كتاب غير موجود")
    return book_dir


@app.get("/api/books")
def list_books() -> dict:
    """Previously converted books (survive server restarts)."""
    books = []
    if OUTPUT_DIR.exists():
        for book_dir in sorted(OUTPUT_DIR.iterdir()):
            meta_file = book_dir / "metadata.json"
            if not (book_dir / "book.md").exists() or not meta_file.exists():
                continue
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            books.append({
                "book_name": meta.get("book_name", book_dir.name),
                "page_count": meta.get("page_count"),
                "processed_at": meta.get("processed_at"),
                "failed_pages": meta.get("failed_pages", []),
                "reader_url": f"/reader/{book_dir.name}",
            })
    return {"books": books}


@app.get("/reader/{book_name}")
def reader(book_name: str) -> HTMLResponse:
    book_dir = _safe_book_dir(book_name)
    text = (book_dir / "book.md").read_text(encoding="utf-8")
    return HTMLResponse(render_book_html(text, book_name))


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
