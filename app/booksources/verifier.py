"""Prove a downloaded file really is a usable PDF before OCR ever sees it.

A `.pdf` extension and a Content-Type header are claims by a remote server.
Neither is evidence. Only the bytes on disk are.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, asdict
from pathlib import Path

import pymupdf

from .policies import MAX_PDF_BYTES, MAX_PDF_PAGES

PDF_MAGIC = b"%PDF-"
PDF_EOF = b"%%EOF"
EOF_SEARCH_BYTES = 4096
_HTML_MARKERS = (b"<!doctype html", b"<html", b"<head", b"<script")


class VerificationError(ValueError):
    """The file is not an acceptable PDF. It must not reach the pipeline."""


@dataclass
class VerifiedPdf:
    path: str
    sha256: str
    size_bytes: int
    pages: int
    repaired: bool = False   # opened only after PyMuPDF repaired its structure

    def to_dict(self) -> dict:
        return asdict(self)


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_pdf(
    path: str | Path,
    max_bytes: int = MAX_PDF_BYTES,
    max_pages: int = MAX_PDF_PAGES,
    expected_sha256: str | None = None,
) -> VerifiedPdf:
    """Return a VerifiedPdf, or raise VerificationError explaining why not."""
    path = Path(path)
    if not path.is_file():
        raise VerificationError(f"file not found: {path}")

    size = path.stat().st_size
    if size == 0:
        raise VerificationError("file is empty")
    if size > max_bytes:
        raise VerificationError(f"file too large: {size} > {max_bytes} bytes")

    with path.open("rb") as handle:
        head = handle.read(1024)
        handle.seek(max(0, size - EOF_SEARCH_BYTES))
        tail = handle.read()

    if not head.startswith(PDF_MAGIC):
        lowered = head.lower()
        if any(marker in lowered for marker in _HTML_MARKERS):
            raise VerificationError(
                "server returned an HTML page, not a PDF "
                "(login, error, or protection page)"
            )
        raise VerificationError("missing %PDF- signature; not a PDF")

    # PyMuPDF silently repairs a truncated file and still reports a full page
    # count, so a missing end-of-file marker is the only reliable evidence
    # that the transfer was cut short.
    if PDF_EOF not in tail:
        raise VerificationError("PDF has no %%EOF marker; the file is truncated")

    # Structural check: a file can start with %PDF- and still be truncated.
    try:
        with pymupdf.open(path) as doc:
            if doc.needs_pass:
                raise VerificationError("PDF is encrypted; cannot process")
            pages = doc.page_count
            repaired = bool(getattr(doc, "is_repaired", False))
    except VerificationError:
        raise
    except Exception as exc:
        raise VerificationError(f"PDF will not open: {type(exc).__name__}: {exc}") from exc

    if pages <= 0:
        raise VerificationError("PDF has no pages")
    if pages > max_pages:
        raise VerificationError(f"too many pages: {pages} > {max_pages}")

    digest = sha256_file(path)
    if expected_sha256 and digest != expected_sha256:
        raise VerificationError("checksum mismatch; download is not intact")

    return VerifiedPdf(path=str(path), sha256=digest, size_bytes=size,
                       pages=pages, repaired=repaired)
