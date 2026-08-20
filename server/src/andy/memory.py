"""What Andy remembers between conversations.

Conversation history is bounded and clears after fifteen seconds of silence,
which is right for a robot listening to a whole room: yesterday's overheard
sentence should not colour today's answer. But that leaves nothing that survives
a pause, and "remember that I take my tablets at eight" is a reasonable thing to
ask a desk robot.

This is a small, deliberately boring store. Bounded, so it cannot grow without
limit. Written through to disk, so a restart does not lose it. Plain text
entries, because everything here is eventually spoken aloud.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import tempfile

log = logging.getLogger("andy.memory")

MAX_ENTRIES = 64
MAX_CHARS = 240


@dataclass(frozen=True, slots=True)
class Memory:
    text: str
    at: str

    def spoken_age(self, now: datetime) -> str:
        """How long ago, in words a person would use."""
        try:
            then = datetime.fromisoformat(self.at)
        except ValueError:
            return "at some point"
        delta = now - then
        hours = delta.total_seconds() / 3600
        if hours < 1:
            return "just now"
        if hours < 24:
            return f"{int(hours)} hours ago"
        days = int(hours // 24)
        return "yesterday" if days == 1 else f"{days} days ago"


class MemoryStore:
    """A bounded, durable list of things Andy was asked to remember."""

    def __init__(self, path: Path | None, *, limit: int = MAX_ENTRIES) -> None:
        self._path = path
        self._limit = limit
        self._entries: list[Memory] = []
        self._load()

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._entries = [
                Memory(text=str(item["text"]), at=str(item["at"]))
                for item in raw
                if isinstance(item, dict) and item.get("text")
            ][-self._limit :]
            log.info("recalled %d memories", len(self._entries))
        except (OSError, ValueError, KeyError):
            log.warning("memory store unreadable; starting empty", exc_info=True)
            self._entries = []

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Written through a temporary file so a crash mid-write cannot
            # leave Andy with a truncated memory.
            with tempfile.NamedTemporaryFile(
                "w", dir=self._path.parent, delete=False, encoding="utf-8"
            ) as handle:
                json.dump([asdict(entry) for entry in self._entries], handle)
                temporary = Path(handle.name)
            temporary.replace(self._path)
        except OSError:
            log.warning("could not persist memory", exc_info=True)

    def remember(self, text: str, *, now: datetime | None = None) -> str:
        text = " ".join(text.split())[:MAX_CHARS]
        if not text:
            raise ValueError("nothing to remember")
        moment = now or datetime.now(timezone.utc)
        # Rewriting a near-duplicate keeps the store from filling with the same
        # fact restated, which is what actually happens in conversation.
        self._entries = [e for e in self._entries if e.text.casefold() != text.casefold()]
        self._entries.append(Memory(text=text, at=moment.isoformat()))
        del self._entries[: max(0, len(self._entries) - self._limit)]
        self._save()
        log.info("remembered: %s", text[:80])
        return text

    def recall(self, query: str = "", *, limit: int = 8) -> list[Memory]:
        if not query.strip():
            return list(reversed(self._entries[-limit:]))
        words = {w for w in query.casefold().split() if len(w) > 2}
        scored = [
            (sum(1 for w in words if w in entry.text.casefold()), index, entry)
            for index, entry in enumerate(self._entries)
        ]
        hits = sorted(
            (item for item in scored if item[0] > 0),
            key=lambda item: (-item[0], -item[1]),
        )
        return [entry for _, _, entry in hits[:limit]]

    def forget(self, query: str) -> int:
        words = {w for w in query.casefold().split() if len(w) > 2}
        if not words:
            return 0
        before = len(self._entries)
        self._entries = [
            entry
            for entry in self._entries
            if not any(word in entry.text.casefold() for word in words)
        ]
        removed = before - len(self._entries)
        if removed:
            self._save()
        return removed

    def snapshot(self) -> dict[str, object]:
        return {
            "count": len(self._entries),
            "limit": self._limit,
            "persisted": self._path is not None,
            "recent": [entry.text for entry in reversed(self._entries[-5:])],
        }
