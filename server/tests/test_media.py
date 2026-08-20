from __future__ import annotations

import pytest

from andy.media import AudioStore, MEDIA_CHUNK_BYTES, MediaItem, stream_audio


def test_audio_store_rejects_empty_and_oversized_items() -> None:
    store = AudioStore(max_item_bytes=4)

    with pytest.raises(ValueError, match="empty"):
        store.put(b"")
    with pytest.raises(ValueError, match="size limit"):
        store.put(b"12345")


def test_audio_store_evicts_the_oldest_item_at_capacity() -> None:
    store = AudioStore(max_items=2)
    first = store.put(b"first")
    second = store.put(b"second")
    third = store.put(b"third")

    assert store.get(first) is None
    assert store.get(second) is not None
    assert store.get(third) is not None


@pytest.mark.asyncio
async def test_audio_stream_preserves_bytes_in_bounded_chunks() -> None:
    data = bytes(range(256)) * 9

    chunks = [chunk async for chunk in stream_audio(MediaItem(data, "audio/wav"))]

    assert b"".join(chunks) == data
    assert all(0 < len(chunk) <= MEDIA_CHUNK_BYTES for chunk in chunks)
    assert len(chunks) == 3
