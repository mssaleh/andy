from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
import time
import uuid


MEDIA_CHUNK_BYTES = 1024
MEDIA_HEADER_FLUSH_SECONDS = 0.02


@dataclass(frozen=True, slots=True)
class MediaItem:
    data: bytes
    content_type: str


class AudioStore:
    def __init__(
        self,
        *,
        max_items: int = 16,
        ttl_seconds: float = 300.0,
        max_item_bytes: int = 4 * 1024 * 1024,
    ) -> None:
        if max_items < 1 or ttl_seconds <= 0 or max_item_bytes < 1:
            raise ValueError("audio store limits must be positive")
        self._max_items = max_items
        self._ttl_seconds = ttl_seconds
        self._max_item_bytes = max_item_bytes
        self._items: dict[str, tuple[float, MediaItem]] = {}

    def put(self, data: bytes, content_type: str = "audio/wav") -> str:
        if not data:
            raise ValueError("audio item cannot be empty")
        if len(data) > self._max_item_bytes:
            raise ValueError("audio item exceeds the configured size limit")
        self._evict()
        key = uuid.uuid4().hex
        self._items[key] = (time.monotonic(), MediaItem(data, content_type))
        self._evict()
        return key

    def get(self, key: str) -> MediaItem | None:
        self._evict()
        entry = self._items.get(key)
        return entry[1] if entry else None

    def _evict(self) -> None:
        now = time.monotonic()
        expired = [
            key
            for key, (created, _) in self._items.items()
            if now - created > self._ttl_seconds
        ]
        for key in expired:
            self._items.pop(key, None)
        while len(self._items) > self._max_items:
            oldest = min(self._items, key=lambda key: self._items[key][0])
            self._items.pop(oldest, None)


async def stream_audio(item: MediaItem) -> AsyncIterator[bytes]:
    """Yield media in tunnel-safe TCP writes while preserving its exact bytes.

    Writes stay at one tunnel segment so the datagrams never fragment, but they
    are not rate limited. Andy reaches the server only over WireGuard, which
    hairpins through the cloud router at a measured 243 ms round trip, and
    playback consumes 48,000 B/s. Any artificial pacing near that rate starves
    the speaker as soon as the device buffer drains, because a sleep is a floor
    and socket drain on a link that long pushes the real interval past it. TCP
    is the rate controller; the socket's unsent-data limit is the backpressure.
    """
    await asyncio.sleep(MEDIA_HEADER_FLUSH_SECONDS)
    for offset in range(0, len(item.data), MEDIA_CHUNK_BYTES):
        yield item.data[offset : offset + MEDIA_CHUNK_BYTES]
        # Yield to the event loop without capping throughput.
        await asyncio.sleep(0)
