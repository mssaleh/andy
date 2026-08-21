from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
import json
import logging
import re
from typing import Protocol


log = logging.getLogger("andy.actions")
MAX_REPLY_CHARS = 500


class MotionAction(StrEnum):
    HOME = "home"
    LOOK_LEFT = "look_left"
    LOOK_RIGHT = "look_right"
    LOOK_UP = "look_up"
    NOD_YES = "nod_yes"
    SHAKE_NO = "shake_no"
    BOW = "bow"
    GREET = "greet"
    CELEBRATE = "celebrate"
    SCAN = "scan"
    DANCE = "dance"
    YAW_POSITIVE_10 = "yaw_positive_10"
    PITCH_POSITIVE_10 = "pitch_positive_10"


class DecisionKind(StrEnum):
    IGNORE = "ignore"
    WAIT = "wait"
    CONTEXT_END = "context_end"
    CHAT = "chat"
    MOTION = "motion"
    REJECTED_MOTION = "rejected_motion"
    SESSION_END = "session_end"


CANONICAL_REQUESTS: dict[MotionAction, str] = {
    MotionAction.HOME: "Return your head to the calibrated home position.",
    MotionAction.LOOK_LEFT: "Look left.",
    MotionAction.LOOK_RIGHT: "Look right.",
    MotionAction.LOOK_UP: "Look up.",
    MotionAction.NOD_YES: "Nod your head yes.",
    MotionAction.SHAKE_NO: "Shake your head no.",
    MotionAction.BOW: "Take a bow.",
    MotionAction.GREET: "Greet me.",
    MotionAction.CELEBRATE: "Celebrate.",
    MotionAction.SCAN: "Scan the room.",
    MotionAction.DANCE: "Dance for me.",
    MotionAction.YAW_POSITIVE_10: "Move yaw positive by ten degrees.",
    MotionAction.PITCH_POSITIVE_10: "Move pitch positive by ten degrees.",
}


@dataclass(frozen=True, slots=True)
class ActionDecision:
    kind: DecisionKind
    action: MotionAction | None = None
    reply: str | None = None


MOTION_DESCRIPTIONS: dict[MotionAction, str] = {
    MotionAction.HOME: "return the head to its calibrated centered home pose",
    MotionAction.LOOK_LEFT: (
        "look exactly 30 degrees left, hold briefly, then return home"
    ),
    MotionAction.LOOK_RIGHT: (
        "look exactly 30 degrees right, hold briefly, then return home"
    ),
    MotionAction.LOOK_UP: (
        "look exactly 30 degrees up, hold briefly, then return home"
    ),
    MotionAction.NOD_YES: "perform a yes nod and return home",
    MotionAction.SHAKE_NO: "perform a no head shake and return home",
    MotionAction.BOW: "bow the head and return home",
    MotionAction.GREET: "perform Andy's four-pose greeting and return home",
    MotionAction.CELEBRATE: (
        "perform Andy's five-pose celebration and return home"
    ),
    MotionAction.SCAN: "scan left, right, and up, returning home",
    MotionAction.DANCE: "perform Andy's eight-pose dance and return home",
    MotionAction.YAW_POSITIVE_10: (
        "diagnostic: move yaw to exactly positive 10 degrees"
    ),
    MotionAction.PITCH_POSITIVE_10: (
        "diagnostic: move pitch to exactly positive 10 degrees"
    ),
}


def motion_catalog_prompt() -> str:
    """Render the semantic catalog supplied to the conversational model."""
    return "\n".join(
        f"- {action.value}: {MOTION_DESCRIPTIONS[action]}"
        for action in MotionAction
    )


_DIRECT_REQUESTS: dict[str, MotionAction] = {}


def _register_direct_requests(
    action: MotionAction, *requests: str
) -> None:
    for request in requests:
        existing = _DIRECT_REQUESTS.setdefault(request, action)
        if existing is not action:
            raise RuntimeError(f"ambiguous direct motion request: {request}")


_register_direct_requests(
    MotionAction.HOME,
    "return your head to the calibrated home position",
    "return your head home",
    "move your head home",
    "return home",
    "go home",
    "center your head",
    "centre your head",
)
_register_direct_requests(
    MotionAction.LOOK_LEFT,
    "look left",
    "look to the left",
    "turn your head left",
    "turn your head to the left",
    "look left 30 degrees",
    "look 30 degrees left",
    "look 30 degrees to the left",
    "look to the left by 30 degrees",
    "turn your head left by 30 degrees",
    "turn your head to the left by 30 degrees",
    "turn your head 30 degrees left",
    "turn your head 30 degrees to the left",
)
_register_direct_requests(
    MotionAction.LOOK_RIGHT,
    "look right",
    "look to the right",
    "turn your head right",
    "turn your head to the right",
    "look right 30 degrees",
    "look 30 degrees right",
    "look 30 degrees to the right",
    "look to the right by 30 degrees",
    "turn your head right by 30 degrees",
    "turn your head to the right by 30 degrees",
    "turn your head 30 degrees right",
    "turn your head 30 degrees to the right",
)
_register_direct_requests(
    MotionAction.LOOK_UP,
    "look up",
    "tilt your head up",
    "look up 30 degrees",
    "look up by 30 degrees",
    "tilt your head up 30 degrees",
    "tilt your head up by 30 degrees",
)
_register_direct_requests(
    MotionAction.NOD_YES,
    "nod",
    "nod yes",
    "nod your head",
    "nod your head yes",
    "say yes with your head",
)
_register_direct_requests(
    MotionAction.SHAKE_NO,
    "shake no",
    "shake your head",
    "shake your head no",
    "say no with your head",
)
_register_direct_requests(MotionAction.BOW, "bow", "take a bow")
_register_direct_requests(
    MotionAction.GREET,
    "greet me",
    "do your greeting",
    "show me your greeting",
)
_register_direct_requests(
    MotionAction.CELEBRATE,
    "celebrate",
    "do your celebration",
    "show me your celebration",
)
_register_direct_requests(
    MotionAction.SCAN,
    "scan",
    "scan the room",
    "look around",
)
_register_direct_requests(
    MotionAction.DANCE,
    "dance",
    "dance for me",
    "do a dance",
    "do your dance",
    "show me a dance",
)
_register_direct_requests(
    MotionAction.YAW_POSITIVE_10,
    "move yaw positive by 10 degrees",
    "move yaw positive 10 degrees",
    "move your yaw positive by 10 degrees",
)
_register_direct_requests(
    MotionAction.PITCH_POSITIVE_10,
    "move pitch positive by 10 degrees",
    "move pitch positive 10 degrees",
    "move your pitch positive by 10 degrees",
)

_REQUEST_PREFIXES = (
    "andy ",
    "please ",
    "can you ",
    "could you ",
    "would you ",
    "will you ",
    "i want you to ",
    "i need you to ",
    "i would like you to ",
    "id like you to ",
)
_REQUEST_SUFFIXES = (" please", " for me", " now")
_ANGLE_TOKEN = (
    r"(?:\d+|zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|"
    r"nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)"
)
_HEAD_MOTION = r"(?:look|(?:turn|move|tilt) (?:(?:your|the) )?head)"
_DIRECTIONAL_ANGLE_REQUESTS = (
    re.compile(
        rf"^{_HEAD_MOTION} (?:to the )?"
        rf"(?P<direction>left|right|up|down) (?:by )?"
        rf"(?P<angle>{_ANGLE_TOKEN}) degrees?$"
    ),
    re.compile(
        rf"^{_HEAD_MOTION} (?P<angle>{_ANGLE_TOKEN}) degrees? "
        rf"(?:to the )?(?P<direction>left|right|up|down)$"
    ),
)


def _normalize_request(transcript: str) -> str:
    normalized = transcript.casefold().replace("°", " degrees ")
    tokens = re.findall(r"[a-z0-9]+", normalized)
    tokens = [
        {"ten": "10", "thirty": "30"}.get(token, token)
        for token in tokens
    ]
    text = " ".join(tokens)
    changed = True
    while changed and text:
        changed = False
        for prefix in _REQUEST_PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix) :].strip()
                changed = True
                break
    changed = True
    while changed and text:
        changed = False
        for suffix in _REQUEST_SUFFIXES:
            if text.endswith(suffix):
                text = text[: -len(suffix)].strip()
                changed = True
                break
    return text


def resolve_calibrated_request(transcript: str) -> ActionDecision | None:
    """Resolve only unambiguous fixed motions; leave all other text to the LLM."""
    request = _normalize_request(transcript)
    action = _DIRECT_REQUESTS.get(request)
    if action is not None:
        return ActionDecision(
            kind=DecisionKind.MOTION,
            action=action,
            reply=_accepted_reply(action),
        )

    match = next(
        (
            candidate
            for pattern in _DIRECTIONAL_ANGLE_REQUESTS
            if (candidate := pattern.fullmatch(request)) is not None
        ),
        None,
    )
    if match is None:
        return None
    direction = match.group("direction")
    angle = match.group("angle")
    if angle == "30" and direction != "down":
        direction_actions = {
            "left": MotionAction.LOOK_LEFT,
            "right": MotionAction.LOOK_RIGHT,
            "up": MotionAction.LOOK_UP,
        }
        action = direction_actions[direction]
        return ActionDecision(
            kind=DecisionKind.MOTION,
            action=action,
            reply=_accepted_reply(action),
        )
    if direction == "down":
        reply = "I don't have a direct calibrated look-down action."
    else:
        reply = (
            f"I can't use that angle. My calibrated {direction} action is "
            "exactly 30 degrees."
        )
    return ActionDecision(
        kind=DecisionKind.REJECTED_MOTION,
        reply=reply,
    )


class MotionExecutor(Protocol):
    async def execute(self, action: MotionAction) -> str: ...

    async def stop_passive(self) -> None: ...

    def snapshot(self) -> dict[str, object]: ...


def trim_to_sentence(text: str, limit: int = MAX_REPLY_CHARS) -> str:
    """Cut an over-long reply at the last sentence that fits.

    Reached only after the model has already been asked once to be brief, so
    the remaining choice is a shorter answer or none at all. Silence reads to
    the person as a robot that ignored them, which is worse than an answer
    that stops early. A fragment is worse still, so a cut is taken only at a
    sentence ending in the back half of the window.
    """
    window = text[:limit]
    cut = max(window.rfind("."), window.rfind("!"), window.rfind("?"))
    if cut >= limit // 2:
        return window[: cut + 1].strip()
    return window.rstrip()


def parse_agent_decision(raw: str, *, trim_overlong: bool = False) -> ActionDecision:
    """Parse an LLM decision while keeping physical actions on an allowlist."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("agent decision contains invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("agent decision must be a JSON object")
    expected_keys = {"kind", "reply", "motion"}
    if set(payload) != expected_keys:
        raise ValueError("agent decision must contain exactly kind, reply, and motion")

    raw_kind = payload["kind"]
    reply_value = payload["reply"]
    motion_value = payload["motion"]
    if not isinstance(raw_kind, str):
        raise ValueError("agent decision kind must be a string")
    if reply_value is not None and not isinstance(reply_value, str):
        raise ValueError("agent decision reply must be a string or null")
    if motion_value is not None and not isinstance(motion_value, str):
        raise ValueError("agent decision motion must be a string or null")
    kind = raw_kind.strip().casefold()
    reply = reply_value.strip() if reply_value is not None else ""
    motion = motion_value.strip().casefold() if motion_value is not None else ""
    if len(reply) > MAX_REPLY_CHARS:
        if not trim_overlong:
            raise ValueError("agent decision reply is too long for speech")
        reply = trim_to_sentence(reply)

    non_response_kinds = {
        "ignore": DecisionKind.IGNORE,
        "wait": DecisionKind.WAIT,
        "end_context": DecisionKind.CONTEXT_END,
    }
    if kind in non_response_kinds:
        if reply_value is not None or motion_value is not None:
            raise ValueError(f"{kind} decision must use null reply and motion")
        return ActionDecision(kind=non_response_kinds[kind])
    if kind == "reply":
        if not reply:
            raise ValueError("reply decision omitted spoken text")
        if motion_value is not None:
            # Dropped rather than fatal. A reply that also names a movement is
            # a request the agent is about to answer in full, and the agent
            # owns the body on a reply turn. Rejecting the whole decision costs
            # a repair round and then leaves Andy mute, which is a worse
            # failure than a discarded field -- and discarding a movement can
            # never cause one.
            log.info("ignored a movement named on a reply decision: %r", motion)
        return ActionDecision(kind=DecisionKind.CHAT, reply=reply)
    if kind == "sleep":
        if motion_value is not None:
            log.info("ignored a movement named on a sleep decision: %r", motion)
        return ActionDecision(
            kind=DecisionKind.SESSION_END,
            reply=reply or "Okay. I'll stop listening.",
        )
    if kind != "motion":
        raise ValueError(f"unknown agent decision kind: {raw_kind!r}")

    if not motion:
        raise ValueError("motion decision omitted its motion name")
    try:
        action = MotionAction(motion)
    except ValueError:
        return ActionDecision(
            kind=DecisionKind.REJECTED_MOTION,
            reply=(
                "I can't safely perform that motion. Please ask for one of my "
                "calibrated movements."
            ),
        )
    return ActionDecision(
        kind=DecisionKind.MOTION,
        action=action,
        reply=reply or _accepted_reply(action),
    )


class AgentActions:
    """Validate selected motion and own execution status counters."""

    def __init__(self, executor: MotionExecutor, *, enabled: bool = True) -> None:
        self._executor = executor
        self._enabled = enabled
        self._requests = 0
        self._rejections = 0
        self._completions = 0
        self._failures = 0
        self._state = "idle"
        self._decision_state = "idle"
        self._last_action: MotionAction | None = None
        self._last_detail = ""

    def authorize(
        self, decision: ActionDecision, transcript: str
    ) -> ActionDecision:
        if decision.kind is DecisionKind.MOTION:
            if decision.action is None:
                raise RuntimeError("motion decision omitted its fixed action")
            if not self._enabled:
                decision = ActionDecision(
                    kind=DecisionKind.REJECTED_MOTION,
                    reply="My fixed motion actions are disabled.",
                )
            else:
                self._requests += 1
                self._state = "queued"
                self._decision_state = decision.kind.value
                self._last_action = decision.action
                self._last_detail = "accepted through the fixed allowlist"
                log.info("motion decision accepted: %s", decision.action)
                return decision
        if decision.kind is DecisionKind.REJECTED_MOTION:
            self._rejections += 1
            self._state = "rejected"
            self._decision_state = decision.kind.value
            self._last_action = None
            self._last_detail = "motion request was outside the fixed action set"
            log.warning("motion request rejected for transcript: %r", transcript[:160])
        elif decision.kind is DecisionKind.IGNORE:
            self._decision_state = decision.kind.value
        elif decision.kind is DecisionKind.WAIT:
            self._decision_state = decision.kind.value
        elif decision.kind is DecisionKind.CONTEXT_END:
            self._decision_state = decision.kind.value
        elif decision.kind is DecisionKind.SESSION_END:
            self._decision_state = decision.kind.value
        elif decision.kind is DecisionKind.CHAT:
            self._decision_state = decision.kind.value
        return decision

    async def execute(self, action: MotionAction) -> str:
        self._state = "executing"
        self._last_action = action
        self._last_detail = "executing a fixed calibrated motion program"
        try:
            detail = await self._executor.execute(action)
        except asyncio.CancelledError:
            self._state = "cancelled"
            self._last_detail = "action cancelled before verified completion"
            log.warning("fixed motion cancelled: %s", action)
            raise
        except Exception as exc:
            self._failures += 1
            self._state = "failed"
            self._last_detail = str(exc)[:240]
            log.exception("fixed motion failed: %s", action)
            raise
        self._completions += 1
        self._state = "completed"
        self._last_detail = detail
        log.info("fixed motion completed: %s: %s", action, detail)
        return detail

    async def stop_passive(self) -> None:
        await self._executor.stop_passive()

    def snapshot(self) -> dict[str, object]:
        return {
            "allowed": [action.value for action in MotionAction],
            "state": self._state,
            "decision_state": self._decision_state,
            "requests": self._requests,
            "rejections": self._rejections,
            "completions": self._completions,
            "failures": self._failures,
            "last_action": (
                self._last_action.value if self._last_action is not None else None
            ),
            "last_detail": self._last_detail,
            "device": self._executor.snapshot(),
        }


def _accepted_reply(action: MotionAction) -> str:
    replies = {
        MotionAction.HOME: "I'll return my head to its calibrated home position.",
        MotionAction.LOOK_LEFT: "I'll look to my left.",
        MotionAction.LOOK_RIGHT: "I'll look to my right.",
        MotionAction.LOOK_UP: "I'll look up.",
        MotionAction.NOD_YES: "Yes, I'll nod.",
        MotionAction.SHAKE_NO: "No, I'll shake my head.",
        MotionAction.BOW: "I'll take a bow.",
        MotionAction.GREET: "Hello! Here's my greeting.",
        MotionAction.CELEBRATE: "Let's celebrate!",
        MotionAction.SCAN: "I'll look around.",
        MotionAction.DANCE: "Dance time!",
        MotionAction.YAW_POSITIVE_10: (
            "I'll move my head to yaw positive ten degrees."
        ),
        MotionAction.PITCH_POSITIVE_10: (
            "I'll move my head to pitch positive ten degrees."
        ),
    }
    return replies[action]
