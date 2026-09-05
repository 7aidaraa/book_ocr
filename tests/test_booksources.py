"""Book source layer tests. No network, ever: every transport is injected."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.booksources.base import BookCandidate, SearchQuery, SourceError
from app.booksources.cache import SearchCache
from app.booksources.downloader import (
    DownloadCancelled, DownloadError, download,
)
from app.booksources.metadata import build_record
from app.booksources.policies import PolicyError, check_url
from app.booksources.registry import build_registry, enabled_sources
from app.booksources.resolver import (
    author_matches, normalize_arabic, parse_query, resolve, score,
)
from app.booksources.sources.mock import MOCK_HOST, MockLibrarySource, _MockResponse
from app.booksources.verifier import VerificationError, verify_pdf
from tests.make_fixture import make_fixture

PUBLIC = lambda host: ["93.184.216.34"]        # noqa: E731  a real public address


# --------------------------------------------------------------------------
# security: SSRF, allowlist, redirects, traversal
# --------------------------------------------------------------------------

def test_https_only():
    with pytest.raises(PolicyError, match="scheme"):
        check_url("http://example.com/a.pdf", ["example.com"], PUBLIC)


@pytest.mark.parametrize("url", [
    "https://localhost/a.pdf",
    "https://127.0.0.1/a.pdf",
    "https://10.0.0.1/a.pdf",
    "https://192.168.1.10/a.pdf",
    "https://169.254.169.254/latest/meta-data/",
    "https://[::1]/a.pdf",
])
def test_localhost_and_private_targets_refused(url):
    with pytest.raises(PolicyError):
        check_url(url, ["example.com"], PUBLIC)


@pytest.mark.parametrize("addresses", [
    ["127.0.0.1"], ["10.1.2.3"], ["192.168.0.5"], ["169.254.169.254"], ["::1"],
])
def test_dns_rebinding_to_private_address_refused(addresses):
    """An allowlisted name that resolves inward is still refused."""
    with pytest.raises(PolicyError, match="non-public"):
        check_url("https://example.com/a.pdf", ["example.com"], lambda h: addresses)


def test_host_outside_allowlist_refused():
    with pytest.raises(PolicyError, match="allowlist"):
        check_url("https://evil.example.net/a.pdf", ["example.com"], PUBLIC)


def test_subdomain_of_allowed_host_accepted():
    assert check_url("https://files.example.com/a.pdf", ["example.com"], PUBLIC)


def test_credentials_in_url_refused():
    with pytest.raises(PolicyError, match="credentials"):
        check_url("https://u:p@example.com/a.pdf", ["example.com"], PUBLIC)


def test_odd_port_refused():
    with pytest.raises(PolicyError, match="port"):
        check_url("https://example.com:8080/a.pdf", ["example.com"], PUBLIC)


def test_no_allowed_hosts_means_nothing_is_allowed():
    with pytest.raises(PolicyError):
        check_url("https://example.com/a.pdf", [], PUBLIC)


def test_redirect_off_allowlist_is_refused(tmp_path):
    def transport(url, timeout):
        if url.endswith("/start.pdf"):
            return _MockResponse(302, {"location": "https://evil.example.net/x.pdf"}, b"")
        return _MockResponse(200, {}, b"%PDF-1.4 leaked")

    with pytest.raises(PolicyError, match="allowlist"):
        download("https://example.com/start.pdf", tmp_path / "o.pdf", ["example.com"],
                 transport=transport, resolver=PUBLIC, sleep=lambda s: None,
                 min_interval=0.0)
    assert not (tmp_path / "o.pdf").exists()


def test_redirect_inside_allowlist_is_followed(tmp_path):
    def transport(url, timeout):
        if url.endswith("/start.pdf"):
            return _MockResponse(302, {"location": "https://files.example.com/f.pdf"}, b"")
        return _MockResponse(200, {"content-length": "9"}, b"%PDF-1.4\n")

    result = download("https://example.com/start.pdf", tmp_path / "o.pdf",
                      ["example.com"], transport=transport, resolver=PUBLIC,
                      sleep=lambda s: None, min_interval=0.0)
    assert result.final_url == "https://files.example.com/f.pdf"


def test_redirect_loop_is_bounded(tmp_path):
    transport = lambda url, t: _MockResponse(  # noqa: E731
        302, {"location": "https://example.com/again.pdf"}, b"")
    with pytest.raises(DownloadError, match="redirects"):
        download("https://example.com/a.pdf", tmp_path / "o.pdf", ["example.com"],
                 transport=transport, resolver=PUBLIC, sleep=lambda s: None,
                 min_interval=0.0)


def test_job_id_path_traversal_refused(tmp_path):
    from app.jobs import JobStore

    store = JobStore(tmp_path)
    with pytest.raises(ValueError, match="unsafe job id"):
        store._path("../../etc/passwd")


# --------------------------------------------------------------------------
# downloader
# --------------------------------------------------------------------------

def _serve(body: bytes, headers: dict | None = None, status: int = 200):
    head = {"content-length": str(len(body)), "content-type": "application/pdf"}
    head.update(headers or {})
    return lambda url, timeout: _MockResponse(status, head, body)


def test_download_streams_and_checksums(tmp_path):
    body = b"%PDF-1.4\n" + b"x" * 5000
    seen: list[tuple] = []
    result = download("https://example.com/a.pdf", tmp_path / "o.pdf", ["example.com"],
                      transport=_serve(body), resolver=PUBLIC, chunk_size=1024,
                      on_progress=lambda d, t: seen.append((d, t)),
                      sleep=lambda s: None, min_interval=0.0)
    assert (tmp_path / "o.pdf").read_bytes() == body
    assert result.size_bytes == len(body)
    assert len(result.sha256) == 64
    assert len(seen) > 1 and seen[-1] == (len(body), len(body))


def test_download_rejects_oversize_stream(tmp_path):
    with pytest.raises(DownloadError, match="exceed"):
        download("https://example.com/a.pdf", tmp_path / "o.pdf", ["example.com"],
                 transport=_serve(b"x" * 100), resolver=PUBLIC, max_bytes=10,
                 sleep=lambda s: None, min_interval=0.0)
    assert not (tmp_path / "o.pdf").exists()


def test_download_rejects_incomplete_body(tmp_path):
    transport = _serve(b"%PDF-1.4 short", {"content-length": "9999"})
    with pytest.raises(DownloadError, match="incomplete"):
        download("https://example.com/a.pdf", tmp_path / "o.pdf", ["example.com"],
                 transport=transport, resolver=PUBLIC, retries=0,
                 sleep=lambda s: None, min_interval=0.0)
    assert not list(tmp_path.glob("*.part"))


def test_download_retries_then_succeeds(tmp_path):
    calls = {"n": 0}

    def transport(url, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            return _MockResponse(503, {}, b"")
        return _MockResponse(200, {"content-length": "9"}, b"%PDF-1.4\n")

    result = download("https://example.com/a.pdf", tmp_path / "o.pdf", ["example.com"],
                      transport=transport, resolver=PUBLIC, retries=2,
                      sleep=lambda s: None, min_interval=0.0)
    assert calls["n"] == 2 and result.size_bytes == 9


def test_download_does_not_retry_a_404(tmp_path):
    calls = {"n": 0}

    def transport(url, timeout):
        calls["n"] += 1
        return _MockResponse(404, {}, b"")

    with pytest.raises(DownloadError, match="404"):
        download("https://example.com/a.pdf", tmp_path / "o.pdf", ["example.com"],
                 transport=transport, resolver=PUBLIC, retries=3,
                 sleep=lambda s: None, min_interval=0.0)
    assert calls["n"] == 1


def test_download_can_be_cancelled(tmp_path):
    with pytest.raises(DownloadCancelled):
        download("https://example.com/a.pdf", tmp_path / "o.pdf", ["example.com"],
                 transport=_serve(b"%PDF-1.4" + b"y" * 9000), resolver=PUBLIC,
                 chunk_size=512, should_cancel=lambda: True,
                 sleep=lambda s: None, min_interval=0.0)
    assert not (tmp_path / "o.pdf").exists() and not list(tmp_path.glob("*.part"))


# --------------------------------------------------------------------------
# verifier
# --------------------------------------------------------------------------

def test_verify_accepts_a_real_pdf(tmp_path):
    pdf = make_fixture(tmp_path / "book.pdf", pages=3)
    verified = verify_pdf(pdf)
    assert verified.pages == 3 and len(verified.sha256) == 64


def test_verify_rejects_html_disguised_as_pdf(tmp_path):
    fake = tmp_path / "book.pdf"
    fake.write_bytes(b"<!DOCTYPE html><html><body>Login required</body></html>")
    with pytest.raises(VerificationError, match="HTML"):
        verify_pdf(fake)


def test_verify_rejects_truncated_pdf(tmp_path):
    pdf = make_fixture(tmp_path / "book.pdf", pages=2)
    data = pdf.read_bytes()
    pdf.write_bytes(data[: len(data) // 3])
    with pytest.raises(VerificationError):
        verify_pdf(pdf)


def test_verify_rejects_empty_and_oversize(tmp_path):
    empty = tmp_path / "e.pdf"
    empty.write_bytes(b"")
    with pytest.raises(VerificationError, match="empty"):
        verify_pdf(empty)
    pdf = make_fixture(tmp_path / "b.pdf", pages=1)
    with pytest.raises(VerificationError, match="too large"):
        verify_pdf(pdf, max_bytes=10)


def test_verify_rejects_too_many_pages(tmp_path):
    pdf = make_fixture(tmp_path / "b.pdf", pages=3)
    with pytest.raises(VerificationError, match="too many pages"):
        verify_pdf(pdf, max_pages=2)


def test_verify_detects_checksum_mismatch(tmp_path):
    pdf = make_fixture(tmp_path / "b.pdf", pages=1)
    with pytest.raises(VerificationError, match="checksum"):
        verify_pdf(pdf, expected_sha256="0" * 64)


# --------------------------------------------------------------------------
# resolver
# --------------------------------------------------------------------------

def test_query_parsing_splits_author_only_on_a_separator():
    assert parse_query("شرح قطر الندى").author is None
    parsed = parse_query("دروس في علم الأصول - محمد باقر الصدر")
    assert parsed.title == "دروس في علم الأصول"
    assert parsed.author == "محمد باقر الصدر"


def test_arabic_normalisation_folds_spelling_variants():
    assert normalize_arabic("الإحياء") == normalize_arabic("الاحياء")
    assert normalize_arabic("شَرْحُ") == "شرح"


def test_author_match_is_tri_state():
    assert author_matches("محمد باقر الصدر", "السيد محمد باقر الصدر") is True
    assert author_matches("محمد باقر الصدر", "ابن هشام") is False
    assert author_matches("ابن هشام", None) is None
    assert author_matches(None, "ابن هشام") is None


def _library():
    return MockLibrarySource([
        {"slug": "durus-1", "title": "دروس في علم الأصول", "author": "محمد باقر الصدر",
         "pages": 320, "pdf_url": f"https://{MOCK_HOST}/files/durus-1.pdf",
         "body": b"%PDF-x", "volume": "الجزء الأول"},
        {"slug": "durus-other", "title": "دروس في علم الأصول", "author": "مؤلف آخر",
         "pages": 200, "pdf_url": f"https://{MOCK_HOST}/files/durus-other.pdf",
         "body": b"%PDF-y"},
        {"slug": "qatr", "title": "شرح قطر الندى وبل الصدى", "author": "ابن هشام",
         "pages": 424, "pdf_url": f"https://{MOCK_HOST}/files/qatr.pdf",
         "body": b"%PDF-z"},
    ])


def test_title_match_ranks_first():
    res = resolve(parse_query("شرح قطر الندى"), [_library()])
    assert res.candidates[0].title.startswith("شرح قطر الندى")


def test_author_match_outranks_a_same_title_wrong_author():
    res = resolve(parse_query("دروس في علم الأصول - محمد باقر الصدر"), [_library()])
    assert res.candidates[0].author == "محمد باقر الصدر"


def test_wrong_author_is_never_auto_selected():
    """§7: a named author that cannot be confirmed must ask the user."""
    library = MockLibrarySource([
        {"slug": "durus-other", "title": "دروس في علم الأصول", "author": "مؤلف آخر",
         "pages": 200, "pdf_url": f"https://{MOCK_HOST}/files/o.pdf", "body": b"%PDF-y"},
    ])
    res = resolve(parse_query("دروس في علم الأصول - محمد باقر الصدر"), [library])
    assert res.needs_confirmation is True
    assert "لم أستطع التحقق من تطابق المؤلف" in res.note


def test_multiple_volumes_are_listed_not_merged():
    library = MockLibrarySource([
        {"slug": "v1", "title": "كتاب س", "author": "مؤلف", "volume": "الجزء الأول",
         "pdf_url": f"https://{MOCK_HOST}/files/v1.pdf", "body": b"%PDF-1"},
        {"slug": "v2", "title": "كتاب س", "author": "مؤلف", "volume": "الجزء الثاني",
         "pdf_url": f"https://{MOCK_HOST}/files/v2.pdf", "body": b"%PDF-2"},
    ])
    res = resolve(parse_query("كتاب س"), [library])
    assert len(res.candidates) == 2
    assert {c.volume for c in res.candidates} == {"الجزء الأول", "الجزء الثاني"}


def test_no_results_reports_cleanly():
    res = resolve(parse_query("كتاب لا وجود له إطلاقًا"), [_library()])
    assert res.candidates == [] and res.needs_confirmation is True


def test_duplicates_across_sources_are_merged():
    res = resolve(parse_query("شرح قطر الندى"), [_library(), _library()])
    assert sum(1 for c in res.candidates if c.title.startswith("شرح قطر")) == 1


def test_a_failing_source_does_not_fail_the_search():
    class Broken(MockLibrarySource):
        id = "broken"

        def search(self, query, limit=10):
            raise SourceError("boom")

    res = resolve(parse_query("شرح قطر الندى"), [Broken([]), _library()])
    assert res.errors["broken"] == "boom" and res.candidates


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------

def test_alfeker_is_registered_but_never_runnable():
    entry = next(e for e in build_registry() if e.id == "alfeker")
    assert entry.status.enabled is False
    assert entry.runnable() is False
    assert entry.factory is None                   # no code path can reach it
    assert "UNVERIFIED" in entry.status.reason


def test_mock_is_off_unless_explicitly_enabled(monkeypatch):
    monkeypatch.delenv("BOOKSOURCES_MOCK", raising=False)
    assert enabled_sources() == []
    monkeypatch.setenv("BOOKSOURCES_MOCK", "1")
    assert [s.id for s in enabled_sources()] == ["mock"]


# --------------------------------------------------------------------------
# cache
# --------------------------------------------------------------------------

def test_cache_returns_within_ttl_and_expires_after(tmp_path):
    cache = SearchCache(tmp_path / "c.json", ttl=100)
    key = SearchCache.key("قطر الندى", None, ["mock"])
    cache.put(key, {"hits": 1}, now=1000.0)
    assert cache.get(key, now=1050.0) == {"hits": 1}
    assert cache.get(key, now=2000.0) is None


def test_cache_survives_reload(tmp_path):
    key = SearchCache.key("قطر الندى", None, ["mock"])
    SearchCache(tmp_path / "c.json").put(key, {"hits": 2})
    assert SearchCache(tmp_path / "c.json").get(key) == {"hits": 2}


# --------------------------------------------------------------------------
# metadata
# --------------------------------------------------------------------------

def test_metadata_records_measured_pages_not_advertised(tmp_path):
    pdf = make_fixture(tmp_path / "b.pdf", pages=2)
    candidate = BookCandidate(source="mock", title="كتاب", pages=999)
    record = build_record(candidate, verify_pdf(pdf))
    assert record["pages"] == 2                       # from the file
    assert record["source"]["advertised_pages"] == 999  # kept, but not trusted
