"""Whether Andy can still hear and speak, shown on Andy.

`/health` is honest and nobody stands over it. Andy can lose his recogniser and
his synthesiser and carry on wearing his ordinary listening ring, because from
across the room a stopped backend looks exactly like a quiet evening: he blinks,
he glows, he reacts to a hand on his head, and he answers nothing. The person
who could restart it is sitting in front of him and has no way to know.

So the two services that decide whether he can be spoken to at all are asked on
a timer, and the answer goes where someone will actually read it -- his face.
Nothing here moves him and nothing here speaks, because both of those are the
things that are already failing.
"""

from __future__ import annotations

import asyncio
import logging

from .effects import EffectController, EmotionRequest

log = logging.getLogger("andy.watch")

#: How often to ask. Both probes are plain GETs against services on the same
#: machine, so their cost is noise. The interval is set by the other end: the
#: firmware emotion table holds `unwell` for 60 seconds, and an alarm that is
#: not renewed inside that window lapses on its own while the outage continues.
PROBE_SECONDS = 30.0

#: Consecutive failures before Andy wears it. One is a restart, a model reload,
#: or a probe that raced a container coming up. Two, half a minute apart, is an
#: outage worth a person's attention.
FAILURES_BEFORE_ALARM = 2

#: The mood that means something is wrong with Andy himself. Deliberately not
#: the `sleepy` a flat battery wears: the two faults a person can actually do
#: something about should not look alike.
ALARM_EMOTION = "unwell"

#: Strength of that mood. High enough to be unmistakable, short of the
#: distress the face reserves for being shaken or hurt.
ALARM_INTENSITY = 70


class BackendWatch:
    """Asks whether Andy's ears and voice are answering, and shows the answer."""

    def __init__(
        self,
        *,
        asr,
        tts,
        effects: EffectController | None,
        interval: float = PROBE_SECONDS,
        failures_before_alarm: int = FAILURES_BEFORE_ALARM,
        emotion: str = ALARM_EMOTION,
    ) -> None:
        self._asr = asr
        self._tts = tts
        self._effects = effects
        self._interval = interval
        self._threshold = max(1, failures_before_alarm)
        self._emotion = emotion
        self._failures = 0
        self._alarmed = False
        self._last_down: str = ""
        self._task: asyncio.Task[None] | None = None

    @property
    def alarmed(self) -> bool:
        return self._alarmed

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="andy-backend-watch")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def check_once(self) -> bool:
        """One round of probes. Returns whether Andy can hear and speak."""
        asr_ok, tts_ok = await asyncio.gather(
            self._asr.health(), self._tts.health()
        )
        if asr_ok and tts_ok:
            self._failures = 0
            if self._alarmed:
                log.info("Andy can hear and speak again")
                self._clear()
            return True

        self._failures += 1
        lost = ", ".join(
            phrase
            for phrase, ok in (
                ("cannot hear: the recogniser is not answering", asr_ok),
                ("cannot speak: the synthesiser is not answering", tts_ok),
            )
            if not ok
        )
        if self._failures < self._threshold:
            log.debug("backend probe failed (%d): %s", self._failures, lost)
            return False

        if not self._alarmed or lost != self._last_down:
            log.warning("Andy %s", lost)
        self._last_down = lost
        await self._wear()
        return False

    async def _wear(self) -> None:
        if self._effects is None or not self._effects.available():
            # Andy is not there to be told. The alarm stays unset so that a
            # device which reconnects mid-outage still gets the face on the
            # next round rather than being counted as already wearing it.
            return
        try:
            await self._effects.set_emotion(
                EmotionRequest(self._emotion, ALARM_INTENSITY)
            )
        except Exception:
            log.warning("could not show the outage on Andy's face")
            log.debug("outage face failed", exc_info=True)
            return
        self._alarmed = True

    def _clear(self) -> None:
        self._alarmed = False
        self._last_down = ""
        if self._effects is None or not self._effects.available():
            return
        try:
            self._effects.reset_emotion()
        except Exception:
            log.debug("could not clear the outage face", exc_info=True)

    async def _run(self) -> None:
        while True:
            try:
                await self.check_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("backend watch failed")
            await asyncio.sleep(self._interval)

    def snapshot(self) -> dict[str, object]:
        return {
            "alarmed": self._alarmed,
            "failures": self._failures,
            "interval_seconds": self._interval,
            "down": self._last_down,
        }
