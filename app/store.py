"""Session state, plus the cache that makes this app affordable.

A garment photo is cataloged once. The result is keyed by the hash of the
image bytes and kept on disk, so the second upload of the same jacket — by this
user or the next one — costs nothing. Everything downstream (the Stylist) reads
that text, never the pixels.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

from config import DATA_DIR
from safety import Budget, SafetyLog
from schemas import CallUsage, Garment, StyleProfile

CACHE_PATH = DATA_DIR / "store.json"
_lock = threading.Lock()


def image_key(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()[:16]


class GarmentCache:
    """Hash -> Garment, persisted so savings survive a restart."""

    def __init__(self) -> None:
        self._items: dict[str, dict] = {}
        self.hits = 0
        self.misses = 0
        self._load()

    def _load(self) -> None:
        if CACHE_PATH.exists():
            try:
                self._items = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self._items = {}

    def _save(self) -> None:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(self._items, indent=2), encoding="utf-8")

    def get(self, key: str) -> Garment | None:
        row = self._items.get(key)
        if row is None:
            self.misses += 1
            return None
        self.hits += 1
        return Garment.model_validate(row)

    def put(self, key: str, garment: Garment) -> None:
        with _lock:
            self._items[key] = garment.model_dump()
            self._save()


CACHE = GarmentCache()


@dataclass
class Session:
    """One browser session: a profile, a wardrobe, a budget, a receipt."""

    id: str
    profile: StyleProfile | None = None
    wardrobe: list[Garment] = field(default_factory=list)
    usage: list[CallUsage] = field(default_factory=list)
    budget: Budget = field(default_factory=Budget)
    safety: SafetyLog = field(default_factory=SafetyLog)

    def record(self, call_usage: CallUsage) -> None:
        self.usage.append(call_usage)
        self.budget.record(call_usage)

    def record_cache_hit(self, agent: str) -> None:
        """A hit still shows up on the receipt, at zero, so the saving is visible."""
        self.usage.append(
            CallUsage(
                agent=agent,
                model="cache",
                input_tokens=0,
                cached_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
                cache_hit=True,
            )
        )

    def receipt(self) -> dict:
        return {
            "calls": [u.model_dump() for u in self.usage],
            "totals": {
                "calls": self.budget.calls,
                "cache_hits": sum(1 for u in self.usage if u.cache_hit),
                "input_tokens": sum(u.input_tokens for u in self.usage),
                "cached_tokens": sum(u.cached_tokens for u in self.usage),
                "output_tokens": sum(u.output_tokens for u in self.usage),
                "reasoning_tokens": sum(u.reasoning_tokens for u in self.usage),
                "cost_usd": round(self.budget.spent_usd, 6),
                "tokens_remaining": self.budget.remaining(),
            },
            "safety_events": self.safety.events,
        }


_sessions: dict[str, Session] = {}


def session(sid: str) -> Session:
    with _lock:
        if sid not in _sessions:
            _sessions[sid] = Session(id=sid)
        return _sessions[sid]


def seed_wardrobe() -> list[Garment]:
    """The demo closet, so the app is usable before anything is uploaded."""
    path = DATA_DIR / "seed_wardrobe.json"
    if not path.exists():
        return []
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [Garment.model_validate(r) for r in rows]
