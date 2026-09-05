"""Streaming download with an explicit, testable transport.

No new production dependency: the default transport is urllib from the
standard library. Redirects are *not* followed by urllib here — this module
follows them one hop at a time so every hop passes the policy gate.

Tests inject a fake transport, so the whole download path (streaming, size
cap, checksum, retry, cancel, redirect refusal) is covered without network.
"""

from __future__ import annotations

import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional, Protocol

from .policies import (
    CONNECT_TIMEOUT,
    MAX_PDF_BYTES,
    MAX_REDIRECTS,
    MIN_SECONDS_BETWEEN_REQUESTS,
    PolicyError,
    Resolver,
    check_url,
    default_resolver,
)
from .verifier import sha256_file

USER_AGENT = "book-ocr/1.0 (+local personal use; contact via repository)"
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class DownloadError(RuntimeError):
    """The file could not be fetched. Distinct from a policy refusal."""


class DownloadCancelled(RuntimeError):
    """The caller asked to stop mid-transfer."""


class Response(Protocol):
    status: int
    headers: dict
    def chunks(self, size: int) -> Iterator[bytes]: ...
    def close(self) -> None: ...


Transport = Callable[[str, float], Response]


@dataclass
class Download:
    path: str
    sha256: str
    size_bytes: int
    final_url: str
    content_type: Optional[str] = None


class _UrllibResponse:
    def __init__(self, raw) -> None:
        self._raw = raw
        self.status = getattr(raw, "status", 200) or 200
        self.headers = {k.lower(): v for k, v in raw.headers.items()}

    def chunks(self, size: int) -> Iterator[bytes]:
        while True:
            block = self._raw.read(size)
            if not block:
                return
            yield block

    def close(self) -> None:
        try:
            self._raw.close()
        except Exception:
            pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface redirects to the caller instead of silently following them."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def urllib_transport(url: str, timeout: float) -> Response:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        return _UrllibResponse(_opener.open(request, timeout=timeout))
    except urllib.error.HTTPError as exc:
        if exc.code in (301, 302, 303, 307, 308):
            return _RedirectResponse(exc.code, dict(exc.headers))
        raise DownloadError(f"HTTP {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise DownloadError(f"connection failed: {exc.reason}") from exc


class _RedirectResponse:
    def __init__(self, status: int, headers: dict) -> None:
        self.status = status
        self.headers = {k.lower(): v for k, v in headers.items()}

    def chunks(self, size: int) -> Iterator[bytes]:
        return iter(())

    def close(self) -> None:
        return None


# Politeness: never hammer one host, even across concurrent jobs.
_last_request_at: dict[str, float] = {}
_rate_lock = threading.Lock()


def _throttle(host: str, min_interval: float, sleep: Callable[[float], None]) -> None:
    if min_interval <= 0:
        return
    with _rate_lock:
        elapsed = time.monotonic() - _last_request_at.get(host, 0.0)
        wait = min_interval - elapsed
        if wait > 0:
            sleep(wait)
        _last_request_at[host] = time.monotonic()


def download(
    url: str,
    dest: str | Path,
    allowed_hosts,
    *,
    max_bytes: int = MAX_PDF_BYTES,
    timeout: float = CONNECT_TIMEOUT,
    retries: int = 2,
    transport: Transport = urllib_transport,
    resolver: Resolver = default_resolver,
    on_progress: Optional[Callable[[int, Optional[int]], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    sleep: Callable[[float], None] = time.sleep,
    min_interval: float = MIN_SECONDS_BETWEEN_REQUESTS,
    chunk_size: int = 256 * 1024,
) -> Download:
    """Fetch `url` to `dest`, enforcing policy on every hop.

    Raises PolicyError (refused), DownloadCancelled, or DownloadError.
    A failed attempt never leaves a partial file behind.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        if attempt:
            sleep(min(2.0 ** attempt, 8.0))
        try:
            return _attempt(
                url, dest, allowed_hosts,
                max_bytes=max_bytes, timeout=timeout, transport=transport,
                resolver=resolver, on_progress=on_progress,
                should_cancel=should_cancel, sleep=sleep,
                min_interval=min_interval, chunk_size=chunk_size,
            )
        except (PolicyError, DownloadCancelled):
            raise                       # never retried: the answer will not change
        except DownloadError as exc:
            last_error = exc
            if not getattr(exc, "retryable", False):
                raise
    raise DownloadError(f"giving up after {retries + 1} attempts: {last_error}")


def _attempt(
    url: str,
    dest: Path,
    allowed_hosts,
    *,
    max_bytes: int,
    timeout: float,
    transport: Transport,
    resolver: Resolver,
    on_progress,
    should_cancel,
    sleep,
    min_interval: float,
    chunk_size: int,
) -> Download:
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        host = check_url(current, allowed_hosts, resolver)   # every hop, no exception
        _throttle(host, min_interval, sleep)
        response = transport(current, timeout)
        try:
            if response.status in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location:
                    raise DownloadError(f"HTTP {response.status} without Location")
                current = urllib.parse.urljoin(current, location)
                continue
            if response.status >= 400:
                error = DownloadError(f"HTTP {response.status}")
                error.retryable = response.status in RETRYABLE_STATUS  # type: ignore[attr-defined]
                raise error
            return _stream_to_file(
                response, current, dest,
                max_bytes=max_bytes, on_progress=on_progress,
                should_cancel=should_cancel, chunk_size=chunk_size,
            )
        finally:
            response.close()
    raise DownloadError(f"too many redirects (>{MAX_REDIRECTS})")


def _stream_to_file(
    response: Response,
    final_url: str,
    dest: Path,
    *,
    max_bytes: int,
    on_progress,
    should_cancel,
    chunk_size: int,
) -> Download:
    declared = response.headers.get("content-length")
    total = int(declared) if declared and declared.isdigit() else None
    if total is not None and total > max_bytes:
        raise DownloadError(f"declared size {total} exceeds limit {max_bytes}")

    partial = dest.with_suffix(dest.suffix + ".part")
    written = 0
    try:
        with partial.open("wb") as out:
            for block in response.chunks(chunk_size):
                if should_cancel is not None and should_cancel():
                    raise DownloadCancelled("cancelled by caller")
                written += len(block)
                if written > max_bytes:
                    raise DownloadError(f"stream exceeded limit {max_bytes} bytes")
                out.write(block)
                if on_progress is not None:
                    on_progress(written, total)
        if written == 0:
            raise DownloadError("empty response body")
        if total is not None and written != total:
            raise DownloadError(f"incomplete download: {written} of {total} bytes")
        partial.replace(dest)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise

    return Download(
        path=str(dest),
        sha256=sha256_file(dest),
        size_bytes=written,
        final_url=final_url,
        content_type=response.headers.get("content-type"),
    )
