"""The source abstraction. One adapter per site; the rest of the system
never sees a site's HTML, URLs schemes, or quirks.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Optional


class SourceError(RuntimeError):
    """A source could not serve a request. Never fatal to a whole search."""


@dataclass
class SearchQuery:
    """A structured request. `raw` keeps what the user actually typed."""

    title: str
    author: Optional[str] = None
    raw: str = ""

    def __post_init__(self) -> None:
        self.title = self.title.strip()
        if self.author is not None:
            self.author = self.author.strip() or None
        self.raw = self.raw or self.title


@dataclass
class BookCandidate:
    """One search hit, normalised across sources.

    `confidence` is the resolver's own match score against the query, not a
    claim about the file's contents. Nothing here may be treated as book
    content: content comes only from OCR of the downloaded PDF (rule §20).
    """

    source: str                       # source id, e.g. "mock"
    title: str
    author: Optional[str] = None
    book_page: Optional[str] = None   # human-visible page on the source
    pdf_url: Optional[str] = None     # candidate file link, unverified
    pages: Optional[int] = None       # as advertised by the source
    file_type: Optional[str] = None   # as advertised; verified later
    volume: Optional[str] = None      # part/volume label, if the source says so
    size_bytes: Optional[int] = None
    confidence: float = 0.0
    id: str = ""                      # stable handle for the UI

    def to_dict(self) -> dict:
        return asdict(self)


ProgressCallback = Callable[[int, Optional[int]], None]  # (downloaded, total)


class BookSource:
    """Adapter interface. Subclasses own *all* site-specific knowledge."""

    id: str = ""
    name: str = ""
    # Hosts this source is allowed to fetch from. The downloader refuses any
    # URL — including a redirect target — outside this set.
    allowed_hosts: frozenset[str] = frozenset()
    capabilities: dict = {}   # {"search": bool, "book_page": bool, "pdf": bool}

    def search(self, query: SearchQuery, limit: int = 10) -> list[BookCandidate]:
        raise NotImplementedError

    def fetch_pdf(
        self,
        candidate: BookCandidate,
        dest: Path,
        on_progress: Optional[ProgressCallback] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> Path:
        """Fetch the candidate's file to `dest`. Returns the written path.

        Must not verify the file — verification is the caller's job, so a
        source can never declare its own output trustworthy.
        """
        raise NotImplementedError
