"""What the agent may do to Andy's body, beyond moving his head.

The discipline is the one `MotionAction` already established: the model picks a
name from a closed set or nothing happens. It never supplies a colour, an angle,
a brightness, a duration, an entity id, or a raw frame. Everything here resolves
to a firmware entity that validates the request again on the device.

The emotion vocabulary is not duplicated here. It is read from the device's own
`Emotion` select at bind time, so the firmware table stays the single source of
truth and the two can never drift.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
import logging

from .device import DeviceState

log = logging.getLogger("andy.effects")

#: How fast Andy speaks when he feels something, as a multiple of his ordinary
#: pace. Pace is the one part of prosody this synthesiser exposes, and it is a
#: real carrier of feeling: people speed up when delighted and slow down when
#: tired or sad. It is not full emotional synthesis and does not pretend to be.
#:
#: The band is measured rather than chosen. The same sentence round-tripped
#: through Andy's own recogniser transcribes perfectly from 0.7 to 1.25, and at
#: 1.4 his name comes back as "Endi" -- which is the word the gate uses to
#: decide whether it was spoken to at all. 0.8 to 1.2 keeps margin on the side
#: that fails first.
QUICKENED = frozenset({
    "joyful", "laughing", "gleeful", "delighted", "surprised", "shocked",
    "playful", "mischievous", "furious", "angry", "distressed", "anguished",
    "wailing", "flustered", "overwhelmed",
})
SLOWED = frozenset({
    "sleepy", "yawning", "sad", "unhappy", "disappointed", "pained",
    "unwell", "blank", "deadpan", "content",
})
MAX_PACE_SHIFT = 0.2


def speech_pace(emotion: str | None, intensity: int = 75) -> float:
    """How fast to say something that is felt this way."""
    name = (emotion or "").strip().casefold()
    if name in QUICKENED:
        direction = 1.0
    elif name in SLOWED:
        direction = -1.0
    else:
        return 1.0
    strength = max(0, min(100, intensity)) / 100.0
    return round(1.0 + direction * MAX_PACE_SHIFT * strength, 3)

EMOTION_SELECT = "emotion"
EMOTION_INTENSITY = "emotion_intensity"
EXPRESS_BUTTON = "emotion_express"
#: Long enough for one tunnel round trip and the firmware's own guard.
IDIOM_CLAIM_TIMEOUT = 2.5
RESET_BUTTON = "emotion_reset"


class AttentionAction(StrEnum):
    """Whether Andy is listening. The tap on his screen does the same thing."""

    SLEEP = "sleep"
    WAKE = "wake"


ATTENTION_BUTTONS: dict[AttentionAction, str] = {
    AttentionAction.SLEEP: "conversation_sleep",
    AttentionAction.WAKE: "conversation_follow_up",
}


#: What Andy wears when a movement is asked for directly. The gate answers
#: those without ever reaching the agent, so without this a spoken "dance for
#: me" moved the body and left the face exactly as it was.
MOTION_FEELINGS: dict[str, str] = {
    "home": "neutral",
    "look_left": "puzzled",
    "look_right": "puzzled",
    "look_up": "surprised",
    "nod_yes": "happy",
    "shake_no": "unimpressed",
    "bow": "content",
    "greet": "joyful",
    "celebrate": "delighted",
    "scan": "puzzled",
    "dance": "delighted",
    "yaw_positive_10": "neutral",
    "pitch_positive_10": "neutral",
}


@dataclass(frozen=True, slots=True)
class EmotionRequest:
    """A mood, an optional strength, and whether to move the body for it."""

    emotion: str
    intensity: int | None = None
    express: bool = False


class EffectController:
    """Applies allowlisted effects, refusing anything the device does not offer."""

    def __init__(self, device: DeviceState, *, enabled: bool = True) -> None:
        self._device = device
        self._enabled = enabled
        self._applied = 0
        self._rejected = 0
        self._last: str = ""

    @property
    def emotions(self) -> tuple[str, ...]:
        """The vocabulary, straight from the firmware."""
        return self._device.select_options(EMOTION_SELECT)

    def available(self) -> bool:
        return self._enabled and self._device.connected and bool(self.emotions)

    async def set_emotion(self, request: EmotionRequest) -> str:
        if not self._enabled:
            self._rejected += 1
            raise RuntimeError("effects are disabled")
        vocabulary = self.emotions
        if not vocabulary:
            self._rejected += 1
            raise RuntimeError("device exposes no emotion vocabulary")
        name = request.emotion.strip().casefold()
        if name not in vocabulary:
            self._rejected += 1
            log.warning("rejected emotion outside the device vocabulary: %r", name)
            raise ValueError(f"unknown emotion: {request.emotion!r}")

        if request.intensity is not None:
            self._device.set_number(
                EMOTION_INTENSITY, max(0, min(100, request.intensity))
            )
        self._device.select_option(EMOTION_SELECT, name)
        if request.express and self._device.has_button(EXPRESS_BUTTON):
            # The face and ring change immediately; the body only moves when
            # asked, because a servo program is not free.
            self._device.press(EXPRESS_BUTTON)
            # Then wait for the device to say it has actually taken the
            # mechanism. Andy is a WireGuard round trip away, so a state the
            # server just caused is not a state the server can yet read, and
            # anything that starts a movement next would collide with this one.
            # A `still` idiom never claims it, which is why this is a timeout
            # rather than an error.
            try:
                await self._device.wait_for(
                    lambda: self._device.get("motion_program") is True,
                    IDIOM_CLAIM_TIMEOUT,
                    "idiom to claim the mechanism",
                )
            except (TimeoutError, RuntimeError):
                log.debug("no idiom started for %s", name)
        self._applied += 1
        self._last = f"{name}{' expressed' if request.express else ''}"
        log.info("emotion applied: %s", self._last)
        return self._last

    async def express(self) -> str:
        """Replay the current mood through the body without changing it."""
        if not self._enabled or not self._device.has_button(EXPRESS_BUTTON):
            self._rejected += 1
            raise RuntimeError("expression is unavailable")
        self._device.press(EXPRESS_BUTTON)
        try:
            await self._device.wait_for(
                lambda: self._device.get("motion_program") is True,
                IDIOM_CLAIM_TIMEOUT,
                "idiom to claim the mechanism",
            )
        except (TimeoutError, RuntimeError):
            log.debug("no idiom started")
        self._applied += 1
        self._last = "expressed"
        return self._last

    def reset_emotion(self) -> str:
        if not self._device.has_button(RESET_BUTTON):
            raise RuntimeError("emotion reset is unavailable")
        self._device.press(RESET_BUTTON)
        self._applied += 1
        self._last = "reset"
        return self._last

    def attention(self, action: AttentionAction) -> str:
        self._device.press(ATTENTION_BUTTONS[action])
        self._applied += 1
        self._last = action.value
        return self._last

    async def wear_for_motion(self, action: str) -> str | None:
        """Put on the face that goes with a movement the gate authorised."""
        feeling = MOTION_FEELINGS.get(action)
        if feeling is None or feeling not in self.emotions:
            return None
        try:
            return await self.set_emotion(
                EmotionRequest(emotion=feeling, intensity=80)
            )
        except Exception:
            log.debug("could not wear %s for %s", feeling, action, exc_info=True)
            return None

    def snapshot(self) -> dict[str, object]:
        return {
            "enabled": self._enabled,
            "available": self.available(),
            "emotions": list(self.emotions),
            "applied": self._applied,
            "rejected": self._rejected,
            "last": self._last,
            "current": self._device.get("emotion_state"),
        }
