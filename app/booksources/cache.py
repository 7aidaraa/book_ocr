"""TTL cache for *search results only*.

Never caches files. A cached entry records what a source said about a book,
which is metadata, not content — and metadata is never evidence (§19/§20).
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Optional

CACHE_DIR = Path("data/cache")
CACHE_FILE = CACHE_DIR / "booksearch.json"
DEFAULT_TTL = 24 * 3600     # a library catalogue does not change by the minute


class SearchCache:
    def __init__(self, path: str | Path = CACHE_FILE, ttl: int = DEFAULT_TTL) -> None:
        self.path = Path(path)
        self.ttl = ttl
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._data = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    @staticmethod
    def key(title: str, author: Optional[str], sources: list[str]) -> str:
        return json.dumps([title, author or "", sorted(sources)], ensure_ascii=False)

    def get(self, key: str, now: Optional[float] = None) -> Optional[Any]:
        now = time.time() if now is None else now
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            if now - entry.get("ts", 0) > self.ttl:
                self._data.pop(key, None)
                self._save()
                return None
            return entry.get("value")

    def put(self, key: str, value: Any, now: Optional[float] = None) -> None:
        with self._lock:
            self._data[key] = {"ts": time.time() if now is None else now, "value": value}
            self._save()

    def clear(self) -> None:
        with self._lock:
            self._data = {}
            self._save()
