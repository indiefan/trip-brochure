"""Shared by the pipeline scripts: the trip folder, a fingerprint cache (so a step runs again only for what changed),
and one Claude client. Set ANTHROPIC_API_KEY in the environment (and GOOGLE_MAPS_KEY for places.py)."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5")


def say(*a):
    print(*a, file=sys.stderr, flush=True)


class Trip:
    def __init__(self, folder: str):
        self.dir = Path(folder).resolve()
        self.path = self.dir / "trip.json"
        self.data = json.loads(self.path.read_text(encoding="utf-8"))
        self.cache_path = self.dir / ".cache" / "pipeline.json"
        self.cache = json.loads(self.cache_path.read_text()) if self.cache_path.exists() else {}

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1))

    def stale(self, key: str, text: str, force: bool = False) -> bool:
        """True when `text` (what a step would work from) differs from what the step last saw for `key`."""
        fp = hashlib.sha1(text.encode()).hexdigest()[:16]
        return force or self.cache.get(key) != fp

    def done(self, key: str, text: str) -> None:
        self.cache[key] = hashlib.sha1(text.encode()).hexdigest()[:16]

    @property
    def events(self) -> list[dict]:
        return self.data.setdefault("events", [])

    @property
    def hotels(self) -> list[dict]:
        return self.data.setdefault("hotels", [])

    def event(self, eid: str) -> dict | None:
        return next((e for e in self.events if e["id"] == eid), None)


def claude():
    import anthropic
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("set ANTHROPIC_API_KEY (console.anthropic.com → API keys)")
    return anthropic.Anthropic()
