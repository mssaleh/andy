"""Reminders, and anything else Andy has to say at a particular time.

"Remind me to drink water in ten minutes" is one of the first things anyone
asks a desk robot, and it needs three things the turn loop cannot provide: it
outlives the conversation, it outlives a server restart, and it has to reach the
speaker without anyone having spoken first.

Timers therefore live on disk and fire into the arbiter, which decides whether
Andy may actually speak. A reminder that comes due during quiet hours is still
delivered, because it was explicitly asked for — that is what `ALERT` is for.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import tempfile
import uuid

from .arbiter import Priority, SpeechArbiter

log = logging.getLogger("andy.scheduler")

MAX_TIMERS = 32
MAX_HORIZON = timedelta(days=7)
TICK_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class Timer:
    id: str
    text: str
    due: str

    def due_at(self) -> datetime:
        return datetime.fromisoformat(self.due)


class Scheduler:
    """Durable timers that speak when they come due."""

    def __init__(
        self,
        arbiter: SpeechArbiter,
        path: Path | None,
        *,
        limit: int = MAX_TIMERS,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self._arbiter = arbiter
        self._path = path
        self._limit = limit
        self._clock = clock
        self._timers: list[Timer] = []
        self._task: asyncio.Task[None] | None = None
        self._fired = 0
        self._load()

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._timers = [
                Timer(id=str(i["id"]), text=str(i["text"]), due=str(i["due"]))
                for i in raw
                if isinstance(i, dict) and i.get("text")
            ]
            log.info("restored %d timers", len(self._timers))
        except (OSError, ValueError, KeyError):
            log.warning("timer store unreadable; starting empty", exc_info=True)
            self._timers = []

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w", dir=self._path.parent, delete=False, encoding="utf-8"
            ) as handle:
                json.dump([asdict(t) for t in self._timers], handle)
                temporary = Path(handle.name)
            temporary.replace(self._path)
        except OSError:
            log.warning("could not persist timers", exc_info=True)

    def schedule(self, text: str, delay: timedelta) -> Timer:
        text = " ".join(text.split())[:200]
        if not text:
            raise ValueError("a reminder needs something to say")
        if delay <= timedelta(0):
            raise ValueError("a reminder must be in the future")
        if delay > MAX_HORIZON:
            raise ValueError("a reminder cannot be more than seven days away")
        if len(self._timers) >= self._limit:
            raise ValueError("too many reminders are already set")
        timer = Timer(
            id=uuid.uuid4().hex[:8],
            text=text,
            due=(self._clock() + delay).isoformat(),
        )
        self._timers.append(timer)
        self._save()
        log.info("timer %s set for %s: %s", timer.id, timer.due, text[:60])
        return timer

    def cancel(self, timer_id: str) -> bool:
        before = len(self._timers)
        self._timers = [t for t in self._timers if t.id != timer_id]
        if len(self._timers) != before:
            self._save()
            return True
        return False

    def pending(self) -> list[Timer]:
        return sorted(self._timers, key=lambda t: t.due)

    async def due(self) -> list[Timer]:
        """Pop everything that has come due, persisting the removal first."""
        now = self._clock()
        ready, remaining = [], []
        for timer in self._timers:
            try:
                (ready if timer.due_at() <= now else remaining).append(timer)
            except ValueError:
                continue  # unparseable entry, drop it
        if ready:
            self._timers = remaining
            self._save()
        return ready

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="andy-scheduler")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(TICK_SECONDS)
            try:
                for timer in await self.due():
                    # ALERT, not PROACTIVE: this was asked for, so quiet hours
                    # and the proactive rate limit do not apply to it.
                    await self._arbiter.say(timer.text, Priority.ALERT)
                    self._fired += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("scheduler tick failed")

    def snapshot(self) -> dict[str, object]:
        return {
            "pending": [
                {"id": t.id, "text": t.text, "due": t.due} for t in self.pending()
            ],
            "fired": self._fired,
            "limit": self._limit,
            "persisted": self._path is not None,
            "running": self._task is not None and not self._task.done(),
        }
