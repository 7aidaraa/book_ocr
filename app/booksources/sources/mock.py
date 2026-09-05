"""A local library that behaves like a real remote source.

It exists to prove the whole chain — search, book page, file link, policy,
download, verify, OCR — without a network and without guessing any real
site's structure. It serves real PDF bytes over the *same* downloader and
the *same* policy gate a network source would use; only the transport is
substituted, so nothing on the acquisition path is skipped in tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterator, Optional

from ..base import BookCandidate, BookSource, SearchQuery, SourceError
from ..downloader import DownloadError, download
from ..policies import CONNECT_TIMEOUT
from ..resolver import similarity

MOCK_HOST = "mock-library.invalid"     # RFC 2606: can never resolve for real
_MOCK_IP = ["93.184.216.34"]           # a public address; the host never resolves


class _MockResponse:
    def __init__(self, status: int, headers: dict, body: bytes) -> None:
        self.status = status
        self.headers = {k.lower(): v for k, v in headers.items()}
        self._body = body

    def chunks(self, size: int) -> Iterator[bytes]:
        for offset in range(0, len(self._body), size):
            yield self._body[offset : offset + size]

    def close(self) -> None:
        return None


class MockLibrarySource(BookSource):
    id = "mock"
    name = "مكتبة تجريبية محلية"
    allowed_hosts = frozenset({MOCK_HOST})
    capabilities = {"search": True, "book_page": True, "pdf": True}

    def __init__(self, catalogue: Optional[list[dict]] = None) -> None:
        self.catalogue = catalogue if catalogue is not None else _default_catalogue()

    # ---- search -------------------------------------------------------

    def search(self, query: SearchQuery, limit: int = 10) -> list[BookCandidate]:
        if not query.title:
            raise SourceError("empty query")
        hits: list[tuple[float, BookCandidate]] = []
        for entry in self.catalogue:
            relevance = similarity(query.title, entry["title"])
            if query.author and entry.get("author"):
                relevance = max(relevance, similarity(query.author, entry["author"]) * 0.5)
            if relevance < 0.45:
                continue
            hits.append((relevance, BookCandidate(
                source=self.id,
                title=entry["title"],
                author=entry.get("author"),
                book_page=f"https://{MOCK_HOST}/book/{entry['slug']}",
                pdf_url=entry.get("pdf_url"),
                pages=entry.get("pages"),
                file_type=entry.get("file_type", "pdf"),
                volume=entry.get("volume"),
                size_bytes=entry.get("size_bytes"),
                id=f"{self.id}:{entry['slug']}",
            )))
        hits.sort(key=lambda pair: pair[0], reverse=True)
        return [candidate for _, candidate in hits[:limit]]

    # ---- acquisition --------------------------------------------------

    def _entry_for(self, candidate: BookCandidate) -> dict:
        for entry in self.catalogue:
            if candidate.pdf_url and entry.get("pdf_url") == candidate.pdf_url:
                return entry
            if candidate.id.endswith(":" + entry["slug"]):
                return entry
        raise SourceError("unknown candidate for this source")

    def transport(self, url: str, timeout: float):
        """Stand-in for the network. Serves bytes the catalogue points at."""
        for entry in self.catalogue:
            if entry.get("pdf_url") == url:
                body = _read_body(entry)
                return _MockResponse(
                    200,
                    {"content-type": entry.get("content_type", "application/pdf"),
                     "content-length": str(len(body))},
                    body,
                )
            if entry.get("redirect_from") == url:
                return _MockResponse(302, {"location": entry["pdf_url"]}, b"")
        return _MockResponse(404, {}, b"")

    def fetch_pdf(
        self,
        candidate: BookCandidate,
        dest: Path,
        on_progress: Optional[Callable[[int, Optional[int]], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> Path:
        entry = self._entry_for(candidate)
        url = entry.get("redirect_from") or entry.get("pdf_url")
        if not url:
            raise SourceError("candidate has no file link")
        try:
            result = download(
                url, dest, self.allowed_hosts,
                timeout=CONNECT_TIMEOUT,
                transport=self.transport,
                resolver=lambda host: list(_MOCK_IP),
                on_progress=on_progress,
                should_cancel=should_cancel,
                sleep=lambda seconds: None,     # deterministic tests
                min_interval=0.0,
            )
        except DownloadError as exc:
            raise SourceError(str(exc)) from exc
        return Path(result.path)


def _read_body(entry: dict) -> bytes:
    if "body" in entry:
        return entry["body"]
    return Path(entry["local_file"]).read_bytes()


def _default_catalogue() -> list[dict]:
    """Empty by default: a mock with invented books would be a fake library.

    Callers (tests, the demo fixture builder) supply their own catalogue.
    """
    return []


def from_directory(directory: str | Path) -> "MockLibrarySource":
    """Build a mock library out of real PDFs already on this machine.

    Used for the local demo (BOOKSOURCES_MOCK=1): the catalogue lists files
    the user put in data/mock-library/ — no invented titles, no network.
    """
    directory = Path(directory)
    catalogue: list[dict] = []
    if directory.is_dir():
        for path in sorted(directory.glob("*.pdf")):
            slug = path.stem.replace(" ", "-")
            catalogue.append({
                "slug": slug,
                "title": path.stem,
                "author": None,
                "pdf_url": f"https://{MOCK_HOST}/files/{slug}.pdf",
                "local_file": str(path),
                "size_bytes": path.stat().st_size,
                "file_type": "pdf",
            })
    return MockLibrarySource(catalogue)
