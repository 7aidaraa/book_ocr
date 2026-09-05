"""Which sources exist, what has actually been verified about each, and
which are allowed to run.

A source's presence in this table means nothing on its own (§23). It runs
only when every verification flag is true AND `enabled` is true.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, asdict, field
from typing import Optional

from .base import BookSource


@dataclass
class SourceStatus:
    """Facts established by a real probe, not intentions."""

    discovered: bool = False
    reachable: bool = False
    searchable: bool = False
    downloadable: bool = False
    terms_checked: bool = False
    enabled: bool = False
    last_checked: Optional[str] = None
    reason: Optional[str] = None       # why it is not enabled

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SourceEntry:
    id: str
    name: str
    status: SourceStatus
    capabilities: dict = field(default_factory=dict)
    factory: Optional[object] = None   # callable returning a BookSource

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "capabilities": self.capabilities,
            "status": self.status.to_dict(),
        }

    def runnable(self) -> bool:
        """Enabled AND every verification flag established. Both, always."""
        s = self.status
        return bool(
            s.enabled and s.discovered and s.reachable and s.searchable
            and s.downloadable and s.terms_checked and self.factory is not None
        )


MOCK_LIBRARY_DIR = "data/mock-library"


def _mock_factory():
    """Real local PDFs the user dropped in data/mock-library/, served as if
    they came from a remote library. Never invented titles."""
    from .sources.mock import from_directory

    return from_directory(MOCK_LIBRARY_DIR)


def _mock_enabled() -> bool:
    # Off by default: the mock is a test double and a demo, not a library.
    return os.environ.get("BOOKSOURCES_MOCK", "0") == "1"


def build_registry() -> list[SourceEntry]:
    """The live table. Read on every call so env changes take effect."""
    return [
        SourceEntry(
            id="mock",
            name="مكتبة تجريبية محلية",
            capabilities={"search": True, "book_page": True, "pdf": True},
            status=SourceStatus(
                discovered=True, reachable=True, searchable=True,
                downloadable=True, terms_checked=True,
                enabled=_mock_enabled(),
                reason=None if _mock_enabled() else "معطّل افتراضيًا؛ فعّله بـ BOOKSOURCES_MOCK=1",
            ),
            factory=_mock_factory,
        ),
        SourceEntry(
            id="alfeker",
            name="شبكة الفكر",
            capabilities={"search": False, "book_page": False, "pdf": False},
            status=SourceStatus(
                discovered=True,
                enabled=False,
                reason=(
                    "UNVERIFIED / NETWORK_BLOCKED — لم يُقرأ robots.txt ولا شروط "
                    "الاستخدام، ولم تُكتشف بنية الموقع. لا يوجد كود يتصل به."
                ),
            ),
            factory=None,
        ),
    ]


def enabled_sources() -> list[BookSource]:
    """Instantiate only sources that passed every check and are switched on."""
    return [entry.factory() for entry in build_registry() if entry.runnable()]  # type: ignore[misc]
