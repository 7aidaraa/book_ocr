"""The provenance record for an acquired book (§19).

It records where the file came from and what was proven about it. It never
records or implies what the book *says* — that comes only from OCR output.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .base import BookCandidate
from .verifier import VerifiedPdf


def build_record(
    candidate: BookCandidate,
    verified: VerifiedPdf,
    final_url: Optional[str] = None,
    retrieved_at: Optional[str] = None,
) -> dict:
    return {
        "title": candidate.title,
        "author": candidate.author,
        "volume": candidate.volume,
        "source": {
            "id": candidate.source,
            "book_page": candidate.book_page,
            "pdf_url": final_url or candidate.pdf_url,
            "advertised_pages": candidate.pages,
            "match_confidence": candidate.confidence,
        },
        "retrieved_at": retrieved_at or datetime.now(timezone.utc).isoformat(),
        "sha256": verified.sha256,
        "size_bytes": verified.size_bytes,
        "pages": verified.pages,           # measured from the file, not advertised
        "note": (
            "Source metadata describes the file's origin only. Book content "
            "comes exclusively from OCR of these pages."
        ),
    }
