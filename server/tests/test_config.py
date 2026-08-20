from __future__ import annotations

from pathlib import Path

import pytest

from andy.config import Config


def test_disabled_device_bridge_does_not_require_device_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANDY_DEVICE_ENABLED", "false")
    monkeypatch.delenv("ANDY_DEVICE_KEY", raising=False)
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")

    config = Config.from_env()

    assert not config.device_enabled
    assert config.device_key == ""


def test_enabled_device_bridge_requires_device_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANDY_DEVICE_ENABLED", "true")
    monkeypatch.delenv("ANDY_DEVICE_KEY", raising=False)
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")

    with pytest.raises(RuntimeError, match="ANDY_DEVICE_KEY"):
        Config.from_env()


def test_device_bridge_flag_rejects_ambiguous_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANDY_DEVICE_ENABLED", "sometimes")

    with pytest.raises(RuntimeError, match="must be true or false"):
        Config.from_env()


def test_motion_actions_require_the_device_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANDY_DEVICE_ENABLED", "false")
    monkeypatch.setenv("ANDY_MOTION_ACTIONS_ENABLED", "true")
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")

    with pytest.raises(
        RuntimeError, match="ANDY_MOTION_ACTIONS_ENABLED requires"
    ):
        Config.from_env()


def test_media_url_defaults_to_the_wireguard_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANDY_DEVICE_ENABLED", "false")
    monkeypatch.delenv("ANDY_MEDIA_BASE_URL", raising=False)
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")

    config = Config.from_env()

    assert config.media_base_url == "http://10.0.0.3:8900"


@pytest.mark.parametrize("value", ["0", "65536", "not-a-port"])
def test_device_port_must_be_valid(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("ANDY_DEVICE_ENABLED", "false")
    monkeypatch.setenv("ANDY_DEVICE_PORT", value)
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")

    with pytest.raises(RuntimeError, match="ANDY_DEVICE_PORT"):
        Config.from_env()


@pytest.mark.parametrize(
    "value",
    ["192.0.2.20:8900", "ftp://10.0.0.3/", "http://10.0.0.3/?x=1"],
)
def test_media_url_must_be_an_absolute_http_url(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("ANDY_DEVICE_ENABLED", "false")
    monkeypatch.setenv("ANDY_MEDIA_BASE_URL", value)
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")

    with pytest.raises(RuntimeError, match="ANDY_MEDIA_BASE_URL"):
        Config.from_env()


def test_production_environment_example_matches_the_runtime_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    example = (
        Path(__file__).parents[1] / "deploy" / "production.env.example"
    )
    entries = dict(
        line.split("=", 1)
        for line in example.read_text(encoding="utf-8").splitlines()
        if line
    )
    assert tuple(entries) == (
        "ANDY_DEVICE_ENABLED",
        "ANDY_DEVICE_HOST",
        "ANDY_DEVICE_PORT",
        "ANDY_DEVICE_NAME",
        "ANDY_DEVICE_PROJECT",
        "ANDY_DEVICE_MAC",
        "ANDY_DEVICE_KEY",
        "ANDY_MOTION_ACTIONS_ENABLED",
        "ANDY_MEDIA_BASE_URL",
        "ANDY_ASR_URL",
        "ANDY_ASR_API",
        "ANDY_ASR_MODEL",
        "ANDY_ASR_LANGUAGE",
        "ANDY_TTS_URL",
        "ANDY_TTS_VOICE",
        "ANDY_LLM_URL",
        "ANDY_LLM_MODEL",
        "ANDY_LLM_REASONING",
        "ANDY_SYSTEM_PROMPT",
        "ANDY_AGENT_ENABLED",
        "ANDY_VISION_ENABLED",
        "ANDY_VLM_URL",
        "ANDY_VLM_MODEL",
        "ANDY_OWL_URL",
        "ANDY_MCP_SERVERS",
        "ANDY_VAD_ENGINE",
        "ANDY_VAD_SPEECH_THRESHOLD",
        "ANDY_VAD_MIN_SPEECH_RMS",
        "ANDY_VAD_NOISE_RATIO",
        "ANDY_SESSION_IDLE_SECONDS",
        "ANDY_STATE_DIR",
        "OLLAMA_API_KEY",
    )
    assert entries["ANDY_MEDIA_BASE_URL"] == "http://10.0.0.3:8900"

    entries["ANDY_DEVICE_KEY"] = "device-key"
    entries["OLLAMA_API_KEY"] = "model-key"
    for name, value in entries.items():
        monkeypatch.setenv(name, value)

    config = Config.from_env()

    assert config.device_port == 6053
    assert config.media_base_url == "http://10.0.0.3:8900"


def _bridgeless(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANDY_DEVICE_ENABLED", "false")
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")


def test_vad_engine_defaults_to_the_neural_detector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bridgeless(monkeypatch)
    config = Config.from_env()
    assert config.vad_engine == "silero"
    assert config.vad_speech_threshold == 0.5


def test_vad_engine_accepts_only_a_detector_that_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bridgeless(monkeypatch)
    monkeypatch.setenv("ANDY_VAD_ENGINE", "webrtc")
    assert Config.from_env().vad_engine == "webrtc"

    monkeypatch.setenv("ANDY_VAD_ENGINE", "whatever")
    with pytest.raises(RuntimeError, match="ANDY_VAD_ENGINE"):
        Config.from_env()


@pytest.mark.parametrize("value", ["0", "1", "1.5", "-0.2", "high"])
def test_vad_speech_threshold_must_be_a_probability(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    _bridgeless(monkeypatch)
    monkeypatch.setenv("ANDY_VAD_SPEECH_THRESHOLD", value)
    with pytest.raises(RuntimeError, match="ANDY_VAD_SPEECH_THRESHOLD"):
        Config.from_env()


def test_openai_recogniser_requires_a_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bridgeless(monkeypatch)
    monkeypatch.setenv("ANDY_ASR_API", "openai")
    monkeypatch.delenv("ANDY_ASR_MODEL", raising=False)
    with pytest.raises(RuntimeError, match="ANDY_ASR_MODEL"):
        Config.from_env()

    monkeypatch.setenv("ANDY_ASR_MODEL", "Systran/faster-whisper-small")
    assert Config.from_env().asr_model == "Systran/faster-whisper-small"


def test_recogniser_protocol_must_be_one_that_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bridgeless(monkeypatch)
    assert Config.from_env().asr_api == "andy"
    monkeypatch.setenv("ANDY_ASR_API", "grpc")
    with pytest.raises(RuntimeError, match="ANDY_ASR_API"):
        Config.from_env()
