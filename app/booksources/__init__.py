"""Book discovery and acquisition layer.

Sits *above* the OCR pipeline and never inside it. Its only output is a
verified local PDF path, which the caller hands to app.book.process_book()
exactly as if the user had uploaded the file by hand.

Nothing here knows how OCR works, and app/pdf.py, app/pipeline.py and
app/book.py know nothing about this package.
"""

from .base import BookCandidate, BookSource, SearchQuery, SourceError
from .policies import PolicyError, check_url
from .verifier import VerificationError, VerifiedPdf, verify_pdf

__all__ = [
    "BookCandidate",
    "BookSource",
    "SearchQuery",
    "SourceError",
    "PolicyError",
    "check_url",
    "VerificationError",
    "VerifiedPdf",
    "verify_pdf",
]
