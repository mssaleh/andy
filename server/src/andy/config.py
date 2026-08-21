from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any
import os
from pathlib import Path
from urllib.parse import urlsplit


def _value(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _boolean(name: str, default: bool) -> bool:
    value = _value(name, "true" if default else "false").lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be true or false")


def _choice(name: str, default: str, *, allowed: tuple[str, ...]) -> str:
    value = _value(name, default).lower()
    if value not in allowed:
        raise RuntimeError(f"{name} must be one of: {', '.join(allowed)}")
    return value


def _mac(name: str, default: str) -> str:
    value = _value(name, default).lower().replace(":", "").replace("-", "")
    if len(value) != 12 or any(character not in "0123456789abcdef" for character in value):
        raise RuntimeError(f"{name} must be a 12-digit MAC address")
    return value


def _number(name: str, default: float, *, low: float, high: float) -> float:
    raw = _value(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number") from exc
    if not low <= value <= high:
        raise RuntimeError(f"{name} must be between {low} and {high}")
    return value


def _port(name: str, default: int) -> int:
    raw = _value(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer port") from exc
    if not 1 <= value <= 65_535:
        raise RuntimeError(f"{name} must be between 1 and 65535")
    return value


def _http_url(name: str, default: str) -> str:
    value = _value(name, default).rstrip("/")
    parsed = urlsplit(value)
    try:
        parsed_port = parsed.port
    except ValueError as exc:
        raise RuntimeError(f"{name} contains an invalid port") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or (parsed_port is not None and not 1 <= parsed_port <= 65_535)
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(
            f"{name} must be an absolute HTTP URL without a query or fragment"
        )
    return value


@dataclass(frozen=True, slots=True)
class MCPServerSpec:
    """One MCP server Andy attaches as an extra toolset.

    Andy is a chatbot with a body, and the interesting tools are rarely the
    ones written here. A connector therefore has to be describable in the same
    terms every other MCP client uses -- a command to run, or a URL to call,
    with credentials -- rather than in the one shape this server happened to
    support first.
    """

    name: str
    transport: str
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    command: str = ""
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)

    def as_config(self) -> dict[str, Any]:
        """This connector in the shape the MCP client library reads."""
        if self.transport == "stdio":
            entry: dict[str, Any] = {"command": self.command}
            if self.args:
                entry["args"] = list(self.args)
            if self.env:
                entry["env"] = dict(self.env)
            return entry
        entry = {"url": self.url}
        if self.headers:
            entry["headers"] = dict(self.headers)
        if self.transport == "sse":
            entry["transport"] = "sse"
        return entry

    def describe(self) -> str:
        """Say what this connects to without ever saying how to authenticate."""
        target = self.url or " ".join([self.command, *self.args]).strip()
        return f"{self.name} ({self.transport}: {target})"


def _mcp_servers(name: str) -> tuple[MCPServerSpec, ...]:
    """Parse the MCP connectors, in the shape every MCP client already uses.

    A value beginning with `{` is a JSON object of named servers, exactly like
    the `mcpServers` block other clients read, so a connector can carry a
    command, arguments, an environment, or a URL with an authorization header.
    Anything else is read as a plain comma-separated list of Streamable HTTP
    URLs, which is all most connectors need and is far easier to write by hand.
    """
    raw = _value(name)
    if not raw:
        return ()
    if not raw.lstrip().startswith("{"):
        return tuple(
            MCPServerSpec(name=url.strip(), transport="http", url=_url(url.strip()))
            for url in raw.split(",")
            if url.strip()
        )
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} is not valid JSON: {exc}") from None
    entries = payload.get("mcpServers", payload)
    if not isinstance(entries, dict):
        raise RuntimeError(f"{name} must be an object of named servers")
    servers: list[MCPServerSpec] = []
    for server_name, entry in entries.items():
        if not isinstance(entry, dict):
            raise RuntimeError(f"{name}: {server_name} must be an object")
        command = str(entry.get("command") or "").strip()
        url = str(entry.get("url") or "").strip()
        if bool(command) == bool(url):
            raise RuntimeError(
                f"{name}: {server_name} needs exactly one of command or url"
            )
        headers = entry.get("headers") or {}
        environment = entry.get("env") or {}
        if not isinstance(headers, dict) or not isinstance(environment, dict):
            raise RuntimeError(f"{name}: {server_name} headers and env must be objects")
        if command:
            servers.append(
                MCPServerSpec(
                    name=str(server_name),
                    transport="stdio",
                    command=command,
                    args=tuple(str(a) for a in entry.get("args") or ()),
                    env={str(k): str(v) for k, v in environment.items()},
                )
            )
            continue
        transport = str(entry.get("transport") or "http").lower()
        if transport not in {"http", "sse"}:
            raise RuntimeError(
                f"{name}: {server_name} transport must be http or sse"
            )
        servers.append(
            MCPServerSpec(
                name=str(server_name),
                transport=transport,
                url=_url(url),
                headers={str(k): str(v) for k, v in headers.items()},
            )
        )
    return tuple(servers)


def _url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise RuntimeError(f"{value!r} is not an absolute HTTP URL")
    return value.rstrip("/")


@dataclass(frozen=True, slots=True)
class Config:
    device_enabled: bool
    device_host: str
    device_port: int
    device_name: str
    device_project: str
    device_mac: str
    device_key: str
    motion_actions_enabled: bool
    media_base_url: str
    asr_url: str
    asr_api: str
    asr_model: str
    asr_language: str
    tts_url: str
    tts_voice: str
    llm_api: str
    llm_url: str
    llm_model: str
    llm_key: str
    llm_reasoning: str
    system_prompt: str
    agent_enabled: bool
    vision_enabled: bool
    vlm_url: str
    vlm_model: str
    owl_url: str
    mcp_servers: tuple[MCPServerSpec, ...]
    state_dir: Path | None
    vad_engine: str
    vad_speech_threshold: float
    vad_min_speech_rms: int
    vad_noise_ratio: float
    session_idle_seconds: float

    @classmethod
    def from_env(cls) -> Config:
        config = cls(
            device_enabled=_boolean("ANDY_DEVICE_ENABLED", True),
            device_host=_value("ANDY_DEVICE_HOST", "10.0.0.2"),
            device_port=_port("ANDY_DEVICE_PORT", 6053),
            device_name=_value("ANDY_DEVICE_NAME", "andy"),
            device_project=_value("ANDY_DEVICE_PROJECT", "andy.voice-agent"),
            device_mac=_mac("ANDY_DEVICE_MAC", "AA:BB:CC:DD:EE:FF"),
            device_key=_value("ANDY_DEVICE_KEY"),
            motion_actions_enabled=_boolean(
                "ANDY_MOTION_ACTIONS_ENABLED", False
            ),
            media_base_url=_http_url(
                "ANDY_MEDIA_BASE_URL", "http://10.0.0.3:8900"
            ),
            asr_url=_http_url("ANDY_ASR_URL", "http://127.0.0.1:8881"),
            asr_api=_choice(
                "ANDY_ASR_API", "andy", allowed=("andy", "openai")
            ),
            asr_model=_value("ANDY_ASR_MODEL"),
            asr_language=_value("ANDY_ASR_LANGUAGE", "en"),
            tts_url=_http_url("ANDY_TTS_URL", "http://127.0.0.1:8880"),
            tts_voice=_value("ANDY_TTS_VOICE", "af_heart"),
            llm_api=_choice(
                "ANDY_LLM_API", "ollama", allowed=("ollama", "azure")
            ),
            llm_url=_http_url("ANDY_LLM_URL", "https://ollama.com/v1"),
            llm_model=_value("ANDY_LLM_MODEL", "glm-5.2"),
            llm_key=_value("ANDY_LLM_API_KEY"),
            llm_reasoning=_value("ANDY_LLM_REASONING", "none"),
            agent_enabled=_boolean("ANDY_AGENT_ENABLED", True),
            vision_enabled=_boolean("ANDY_VISION_ENABLED", False),
            vlm_url=_http_url("ANDY_VLM_URL", "https://ollama.com/v1"),
            vlm_model=_value("ANDY_VLM_MODEL", "qwen3-vl:8b"),
            # Optional: with no detector configured Andy can still describe
            # what he sees, he just cannot be asked about a named thing.
            owl_url=(
                _http_url("ANDY_OWL_URL", "") if _value("ANDY_OWL_URL") else ""
            ),
            state_dir=(
                Path(_value("ANDY_STATE_DIR")) if _value("ANDY_STATE_DIR") else None
            ),
            vad_engine=_choice(
                "ANDY_VAD_ENGINE", "silero", allowed=("silero", "webrtc")
            ),
            vad_speech_threshold=_number(
                "ANDY_VAD_SPEECH_THRESHOLD", 0.5, low=0.05, high=0.95
            ),
            vad_min_speech_rms=int(
                _number("ANDY_VAD_MIN_SPEECH_RMS", 60, low=0, high=8_000)
            ),
            vad_noise_ratio=_number(
                "ANDY_VAD_NOISE_RATIO", 1.2, low=1.0, high=10.0
            ),
            session_idle_seconds=_number(
                "ANDY_SESSION_IDLE_SECONDS", 180.0, low=15.0, high=3_600.0
            ),
            mcp_servers=_mcp_servers("ANDY_MCP_SERVERS"),
            system_prompt=_value(
                "ANDY_SYSTEM_PROMPT",
                (
                    "You are Andy, a small friendly moving desk robot. "
                    "Answer naturally in one or two short sentences suitable for speech."
                ),
            ),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.asr_api == "openai" and not self.asr_model:
            raise RuntimeError(
                "ANDY_ASR_API=openai requires a non-empty ANDY_ASR_MODEL"
            )
        if self.motion_actions_enabled and not self.device_enabled:
            raise RuntimeError(
                "ANDY_MOTION_ACTIONS_ENABLED requires ANDY_DEVICE_ENABLED"
            )
        required = {
            "ANDY_MEDIA_BASE_URL": self.media_base_url,
            "ANDY_ASR_URL": self.asr_url,
            "ANDY_TTS_URL": self.tts_url,
            "ANDY_TTS_VOICE": self.tts_voice,
            "ANDY_LLM_URL": self.llm_url,
            "ANDY_LLM_MODEL": self.llm_model,
            "ANDY_VAD_ENGINE": self.vad_engine,
            "ANDY_SYSTEM_PROMPT": self.system_prompt,
            "ANDY_LLM_API_KEY": self.llm_key,
        }
        if self.device_enabled:
            required.update(
                {
                    "ANDY_DEVICE_HOST": self.device_host,
                    "ANDY_DEVICE_NAME": self.device_name,
                    "ANDY_DEVICE_PROJECT": self.device_project,
                    "ANDY_DEVICE_MAC": self.device_mac,
                    "ANDY_DEVICE_KEY": self.device_key,
                }
            )
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"required environment is unset: {', '.join(missing)}")
