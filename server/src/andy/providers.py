from __future__ import annotations

from array import array
from io import BytesIO
import sys
import wave

import httpx


def _resample_pcm16(
    frames: bytes,
    *,
    channels: int,
    source_sample_rate: int,
    target_sample_rate: int,
) -> bytes:
    source_samples = array("h")
    source_samples.frombytes(frames)
    if sys.byteorder != "little":
        source_samples.byteswap()

    source_frame_count = len(source_samples) // channels
    if source_frame_count == 0:
        return b""
    target_frame_count = (
        (source_frame_count - 1) * target_sample_rate // source_sample_rate
    ) + 1
    target_samples = array("h")

    for target_frame in range(target_frame_count):
        source_position = target_frame * source_sample_rate
        left_frame = source_position // target_sample_rate
        fraction = source_position % target_sample_rate
        right_frame = min(left_frame + 1, source_frame_count - 1)
        left_weight = target_sample_rate - fraction

        for channel in range(channels):
            left = source_samples[left_frame * channels + channel]
            right = source_samples[right_frame * channels + channel]
            weighted = left * left_weight + right * fraction
            if weighted >= 0:
                sample = (weighted + target_sample_rate // 2) // target_sample_rate
            else:
                sample = -((-weighted + target_sample_rate // 2) // target_sample_rate)
            target_samples.append(sample)

    if sys.byteorder != "little":
        target_samples.byteswap()
    return target_samples.tobytes()


def normalize_pcm16_wav(data: bytes, target_sample_rate: int) -> bytes:
    """Return an uncompressed PCM16 WAV at the requested sample rate."""
    if target_sample_rate <= 0:
        raise ValueError("target sample rate must be positive")

    try:
        with wave.open(BytesIO(data), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            source_sample_rate = source.getframerate()
            compression = source.getcomptype()
            frames = source.readframes(source.getnframes())
    except (EOFError, wave.Error) as exc:
        raise RuntimeError("TTS provider returned an invalid WAV") from exc

    if channels not in (1, 2):
        raise RuntimeError(f"TTS WAV has unsupported channel count: {channels}")
    if sample_width != 2 or compression != "NONE":
        raise RuntimeError("TTS WAV must be uncompressed 16-bit PCM")
    if source_sample_rate <= 0:
        raise RuntimeError("TTS WAV has an invalid sample rate")
    if source_sample_rate == target_sample_rate:
        return data

    converted = _resample_pcm16(
        frames,
        channels=channels,
        source_sample_rate=source_sample_rate,
        target_sample_rate=target_sample_rate,
    )
    output = BytesIO()
    with wave.open(output, "wb") as destination:
        destination.setnchannels(channels)
        destination.setsampwidth(sample_width)
        destination.setframerate(target_sample_rate)
        destination.writeframes(converted)
    return output.getvalue()


def wav_container(pcm16: bytes, *, sample_rate: int, channels: int = 1) -> bytes:
    """Wrap bare PCM16 in a RIFF header, which is what an upload API expects."""
    output = BytesIO()
    with wave.open(output, "wb") as destination:
        destination.setnchannels(channels)
        destination.setsampwidth(2)
        destination.setframerate(sample_rate)
        destination.writeframes(pcm16)
    return output.getvalue()


class WhisperASR:
    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)

    async def transcribe(self, pcm16_16k: bytes) -> str:
        if len(pcm16_16k) < 3_200:
            return ""
        response = await self._client.post(
            f"{self._base_url}/transcribe",
            content=pcm16_16k,
            headers={"Content-Type": "application/octet-stream"},
        )
        response.raise_for_status()
        return str(response.json().get("text") or "").strip()

    async def health(self) -> bool:
        try:
            response = await self._client.get(
                f"{self._base_url}/health", timeout=5.0
            )
            return response.status_code == 200 and bool(response.json().get("ok"))
        except (httpx.HTTPError, ValueError):
            return False

    async def aclose(self) -> None:
        await self._client.aclose()


class OpenAIAudioASR:
    """Recognition over the OpenAI audio API, so the recogniser is a choice.

    Andy's first recogniser speaks a private protocol -- raw PCM16 in, one JSON
    object out -- because the image it wraps ships no server and had to be
    given one. Nothing else speaks that protocol, which makes the recogniser a
    code change rather than a deployment one.

    This speaks the shape everything else already does. Any server offering
    `/v1/audio/transcriptions` fits behind it, so which model recognises Andy's
    speech, and whether it is English-only, is decided by configuration and can
    be changed back.
    """

    def __init__(
        self,
        base_url: str,
        *,
        model: str,
        language: str = "en",
        api_key: str = "",
        sample_rate: int = 16_000,
        timeout: float = 30.0,
    ) -> None:
        if not model:
            raise ValueError("an OpenAI-compatible recogniser needs a model")
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._language = language
        self._sample_rate = sample_rate
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(timeout=timeout, headers=headers)

    async def transcribe(self, pcm16_16k: bytes) -> str:
        # A tenth of a second cannot carry a word, and a recogniser handed one
        # answers with an invention rather than an empty string.
        if len(pcm16_16k) < 3_200:
            return ""
        wav = wav_container(pcm16_16k, sample_rate=self._sample_rate)
        data = {"model": self._model, "response_format": "json"}
        if self._language:
            data["language"] = self._language
        response = await self._client.post(
            f"{self._base_url}/v1/audio/transcriptions",
            files={"file": ("utterance.wav", wav, "audio/wav")},
            data=data,
        )
        response.raise_for_status()
        return str(response.json().get("text") or "").strip()

    async def health(self) -> bool:
        """The configured model has to be present, not merely the server.

        A recogniser that is running but cannot load the model Andy asks for
        fails on the first utterance instead of at startup, which is the point
        at which nobody is watching.
        """
        try:
            response = await self._client.get(
                f"{self._base_url}/v1/models", timeout=5.0
            )
            if response.status_code != 200:
                return False
            models = response.json().get("data")
            return isinstance(models, list) and any(
                isinstance(model, dict) and model.get("id") == self._model
                for model in models
            )
        except (httpx.HTTPError, ValueError):
            return False

    async def aclose(self) -> None:
        await self._client.aclose()


class OpenAIChat:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        *,
        reasoning_effort: str = "none",
        max_tokens: int = 192,
        temperature: float = 0.1,
        timeout: float = 45.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._reasoning_effort = reasoning_effort.strip()
        self._max_tokens = max_tokens
        self._temperature = temperature
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(timeout=timeout, headers=headers)

    async def complete(self, messages: list[dict[str, str]]) -> str:
        payload: dict[str, object] = {
            "model": self._model,
            "messages": messages,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "stream": False,
        }
        if self._reasoning_effort:
            payload["reasoning_effort"] = self._reasoning_effort
        response = await self._client.post(
            f"{self._base_url}/chat/completions", json=payload
        )
        response.raise_for_status()
        data = response.json()
        if data.get("error"):
            raise RuntimeError(str(data["error"])[:300])
        text = str(data["choices"][0]["message"].get("content") or "").strip()
        if not text:
            raise RuntimeError(f"model {self._model!r} returned no spoken response")
        return text

    async def health(self) -> bool:
        try:
            response = await self._client.get(
                f"{self._base_url}/models", timeout=5.0
            )
            if response.status_code != 200:
                return False
            models = response.json().get("data")
            return isinstance(models, list) and any(
                isinstance(model, dict) and model.get("id") == self._model
                for model in models
            )
        except (httpx.HTTPError, ValueError):
            return False

    async def aclose(self) -> None:
        await self._client.aclose()


class KokoroTTS:
    def __init__(
        self,
        base_url: str,
        *,
        voice: str = "af_heart",
        target_sample_rate: int = 24_000,
        timeout: float = 30.0,
    ) -> None:
        if target_sample_rate <= 0:
            raise ValueError("target sample rate must be positive")
        self._base_url = base_url.rstrip("/")
        self._voice = voice
        self._target_sample_rate = target_sample_rate
        self._client = httpx.AsyncClient(timeout=timeout)

    async def synthesize(self, text: str, *, pace: float = 1.0) -> bytes:
        text = text.strip()
        if not text:
            return b""
        # Clamped here rather than trusted from the caller: the recogniser
        # starts mishearing Andy's own name above this, and his name is how the
        # gate decides whether it was spoken to.
        speed = max(0.8, min(1.2, float(pace)))
        response = await self._client.post(
            f"{self._base_url}/v1/audio/speech",
            json={
                "model": "kokoro",
                "input": text,
                "voice": self._voice,
                "response_format": "wav",
                "speed": speed,
            },
        )
        response.raise_for_status()
        return normalize_pcm16_wav(response.content, self._target_sample_rate)

    async def health(self) -> bool:
        try:
            response = await self._client.get(
                f"{self._base_url}/health", timeout=5.0
            )
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def aclose(self) -> None:
        await self._client.aclose()
