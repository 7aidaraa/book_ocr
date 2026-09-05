"""Turn what the user typed into ranked, de-duplicated candidates.

Deliberately not NLP. Arabic normalisation plus sequence similarity is
enough for the MVP and, unlike a model, is inspectable when it misranks.

Rule §7 lives here: a query that names an author never auto-selects a hit
whose author could not be matched. The user chooses instead.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, Optional

from .base import BookCandidate, BookSource, SearchQuery, SourceError

# Confidence at or above which a single hit may be offered as "confirmed".
AUTO_SELECT_CONFIDENCE = 0.90

_TASHKEEL = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭ]")
_TATWEEL = "ـ"
_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")
_SEPARATORS = re.compile(r"\s+[-–—:|/]\s+|\s+لـ?لمؤلف\s+|\s+تأليف\s+")
_PREFIXES = ("الشيخ ", "السيد ", "العلامة ", "الإمام ", "الدكتور ", "د. ", "ابن ")


def normalize_arabic(text: str) -> str:
    """Fold the spelling variants that make two identical titles look different."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = _TASHKEEL.sub("", text).replace(_TATWEEL, "")
    for src, dst in (("أإآٱ", "ا"), ("ىي", "ي"), ("ؤ", "و"), ("ئ", "ي"), ("ة", "ه")):
        for ch in src:
            text = text.replace(ch, dst)
    text = _NON_WORD.sub(" ", text)
    return _SPACES.sub(" ", text).strip().lower()


def _strip_titles(name: str) -> str:
    out = name.strip()
    changed = True
    while changed:
        changed = False
        for prefix in _PREFIXES:
            if out.startswith(prefix) and prefix != "ابن ":
                out, changed = out[len(prefix):].strip(), True
    return out


def parse_query(text: str, author: Optional[str] = None) -> SearchQuery:
    """Split "title - author" when the user used a separator; never guess."""
    raw = (text or "").strip()
    if author:
        return SearchQuery(title=raw, author=author, raw=raw)
    parts = _SEPARATORS.split(raw, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return SearchQuery(title=parts[0].strip(), author=parts[1].strip(), raw=raw)
    return SearchQuery(title=raw, author=None, raw=raw)


def similarity(a: str, b: str) -> float:
    a, b = normalize_arabic(a), normalize_arabic(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.92
    return SequenceMatcher(None, a, b).ratio()


def author_matches(query_author: Optional[str], candidate_author: Optional[str]) -> Optional[bool]:
    """True / False / None when the candidate advertises no author at all."""
    if not query_author:
        return None
    if not candidate_author:
        return None
    return similarity(_strip_titles(query_author), _strip_titles(candidate_author)) >= 0.75


def score(query: SearchQuery, candidate: BookCandidate) -> float:
    """0–1 match score. Only the query is compared — never the file's content."""
    title = similarity(query.title, candidate.title)
    total, weight = title * 0.6, 0.6

    match = author_matches(query.author, candidate.author)
    if query.author:
        total += (1.0 if match else 0.0) * 0.25
        weight += 0.25

    total += (0.10 if candidate.pdf_url else 0.0)
    weight += 0.10
    total += (0.05 if candidate.pages else 0.0)
    weight += 0.05
    return round(total / weight, 3)


def _dedupe_key(candidate: BookCandidate) -> tuple:
    return (
        candidate.pdf_url
        or (normalize_arabic(candidate.title), normalize_arabic(candidate.author or ""),
            normalize_arabic(candidate.volume or "")),
    )


@dataclass
class Resolution:
    query: SearchQuery
    candidates: list[BookCandidate]
    errors: dict           # source id -> reason it produced nothing
    needs_confirmation: bool
    note: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "query": {"title": self.query.title, "author": self.query.author,
                      "raw": self.query.raw},
            "candidates": [c.to_dict() for c in self.candidates],
            "errors": self.errors,
            "needs_confirmation": self.needs_confirmation,
            "note": self.note,
        }


def resolve(
    query: SearchQuery,
    sources: Iterable[BookSource],
    limit: int = 10,
) -> Resolution:
    """Search every enabled source, merge, de-duplicate, rank.

    One source failing never fails the search; its reason is reported.
    """
    found: list[BookCandidate] = []
    errors: dict = {}

    for source in sources:
        try:
            hits = source.search(query, limit=limit)
        except SourceError as exc:
            errors[source.id] = str(exc)
            continue
        except Exception as exc:                       # an adapter bug is not fatal
            errors[source.id] = f"{type(exc).__name__}: {exc}"
            continue
        for hit in hits:
            hit.source = hit.source or source.id
            hit.confidence = score(query, hit)
            found.append(hit)

    seen: set = set()
    unique: list[BookCandidate] = []
    for candidate in sorted(found, key=lambda c: c.confidence, reverse=True):
        key = _dedupe_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        if not candidate.id:
            candidate.id = f"{candidate.source}:{len(unique)}"
        unique.append(candidate)

    unique = unique[:limit]

    # §7: never load a book whose author we could not confirm.
    needs_confirmation = True
    note = None
    if not unique:
        note = "لم يُعثر على نتائج."
    else:
        best = unique[0]
        match = author_matches(query.author, best.author)
        if query.author and match is not True:
            note = "وجدت نتائج قريبة، لكن لم أستطع التحقق من تطابق المؤلف."
        elif best.confidence >= AUTO_SELECT_CONFIDENCE and (
            len(unique) == 1 or unique[1].confidence < best.confidence - 0.05
        ):
            needs_confirmation = False

    return Resolution(query=query, candidates=unique, errors=errors,
                      needs_confirmation=needs_confirmation, note=note)
