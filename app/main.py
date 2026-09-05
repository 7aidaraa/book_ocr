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
import re as _re
import time as _time

from fastapi import Body, FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import pdf
from .acquire import run_acquisition
from .book import process_book
from .booksources.base import BookCandidate
from .booksources.cache import SearchCache
from .booksources.registry import build_registry, enabled_sources
from .booksources.resolver import parse_query, resolve
from .jobs import JobStore
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

    OCR_ENGINE selects the engine. Default is tesseract: on real Arabic books
    it keeps inter-word spaces, which PaddleOCR's formatter drops (upstream
    bug, see دليل-التشغيل.md). OCR_ENGINE=paddleocr opts back in.
    """
    global _engine
    with _engine_lock:
        if _engine is None:
            if _os.environ.get("OCR_ENGINE", "tesseract").lower() == "tesseract":
                from .engines.tesseract_engine import TesseractEngine

                _engine = TesseractEngine(lang=lang)
            else:
                from .engines.paddleocr_engine import PaddleOCREngine

                _engine = PaddleOCREngine(lang=lang)
        return _engine


@app.get("/api/languages")
def languages() -> dict:
    return {"languages": SUPPORTED_LANGS, "default": "ar"}


# ---- hub mode: Render acts as the fixed front door; a Colab GPU session
# ---- registers its temporary public URL here and heartbeats every minute.

COLAB_URL = ("https://colab.research.google.com/github/7aidaraa/book_ocr/"
             "blob/main/colab/arabic_book_ocr.ipynb")
_GPU_URL_RE = _re.compile(r"^https://[-\w]+\.(trycloudflare\.com|ngrok-free\.app)/?$")
_gpu = {"url": None, "ts": 0.0}


@app.get("/api/config")
def config() -> dict:
    return {
        "hub_mode": _os.environ.get("HUB_MODE", "0") == "1",
        "colab_url": COLAB_URL,
    }


@app.post("/api/gpu-session")
def register_gpu_session(data: dict = Body(...)) -> dict:
    if data.get("token") != _os.environ.get("HUB_TOKEN", "kitab-hub"):
        raise HTTPException(403, "رمز غير صحيح")
    url = str(data.get("url", ""))
    if not _GPU_URL_RE.match(url):
        raise HTTPException(400, "رابط غير مقبول")
    _gpu["url"], _gpu["ts"] = url.rstrip("/"), _time.time()
    return {"ok": True}


@app.get("/api/gpu-session")
def gpu_session_status() -> dict:
    online = bool(_gpu["url"]) and (_time.time() - _gpu["ts"] < 180)
    return {"online": online, "url": _gpu["url"] if online else None}


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
            "first_error": None,
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
        # surface why pages failed instead of making the user dig into files
        job["first_error"] = next(
            (p["error"] for p in metadata["pages"] if p.get("error")), None
        )
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


@app.get("/api/selftest")
def selftest() -> dict:
    """Run OCR on one generated page — a 5-second engine health check.

    Reports the real exception instead of making the user convert a whole
    book to discover the engine is broken.
    """
    import tempfile
    import traceback

    import pymupdf

    info: dict = {"engine": None, "engine_version": None, "device": None}
    try:
        import paddle  # noqa: F401

        info["device"] = "gpu" if paddle.device.is_compiled_with_cuda() and \
            paddle.device.cuda.device_count() > 0 else "cpu"
    except Exception:
        info["device"] = "cpu (no paddle)"

    tmp = Path(tempfile.mkdtemp())
    try:
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        page.insert_htmlbox(
            pymupdf.Rect(50, 50, 545, 400),
            '<div style="direction:rtl;font-size:22px">العلم نور يهتدي به الإنسان</div>',
        )
        pdf_path = tmp / "selftest.pdf"
        doc.save(pdf_path)
        doc.close()

        engine = app.state.engine_factory("ar")  # type: ignore[attr-defined]
        info["engine"] = engine.name
        info["engine_version"] = engine.version()

        from .pipeline import process_page

        result, _ = process_page(
            pdf_path, 1, engine, work_dir=tmp / "work",
            dpi=int(_os.environ.get("OCR_DPI", "300")),
            grayscale=_os.environ.get("OCR_GRAYSCALE", "0") == "1",
        )
        info["status"] = result.status
        info["error"] = result.error
        info["text"] = " ".join(b.text for b in result.ordered_blocks())[:300]
        info["ok"] = result.status == "ok" and bool(info["text"].strip())
    except Exception as exc:
        info["ok"] = False
        info["status"] = "error"
        info["error"] = f"{type(exc).__name__}: {exc}"
        info["traceback"] = traceback.format_exc()[-1500:]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return info


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


# ---------------------------------------------------------------------------
# Book discovery (optional layer). The upload flow above is untouched: both
# paths converge on the same process_book() call.
# ---------------------------------------------------------------------------

_book_jobs = JobStore()
_search_cache = SearchCache()
# Candidates a user has actually been shown, so /acquire can never be handed
# an arbitrary URL — it takes an id we issued, never a link.
_offered: dict[str, tuple[str, BookCandidate]] = {}
_offered_lock = threading.Lock()
MAX_OFFERED = 500          # bounded: this is a hand-out list, not storage


@app.get("/api/books/sources")
def book_sources() -> dict:
    """Every registered source and what has actually been verified about it."""
    return {"sources": [entry.to_dict() for entry in build_registry()]}


@app.post("/api/books/search")
def book_search(data: dict = Body(...)) -> dict:
    sources = enabled_sources()
    if not sources:
        raise HTTPException(
            503,
            "لا يوجد مصدر كتب مفعّل. المصادر الحقيقية لم يُتحقق منها بعد — "
            "استخدم رفع PDF يدويًا.",
        )
    text = str(data.get("query", "")).strip()
    if not text:
        raise HTTPException(400, "اكتب اسم الكتاب")
    if len(text) > 300:
        raise HTTPException(400, "النص طويل جدًا")

    query = parse_query(text, author=(data.get("author") or None))
    cache_key = SearchCache.key(query.title, query.author, [s.id for s in sources])
    cached = _search_cache.get(cache_key)
    if cached is not None:
        payload = cached
    else:
        payload = resolve(query, sources).to_dict()
        _search_cache.put(cache_key, payload)

    source_by_id = {s.id: s for s in sources}
    with _offered_lock:
        for item in payload["candidates"]:
            candidate = BookCandidate(**item)
            if candidate.source in source_by_id:
                _offered[candidate.id] = (candidate.source, candidate)
        while len(_offered) > MAX_OFFERED:
            _offered.pop(next(iter(_offered)))
    return payload


@app.post("/api/books/acquire")
def book_acquire(data: dict = Body(...), lang: str = "ar") -> dict:
    """Start a background job: download -> verify -> existing OCR pipeline."""
    if lang not in SUPPORTED_LANGS:
        raise HTTPException(400, f"لغة غير مدعومة: {lang}")
    candidate_id = str(data.get("candidate_id", ""))
    with _offered_lock:
        offer = _offered.get(candidate_id)
    if offer is None:
        raise HTTPException(404, "نتيجة غير معروفة — أعد البحث")

    source_id, candidate = offer
    source = next((s for s in enabled_sources() if s.id == source_id), None)
    if source is None:
        raise HTTPException(503, "المصدر لم يعد مفعّلًا")

    book_name = _safe_book_name(candidate)
    job = _book_jobs.create(
        "acquire",
        title=candidate.title,
        author=candidate.author,
        source=source_id,
        book_name=book_name,
        candidate=candidate.to_dict(),
    )

    def worker() -> None:
        engine = app.state.engine_factory(lang)
        run_acquisition(
            _book_jobs, job["id"], source, candidate, engine,
            output_root=OUTPUT_DIR, book_name=book_name,
            dpi=int(_os.environ.get("OCR_DPI", "300")),
            grayscale=_os.environ.get("OCR_GRAYSCALE", "0") == "1",
        )

    threading.Thread(target=worker, daemon=True).start()
    return job


@app.get("/api/books/jobs")
def book_jobs() -> dict:
    return {"jobs": _book_jobs.list(kinds=["acquire"])}


@app.get("/api/books/jobs/{job_id}")
def book_job(job_id: str) -> dict:
    job = _book_jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "لا توجد مهمة بهذا المعرف")
    return job


@app.post("/api/books/jobs/{job_id}/cancel")
def book_job_cancel(job_id: str) -> dict:
    try:
        return _book_jobs.request_cancel(job_id)
    except KeyError:
        raise HTTPException(404, "لا توجد مهمة بهذا المعرف")


def _safe_book_name(candidate: BookCandidate) -> str:
    """A directory name derived from the title, never from a remote filename."""
    parts = [candidate.title]
    if candidate.volume:
        parts.append(candidate.volume)
    name = _re.sub(r"[^\w\u0600-\u06FF \-]", "", " - ".join(parts)).strip()
    name = _re.sub(r"\s+", " ", name)[:80].strip(" .-")
    return name or "book"


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
