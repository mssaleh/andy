"""Who gets the speaker, and when Andy is allowed to speak first.

Until now the only path to the speaker ran inside a conversational turn, so
Andy could answer but never initiate. Proactive speech needs an owner, because
a robot that can see, feel and hear will otherwise talk over itself and talk too
much.

Three rules, in order:
  * a turn in flight outranks anything proactive;
  * one announcement at a time;
  * proactive speech is rate limited and silent during quiet hours.

The capture-pause handshake is unchanged. Everything here still goes through
`SpeakerOutput`, so the microphone always stops before the speaker starts.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, time
from enum import IntEnum
import logging

from .media import AudioStore
from .speaker import SpeakerOutput

log = logging.getLogger("andy.arbiter")


class Priority(IntEnum):
    """Higher wins. A reply to a person always outranks Andy's own idea."""

    PROACTIVE = 0
    ALERT = 1
    REPLY = 2


@dataclass(frozen=True, slots=True)
class QuietHours:
    start: time = time(22, 0)
    end: time = time(7, 30)

    def contains(self, moment: datetime) -> bool:
        now = moment.time()
        if self.start <= self.end:
            return self.start <= now < self.end
        return now >= self.start or now < self.end


class SpeechArbiter:
    """Serialises the speaker and bounds how often Andy speaks unprompted."""

    def __init__(
        self,
        speaker: SpeakerOutput,
        media: AudioStore,
        tts,
        *,
        media_base_url: str,
        min_proactive_gap: float = 90.0,
        quiet_hours: QuietHours | None = None,
        clock=datetime.now,
    ) -> None:
        self._speaker = speaker
        self._media = media
        self._tts = tts
        self._media_base_url = media_base_url.rstrip("/")
        self._min_gap = min_proactive_gap
        self._quiet = quiet_hours or QuietHours()
        self._clock = clock
        self._lock = asyncio.Lock()
        self._active: Priority | None = None
        self._last_proactive: float | None = None
        self._spoken = 0
        self._suppressed = 0

    def may_speak(self, priority: Priority) -> tuple[bool, str]:
        """Whether Andy may speak now, and why not when he may not."""
        if priority >= Priority.REPLY:
            return True, ""
        if self._active is not None and self._active >= priority:
            return False, "already speaking"
        if priority is Priority.PROACTIVE:
            if self._quiet.contains(self._clock()):
                return False, "quiet hours"
            if self._last_proactive is not None:
                elapsed = asyncio.get_running_loop().time() - self._last_proactive
                if elapsed < self._min_gap:
                    return False, f"rate limited, {self._min_gap - elapsed:.0f}s left"
        return True, ""

    async def say(self, text: str, priority: Priority = Priority.REPLY) -> bool:
        """Synthesise and speak. Returns False when the arbiter declined."""
        text = text.strip()
        if not text:
            return False
        allowed, reason = self.may_speak(priority)
        if not allowed:
            self._suppressed += 1
            log.info("suppressed %s speech: %s", priority.name.lower(), reason)
            return False

        wav = await self._tts.synthesize(text)
        if not wav:
            raise RuntimeError("speech synthesizer returned empty audio")
        key = self._media.put(wav, "audio/wav")
        url = f"{self._media_base_url}/tts/{key}.wav"

        async with self._lock:
            self._active = priority
            try:
                await self._speaker.play_announcement(url)
            finally:
                self._active = None
        if priority is Priority.PROACTIVE:
            self._last_proactive = asyncio.get_running_loop().time()
        self._spoken += 1
        log.info("spoke (%s, %d chars)", priority.name.lower(), len(text))
        return True

    async def play(self, url: str, priority: Priority = Priority.REPLY) -> None:
        """Speak an already-synthesised asset, for the turn loop's own path."""
        async with self._lock:
            self._active = priority
            try:
                await self._speaker.play_announcement(url)
            finally:
                self._active = None
        self._spoken += 1

    async def stop(self) -> None:
        await self._speaker.stop_announcement()

    def snapshot(self) -> dict[str, object]:
        return {
            "speaking": self._active.name.lower() if self._active else None,
            "spoken": self._spoken,
            "suppressed": self._suppressed,
            "quiet_hours": f"{self._quiet.start:%H:%M}-{self._quiet.end:%H:%M}",
            "min_proactive_gap_seconds": self._min_gap,
        }
