"""The bridge: candidate -> verified local PDF -> the existing OCR pipeline.

This is the only place where the book-source layer touches the pipeline, and
it touches it at exactly one call: process_book(). Nothing upstream of that
call knows about OCR; nothing downstream knows about book sources.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable, Optional

from .book import process_book
from .booksources.base import BookCandidate, SourceError
from .booksources.metadata import build_record
from .booksources.policies import PolicyError
from .booksources.verifier import VerificationError, verify_pdf
from .engines.base import OCREngine
from . import jobs as jobstates

WORK_ROOT = Path("data/work/acquired")


class AcquisitionError(RuntimeError):
    """Acquisition failed before OCR. Carries a user-facing Arabic reason."""


def acquire_pdf(
    source,
    candidate: BookCandidate,
    work_dir: str | Path,
    on_progress: Optional[Callable[[int, Optional[int]], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> tuple[Path, dict]:
    """Download and verify. Returns (pdf_path, provenance record).

    A file that fails verification is deleted, never handed to OCR.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    dest = work_dir / "source.pdf"

    try:
        path = source.fetch_pdf(candidate, dest, on_progress=on_progress,
                                should_cancel=should_cancel)
    except PolicyError as exc:
        raise AcquisitionError(f"رابط مرفوض بسياسة الأمان: {exc}") from exc
    except SourceError as exc:
        raise AcquisitionError(f"تعذّر التنزيل من المصدر: {exc}") from exc

    try:
        verified = verify_pdf(path)
    except VerificationError as exc:
        Path(path).unlink(missing_ok=True)
        raise AcquisitionError(f"الملف ليس PDF صالحًا: {exc}") from exc

    return Path(path), build_record(candidate, verified)


def run_acquisition(
    store: "jobstates.JobStore",
    job_id: str,
    source,
    candidate: BookCandidate,
    engine: OCREngine,
    output_root: str | Path,
    book_name: Optional[str] = None,
    dpi: int = 300,
    grayscale: bool = False,
    keep_pdf: bool = False,
) -> dict:
    """Full acquisition job: download -> verify -> process_book -> cleanup."""
    book_name = book_name or candidate.title
    work_dir = WORK_ROOT / job_id

    def cancelled() -> bool:
        return store.cancel_requested(job_id)

    try:
        store.update(job_id, state=jobstates.DOWNLOADING, message="تنزيل الملف...")

        def on_bytes(done: int, total: Optional[int]) -> None:
            store.set_progress(job_id, jobstates.DOWNLOADING, done, total)

        pdf_path, record = acquire_pdf(
            source, candidate, work_dir,
            on_progress=on_bytes, should_cancel=cancelled,
        )
        store.update(job_id, provenance=record,
                     message="تم التحقق من الملف", pages=record["pages"])

        if cancelled():
            return store.mark_cancelled(job_id)

        store.update(job_id, state=jobstates.PROCESSING, message="بدء المعالجة...")

        def on_page(page: int, total: int, message: str) -> None:
            store.set_progress(job_id, jobstates.PROCESSING, page, total, message)

        metadata = process_book(
            pdf_path, engine,
            book_name=book_name,
            output_root=output_root,
            dpi=dpi,
            grayscale=grayscale,
            on_progress=on_page,
        )
        output_dir = str(Path(output_root) / book_name)
        job = store.update(
            job_id,
            state=jobstates.COMPLETED,
            message="اكتمل التحويل",
            output_dir=output_dir,
            failed_pages=metadata["failed_pages"],
            ocr_engine=engine.name,
        )
        return job
    except Exception as exc:
        return store.update(
            job_id, state=jobstates.FAILED,
            message="فشلت المهمة",
            error=str(exc) if isinstance(exc, AcquisitionError)
            else f"{type(exc).__name__}: {exc}",
        )
    finally:
        # §10: the acquired file is a means, not a stored library.
        if not keep_pdf:
            shutil.rmtree(work_dir, ignore_errors=True)
