"""Looking through Andy's eye.

A frame reaches the server over the same encrypted session as everything else,
and over the same 243 ms tunnel, so a photograph is expensive by desk-robot
standards. Nothing polls it.

What is cached is therefore the frame, not the answer. Two questions about the
same moment -- "what can you see" and "is my cup there" -- are two questions
about one photograph, and taking a second one to answer the second question
would double the only cost that matters while describing a room that has not
changed.

Two ways of looking share that frame:

- `describe` asks a vision-language model for a sentence. It is open-ended and
  slow, and it is what someone means by "what can you see?".
- `find` asks an open-vocabulary detector for specific things by name. It is
  local, quick, and answers "is there a person" or "where are my keys" without
  leaving the machine.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time

import httpx
from aioesphomeapi import APIClient, CameraState

log = logging.getLogger("andy.vision")

FRAME_TIMEOUT = 20.0
#: How long a photograph still describes the room. Long enough that a follow-up
#: question in the same breath reuses it, short enough that it is not stale.
FRAME_CACHE_SECONDS = 5.0
DESCRIPTION_CACHE_SECONDS = 20.0
#: A detector is given phrases, not a sentence. These bound what one question
#: may cost; they are not a safety boundary, because looking moves nothing.
MAX_PHRASES = 8
MAX_PHRASE_CHARS = 60


class VisionProvider:
    """Grabs one frame on demand and answers questions about it."""

    def __init__(
        self,
        client: APIClient,
        *,
        base_url: str,
        model: str,
        api_key: str,
        detector_url: str = "",
        timeout: float = 60.0,
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._detector_url = detector_url.rstrip("/")
        self._http = httpx.AsyncClient(
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        )
        self._lock = asyncio.Lock()
        self._frame: tuple[float, bytes] | None = None
        self._described: tuple[float, str] | None = None
        self.frames_taken = 0
        self.frames_reused = 0

    @property
    def can_find(self) -> bool:
        return bool(self._detector_url)

    async def frame(self) -> bytes:
        """One JPEG from the device, requested rather than streamed."""
        loop = asyncio.get_running_loop()
        received: asyncio.Future[bytes] = loop.create_future()

        def on_state(state: object) -> None:
            if (
                isinstance(state, CameraState)
                and state.data
                and not received.done()
            ):
                received.set_result(bytes(state.data))

        self._client.subscribe_states(on_state)
        self._client.request_single_image()
        return await asyncio.wait_for(received, timeout=FRAME_TIMEOUT)

    async def _recent_frame(self) -> bytes:
        now = time.monotonic()
        cached = self._frame
        if cached is not None and now - cached[0] < FRAME_CACHE_SECONDS:
            self.frames_reused += 1
            return cached[1]
        image = await self.frame()
        self.frames_taken += 1
        self._frame = (now, image)
        log.info("photographed the room: %d bytes", len(image))
        return image

    async def describe(self) -> str:
        async with self._lock:
            now = time.monotonic()
            if (
                self._described is not None
                and now - self._described[0] < DESCRIPTION_CACHE_SECONDS
            ):
                return self._described[1]
            try:
                image = await self._recent_frame()
            except (TimeoutError, asyncio.TimeoutError):
                return "Andy's camera did not return a picture in time."
            encoded = base64.b64encode(image).decode("ascii")
            response = await self._http.post(
                f"{self._base_url}/chat/completions",
                json={
                    "model": self._model,
                    "max_tokens": 160,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": (
                                        "You are the eye of a small desk robot. "
                                        "Say what is in front of you in one or "
                                        "two short spoken sentences. Mention "
                                        "people first if any are visible."
                                    ),
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{encoded}"
                                    },
                                },
                            ],
                        }
                    ],
                },
            )
            response.raise_for_status()
            data = response.json()
            text = str(data["choices"][0]["message"].get("content") or "").strip()
            if not text:
                return "Andy could not make sense of what he saw."
            self._described = (now, text)
            log.info("described a frame of %d bytes", len(image))
            return text

    async def find(self, phrases: list[str]) -> list[dict[str, object]]:
        """Look for named things in the current frame.

        Returns one entry per thing that was actually found, so an empty list
        is a real answer -- "no, there is nobody here" -- rather than a failure.
        """
        if not self.can_find:
            raise RuntimeError("Andy has no object detector configured")
        wanted = [
            phrase.strip()[:MAX_PHRASE_CHARS]
            for phrase in phrases
            if phrase and phrase.strip()
        ][:MAX_PHRASES]
        if not wanted:
            raise ValueError("name at least one thing to look for")
        async with self._lock:
            try:
                image = await self._recent_frame()
            except (TimeoutError, asyncio.TimeoutError) as exc:
                raise RuntimeError(
                    "Andy's camera did not return a picture in time"
                ) from exc
            # JSON rather than multipart: the detector runs in a container on
            # the same machine as this process, so the base64 is free, and the
            # container has no web framework to parse a multipart body with.
            response = await self._http.post(
                f"{self._detector_url}/detect",
                json={
                    "image_base64": base64.b64encode(image).decode("ascii"),
                    "phrases": wanted,
                },
            )
            response.raise_for_status()
            found = response.json().get("found") or []
            log.info(
                "looked for %s and found %d", ", ".join(wanted), len(found)
            )
            return list(found)

    async def detector_ready(self) -> bool:
        if not self.can_find:
            return False
        try:
            response = await self._http.get(
                f"{self._detector_url}/health", timeout=5.0
            )
            return response.status_code == 200 and bool(
                response.json().get("ok")
            )
        except (httpx.HTTPError, ValueError):
            return False

    def snapshot(self) -> dict[str, object]:
        return {
            "frames_taken": self.frames_taken,
            "frames_reused": self.frames_reused,
            "can_find": self.can_find,
        }

    async def aclose(self) -> None:
        await self._http.aclose()
