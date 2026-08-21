from __future__ import annotations

import json
from io import BytesIO
import struct
import wave

import httpx
import pytest

from andy.providers import KokoroTTS, OpenAIChat, normalize_pcm16_wav


def make_wav(*, sample_rate: int, sample_width: int = 2) -> bytes:
    frame_count = sample_rate // 20
    if sample_width == 2:
        frames = b"".join(
            struct.pack("<h", (index % 200) - 100)
            for index in range(frame_count)
        )
    else:
        frames = bytes(index % 256 for index in range(frame_count))

    output = BytesIO()
    with wave.open(output, "wb") as destination:
        destination.setnchannels(1)
        destination.setsampwidth(sample_width)
        destination.setframerate(sample_rate)
        destination.writeframes(frames)
    return output.getvalue()


def wav_properties(data: bytes) -> tuple[int, int, int, int]:
    with wave.open(BytesIO(data), "rb") as source:
        return (
            source.getframerate(),
            source.getnchannels(),
            source.getsampwidth(),
            source.getnframes(),
        )


def test_normalize_pcm16_wav_resamples_24khz_to_48khz() -> None:
    source = make_wav(sample_rate=24_000)

    normalized = normalize_pcm16_wav(source, 48_000)

    sample_rate, channels, sample_width, frame_count = wav_properties(normalized)
    assert sample_rate == 48_000
    assert channels == 1
    assert sample_width == 2
    assert frame_count == pytest.approx(2_400, abs=1)


def test_normalize_pcm16_wav_preserves_native_format() -> None:
    source = make_wav(sample_rate=48_000)

    assert normalize_pcm16_wav(source, 48_000) == source


def test_normalize_pcm16_wav_rejects_non_pcm16_audio() -> None:
    with pytest.raises(RuntimeError, match="16-bit PCM"):
        normalize_pcm16_wav(make_wav(sample_rate=24_000, sample_width=1), 48_000)


@pytest.mark.asyncio
async def test_kokoro_tts_preserves_native_24khz_pcm() -> None:
    source = make_wav(sample_rate=24_000)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/audio/speech"
        return httpx.Response(200, content=source)

    provider = KokoroTTS("https://example.test")
    await provider._client.aclose()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        assert await provider.synthesize("Hello") == source
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_openai_chat_health_requires_configured_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={"data": [{"id": "glm-5.2"}, {"id": "other-model"}]},
        )

    provider = OpenAIChat("https://example.test/v1", "glm-5.2", "test-key")
    await provider._client.aclose()
    provider._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer test-key"},
    )
    try:
        assert await provider.health() is True
    finally:
        await provider.aclose()


@pytest.mark.parametrize(
    ("status_code", "payload"),
    [
        (200, {"data": [{"id": "different-model"}]}),
        (503, {"error": "unavailable"}),
        (200, {"unexpected": []}),
    ],
)
@pytest.mark.asyncio
async def test_openai_chat_health_rejects_unusable_catalog(
    status_code: int, payload: dict[str, object]
) -> None:
    provider = OpenAIChat("https://example.test/v1", "glm-5.2", "")
    await provider._client.aclose()
    provider._client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status_code, json=payload)
        )
    )
    try:
        assert await provider.health() is False
    finally:
        await provider.aclose()


def test_wav_container_wraps_bare_pcm_for_an_upload_api() -> None:
    import wave
    from io import BytesIO

    from andy.providers import wav_container

    pcm = b"\x01\x00" * 1_600
    wav = wav_container(pcm, sample_rate=16_000)
    with wave.open(BytesIO(wav)) as handle:
        assert handle.getframerate() == 16_000
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.readframes(handle.getnframes()) == pcm


@pytest.mark.asyncio
async def test_openai_asr_uploads_a_wav_and_returns_the_text() -> None:
    import httpx

    from andy.providers import OpenAIAudioASR

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content
        return httpx.Response(200, json={"text": "  look to your right  "})

    provider = OpenAIAudioASR(
        "http://recogniser.test", model="tiny.en", language="en"
    )
    provider._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    )

    text = await provider.transcribe(b"\x01\x00" * 8_000)

    assert text == "look to your right"
    assert seen["url"] == "http://recogniser.test/v1/audio/transcriptions"
    body = seen["body"]
    assert isinstance(body, bytes)
    assert b'name="model"' in body and b"tiny.en" in body
    assert b'name="language"' in body
    assert b"RIFF" in body


@pytest.mark.asyncio
async def test_openai_asr_does_not_invent_words_for_a_sliver_of_audio() -> None:
    import httpx

    from andy.providers import OpenAIAudioASR

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("a tenth of a second must not reach the model")

    provider = OpenAIAudioASR("http://recogniser.test", model="tiny.en")
    provider._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    )
    assert await provider.transcribe(b"\x00" * 100) == ""


@pytest.mark.asyncio
async def test_openai_asr_health_requires_the_configured_model() -> None:
    import httpx

    from andy.providers import OpenAIAudioASR

    def present(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "tiny.en"}]})

    def absent(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "something-else"}]})

    for handler, expected in ((present, True), (absent, False)):
        provider = OpenAIAudioASR("http://recogniser.test", model="tiny.en")
        provider._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        )
        assert await provider.health() is expected


def test_openai_asr_refuses_to_be_built_without_a_model() -> None:
    from andy.providers import OpenAIAudioASR

    with pytest.raises(ValueError, match="model"):
        OpenAIAudioASR("http://recogniser.test", model="")


@pytest.mark.asyncio
async def test_azure_dialect_sends_what_azure_accepts() -> None:
    """Azure rejects `max_tokens` and any temperature, and enforces a schema.

    Every one of these is a hard 400 rather than a degraded answer, so the
    payload is asserted rather than trusted.
    """
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"kind":"chat"}'}}]},
        )

    schema = {"type": "object", "properties": {"kind": {"type": "string"}}}
    provider = OpenAIChat(
        "https://example.test/openai/v1",
        "gpt-5.6-luna",
        "key",
        api="azure",
        json_schema=schema,
    )
    await provider._client.aclose()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        assert await provider.complete([{"role": "user", "content": "hi"}])
    finally:
        await provider.aclose()

    assert seen["max_completion_tokens"] == 192
    assert "max_tokens" not in seen
    assert "temperature" not in seen
    assert seen["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "decision", "strict": True, "schema": schema},
    }


@pytest.mark.asyncio
async def test_ollama_dialect_omits_a_schema_it_would_ignore() -> None:
    """Ollama Cloud does not support structured outputs, so none is claimed.

    Sending one would be accepted and silently dropped, which reads in the
    payload like a guarantee that is not there.
    """
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "hello"}}]}
        )

    provider = OpenAIChat(
        "https://example.test/v1",
        "glm-5.2",
        "key",
        api="ollama",
        json_schema={"type": "object"},
    )
    await provider._client.aclose()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        assert await provider.complete([{"role": "user", "content": "hi"}]) == "hello"
    finally:
        await provider.aclose()

    assert seen["max_tokens"] == 192
    assert "max_completion_tokens" not in seen
    assert "response_format" not in seen
    assert "temperature" not in seen
