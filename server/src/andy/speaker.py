"""Andy's speaker, and the handshake that keeps him from hearing himself.

This lived inside the motion controller, which meant the only code path to the
speaker ran inside a conversational turn. Andy could answer but could never
speak first. Separating it is what makes a proactive announcement possible.

The capture-pause ordering is unchanged and is not negotiable: the microphone
must stop and the device must confirm it before any playback starts.
"""

from __future__ import annotations

import asyncio
import logging

from .device import DeviceState

log = logging.getLogger("andy.speaker")

PAUSE_TIMEOUT = 10.0
START_TIMEOUT = 10.0
FINISH_TIMEOUT = 45.0


class SpeakerOutput:
    """Serialises playback and owns the pause-then-speak handshake."""

    def __init__(self, device: DeviceState) -> None:
        self._device = device
        self._lock = asyncio.Lock()

    async def play_announcement(self, url: str) -> None:
        if not url:
            raise ValueError("announcement URL cannot be empty")
        async with self._lock:
            device = self._device
            if not device.connected:
                raise RuntimeError("device disconnected while starting announcement")

            before_pauses = device.counter("capture_pauses")
            device.press("pause_capture_for_response")
            await device.wait_for(
                lambda: device.counter("capture_pauses") > before_pauses,
                PAUSE_TIMEOUT,
                "capture pause before announcement",
            )

            before_starts = device.counter("announcement_starts")
            before_finishes = device.counter("announcement_finishes")
            device.play_media(url)
            try:
                await device.wait_for(
                    lambda: device.counter("announcement_starts") > before_starts,
                    START_TIMEOUT,
                    "announcement start",
                )
                await device.wait_for(
                    lambda: device.counter("announcement_finishes") > before_finishes,
                    FINISH_TIMEOUT,
                    "announcement finish",
                )
            except BaseException:
                device.stop_media()
                raise

    async def stop_announcement(self) -> None:
        self._device.stop_media()

    @property
    def busy(self) -> bool:
        return self._lock.locked()
