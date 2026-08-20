from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class EventKind(StrEnum):
    RUN_START = "run_start"
    STT_START = "stt_start"
    STT_VAD_START = "stt_vad_start"
    STT_VAD_END = "stt_vad_end"
    STT_END = "stt_end"
    INTENT_START = "intent_start"
    INTENT_END = "intent_end"
    TTS_START = "tts_start"
    TTS_END = "tts_end"
    ERROR = "error"
    RUN_END = "run_end"


@dataclass(frozen=True, slots=True)
class DeviceEvent:
    kind: EventKind
    data: dict[str, str] = field(default_factory=dict)


class EventSink(Protocol):
    def emit(self, event: DeviceEvent) -> None: ...

