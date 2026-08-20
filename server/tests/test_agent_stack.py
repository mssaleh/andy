"""The pieces added around the agent: effects, arbiter, event routing."""

from __future__ import annotations

import asyncio
from datetime import datetime, time

import pytest

from andy.arbiter import Priority, QuietHours, SpeechArbiter
from andy.bus import DeviceEvent, EventBus, EventKind, Route
from andy.effects import AttentionAction, EffectController, EmotionRequest


class FakeDevice:
    def __init__(self, emotions=("happy", "sad", "neutral")) -> None:
        self.program = False
        self._emotions = tuple(emotions)
        self.connected = True
        self.selected: str | None = None
        self.numbers: dict[str, float] = {}
        self.pressed: list[str] = []
        self._states: dict[str, object] = {}
        self._listeners = []

    def select_options(self, object_id: str):
        return self._emotions if object_id == "emotion" else ()

    def select_option(self, object_id: str, option: str) -> None:
        self.selected = option

    def set_number(self, object_id: str, value: float) -> None:
        self.numbers[object_id] = value

    def press(self, object_id: str) -> None:
        self.pressed.append(object_id)

    def has_button(self, object_id: str) -> bool:
        return True

    def get(self, object_id: str):
        if object_id == "motion_program":
            return self.program
        return self._states.get(object_id)

    async def wait_for(self, predicate, timeout, phase):
        if predicate():
            return
        raise TimeoutError(phase)

    def subscribe(self, listener) -> None:
        self._listeners.append(listener)

    def emit(self, object_id: str, value) -> None:
        self._states[object_id] = value
        for listener in self._listeners:
            listener(object_id, value)


@pytest.mark.asyncio
async def test_emotion_must_come_from_the_device_vocabulary() -> None:
    device = FakeDevice()
    effects = EffectController(device)  # type: ignore[arg-type]

    await effects.set_emotion(EmotionRequest(emotion="happy", intensity=80))
    assert device.selected == "happy"
    assert device.numbers["emotion_intensity"] == 80

    with pytest.raises(ValueError, match="unknown emotion"):
        await effects.set_emotion(EmotionRequest(emotion="incandescent"))


@pytest.mark.asyncio
async def test_emotion_moves_the_body_only_when_asked() -> None:
    device = FakeDevice()
    effects = EffectController(device)  # type: ignore[arg-type]

    await effects.set_emotion(EmotionRequest(emotion="sad"))
    assert "emotion_express" not in device.pressed

    await effects.set_emotion(EmotionRequest(emotion="sad", express=True))
    assert "emotion_express" in device.pressed


@pytest.mark.asyncio
async def test_intensity_is_clamped_not_rejected() -> None:
    device = FakeDevice()
    effects = EffectController(device)  # type: ignore[arg-type]
    await effects.set_emotion(EmotionRequest(emotion="happy", intensity=5_000))
    assert device.numbers["emotion_intensity"] == 100


def test_attention_maps_to_the_conversation_buttons() -> None:
    device = FakeDevice()
    effects = EffectController(device)  # type: ignore[arg-type]
    effects.attention(AttentionAction.SLEEP)
    assert device.pressed == ["conversation_sleep"]


class FakeSpeaker:
    def __init__(self) -> None:
        self.played: list[str] = []

    async def play_announcement(self, url: str) -> None:
        self.played.append(url)

    async def stop_announcement(self) -> None:
        pass


class FakeTTS:
    async def synthesize(self, text: str, *, pace: float = 1.0) -> bytes:
        return b"RIFF" + text.encode()


def _arbiter(**kwargs) -> SpeechArbiter:
    from andy.media import AudioStore

    return SpeechArbiter(
        FakeSpeaker(),  # type: ignore[arg-type]
        AudioStore(),
        FakeTTS(),
        media_base_url="http://andy.test",
        **kwargs,
    )


@pytest.mark.asyncio
async def test_a_reply_always_outranks_the_rate_limit() -> None:
    # Pinned to the middle of the afternoon. With the real clock this passes by
    # day and fails after ten at night, because proactive speech is silenced in
    # quiet hours -- a test that depends on when it is run proves nothing.
    arbiter = _arbiter(
        min_proactive_gap=3600.0,
        clock=lambda: datetime(2026, 8, 20, 14, 0),
    )
    assert await arbiter.say("first thought", Priority.PROACTIVE)
    # Proactive speech is now rate limited, but a person still gets an answer.
    assert not await arbiter.say("second thought", Priority.PROACTIVE)
    assert await arbiter.say("answer to a question", Priority.REPLY)


@pytest.mark.asyncio
async def test_quiet_hours_silence_only_proactive_speech() -> None:
    midnight = datetime(2026, 8, 20, 23, 30)
    arbiter = _arbiter(
        quiet_hours=QuietHours(start=time(22, 0), end=time(7, 30)),
        clock=lambda: midnight,
    )
    assert not await arbiter.say("are you awake", Priority.PROACTIVE)
    assert await arbiter.say("you asked me something", Priority.REPLY)


@pytest.mark.asyncio
async def test_events_are_debounced_and_routed() -> None:
    device = FakeDevice()
    bus = EventBus(device)  # type: ignore[arg-type]
    seen: list[DeviceEvent] = []

    async def collect(event: DeviceEvent) -> None:
        seen.append(event)

    bus.on(Route.AGENT, collect)
    bus.on(Route.RULE, collect)
    bus.start()

    device.emit("presence", True)
    device.emit("presence", True)   # unchanged, never observed
    device.emit("presence", False)  # PRESENCE_LEFT is dropped by policy
    await asyncio.sleep(0.05)
    await bus.stop()

    assert [event.kind for event in seen] == [EventKind.PRESENCE_ARRIVED]


@pytest.mark.asyncio
async def test_a_repeated_event_inside_its_window_is_suppressed() -> None:
    device = FakeDevice()
    ticks = iter([0.0, 1000.0])
    bus = EventBus(device, clock=lambda: next(ticks))  # type: ignore[arg-type]
    seen: list[DeviceEvent] = []

    async def collect(event: DeviceEvent) -> None:
        seen.append(event)

    bus.on(Route.AGENT, collect)
    bus.start()

    device.emit("shake_detected", True)
    device.emit("shake_detected", False)
    device.emit("shake_detected", True)  # far outside the window
    await asyncio.sleep(0.05)
    await bus.stop()

    assert [event.kind for event in seen] == [EventKind.SHAKEN, EventKind.SHAKEN]


@pytest.mark.asyncio
async def test_a_motion_fault_is_a_rule_and_never_reaches_the_agent() -> None:
    device = FakeDevice()
    bus = EventBus(device)  # type: ignore[arg-type]
    routed: dict[str, list[EventKind]] = {"rule": [], "agent": []}

    async def rule(event: DeviceEvent) -> None:
        routed["rule"].append(event.kind)

    async def agent(event: DeviceEvent) -> None:
        routed["agent"].append(event.kind)

    bus.on(Route.RULE, rule)
    bus.on(Route.AGENT, agent)
    bus.start()

    device.emit("motion_faults", 0)
    device.emit("motion_faults", 1)
    await asyncio.sleep(0.05)
    await bus.stop()

    assert routed["rule"] == [EventKind.MOTION_FAULTED]
    assert routed["agent"] == []


def test_spoken_text_drops_a_narrated_self_correction() -> None:
    """A model that corrects itself mid-answer would say both halves aloud."""
    from andy.agent import spoken_text

    raw = (
        "Great news! Let's celebrate! \U0001F389\n\n"
        "Wait, I shouldn't use emoji. Let me rephrase.\n\n"
        "Oh, that is wonderful news."
    )
    assert spoken_text(raw) == "Oh, that is wonderful news."


def test_spoken_text_removes_what_cannot_be_heard() -> None:
    from andy.agent import spoken_text

    assert spoken_text("**Bold** and _italic_ and `code`") == "Bold and italic and code"
    assert spoken_text("Line one.\nLine two.") == "Line one. Line two."
    assert spoken_text("Nice \U0001F600 day") == "Nice  day".replace("  ", " ")


def test_memory_survives_a_restart(tmp_path) -> None:
    from andy.memory import MemoryStore

    store = MemoryStore(tmp_path / "m.json")
    store.remember("Mohammed takes his tablets at eight")
    store.remember("the cat is called Pepper")

    # A new process, the same disk.
    reopened = MemoryStore(tmp_path / "m.json")
    assert [m.text for m in reopened.recall("cat")] == ["the cat is called Pepper"]


def test_memory_is_bounded_and_deduplicated(tmp_path) -> None:
    from andy.memory import MemoryStore

    store = MemoryStore(tmp_path / "m.json", limit=3)
    for i in range(5):
        store.remember(f"fact {i}")
    assert store.snapshot()["count"] == 3

    store.remember("fact 4")  # restating a fact must not consume a slot
    assert store.snapshot()["count"] == 3


def test_forgetting_removes_matching_memories(tmp_path) -> None:
    from andy.memory import MemoryStore

    store = MemoryStore(tmp_path / "m.json")
    store.remember("the cat is called Pepper")
    store.remember("the dog is called Rex")
    assert store.forget("cat") == 1
    assert [m.text for m in store.recall()] == ["the dog is called Rex"]


@pytest.mark.asyncio
async def test_a_reminder_survives_a_restart_and_then_speaks(tmp_path) -> None:
    from datetime import datetime, timedelta, timezone
    from andy.scheduler import Scheduler

    base = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
    arbiter = _arbiter()
    scheduler = Scheduler(arbiter, tmp_path / "t.json", clock=lambda: base)
    scheduler.schedule("Time to drink water.", timedelta(minutes=10))

    # Restart: a new scheduler, the same disk, and the clock now past due.
    later = base + timedelta(minutes=11)
    revived = Scheduler(arbiter, tmp_path / "t.json", clock=lambda: later)
    due = await revived.due()
    assert [t.text for t in due] == ["Time to drink water."]
    # Popping is persisted, so it cannot fire twice.
    assert await revived.due() == []


@pytest.mark.asyncio
async def test_a_reminder_speaks_through_quiet_hours() -> None:
    """It was explicitly asked for, so it is an alert rather than a thought."""
    from datetime import datetime, time, timedelta, timezone
    from andy.arbiter import QuietHours
    from andy.scheduler import Scheduler

    midnight = datetime(2026, 8, 20, 23, 30, tzinfo=timezone.utc)
    arbiter = _arbiter(
        quiet_hours=QuietHours(start=time(22, 0), end=time(7, 30)),
        clock=lambda: midnight,
    )
    scheduler = Scheduler(arbiter, None, clock=lambda: midnight)
    scheduler.schedule("Take your tablets.", timedelta(minutes=-1) + timedelta(minutes=2))

    assert await arbiter.say("Take your tablets.", Priority.ALERT)


def test_a_reminder_cannot_be_set_beyond_the_horizon() -> None:
    from datetime import timedelta
    from andy.scheduler import Scheduler

    scheduler = Scheduler(_arbiter(), None)
    with pytest.raises(ValueError, match="seven days"):
        scheduler.schedule("too far away", timedelta(days=30))
    with pytest.raises(ValueError, match="future"):
        scheduler.schedule("in the past", timedelta(minutes=-5))


def test_a_firmware_program_ends_on_a_verified_terminal_state() -> None:
    """The program path proves completion differently from the pose path.

    A pose reports `complete: ... torque=0/0`. A whole program reports the
    terminal state that `end_motion_program` publishes only after it has
    verified torque release and cut the rail.
    """
    from andy.motion import _TERMINAL

    assert _TERMINAL.match("idle: torque released; servo rail off")
    assert not _TERMINAL.match("fault: program torque release readback=-1/-1")
    assert not _TERMINAL.match("moving: 466/620 -> 552/620 speed=300")


def test_a_spoken_promise_needs_the_tool_that_keeps_it() -> None:
    """Andy cannot keep a promise he only said.

    Observed in production: the agent answered "Got it, I'll remind you to take
    the bread out of the oven" and set no timer. Spoken aloud that is worse
    than a refusal, because the person stops holding the thing themselves.
    """
    from andy.agent import unkept_promise

    assert unkept_promise("I'll remind you in ten minutes.", frozenset()) == (
        "set_a_reminder"
    )
    assert (
        unkept_promise(
            "I'll remind you in ten minutes.", frozenset({"set_a_reminder"})
        )
        is None
    )
    assert unkept_promise("Reminder set for later.", frozenset()) == (
        "set_a_reminder"
    )
    assert unkept_promise("I'll remember that you take it black.", frozenset()) == (
        "remember_this"
    )
    assert (
        unkept_promise(
            "I'll remember that.", frozenset({"remember_this"})
        )
        is None
    )


def test_an_ordinary_answer_is_not_mistaken_for_a_promise() -> None:
    from andy.agent import unkept_promise

    for innocent in (
        "It's a quiet evening in here.",
        "I can look left if you want me to.",
        "That sounds like a good idea.",
        "I don't have a timer running right now.",
    ):
        assert unkept_promise(innocent, frozenset()) is None


def test_tools_called_reads_the_names_off_the_run() -> None:
    from andy.agent import tools_called

    class ToolCallPart:
        def __init__(self, name: str) -> None:
            self.tool_name = name

    class Message:
        def __init__(self, parts) -> None:
            self.parts = parts

    messages = [
        Message([ToolCallPart("set_a_reminder"), ToolCallPart("show_feeling")])
    ]
    assert tools_called(messages) == frozenset(
        {"set_a_reminder", "show_feeling"}
    )
    assert tools_called([]) == frozenset()


def test_every_tool_the_model_asked_for_actually_runs() -> None:
    """The answer tool must not cancel the work tools beside it.

    Measured against the live model: an action and the final answer arrive in
    one response, and the default strategy ends the run on the answer, so the
    action is counted and never executed. Andy then says he set a reminder
    that does not exist, about one request in three.
    """
    import inspect

    from andy.agent import build_agent

    source = inspect.getsource(build_agent)
    assert 'end_strategy="exhaustive"' in source


def test_a_fact_is_named_for_what_its_sensor_can_know() -> None:
    """Proximity is not occupancy.

    The LTR-553 triggers at roughly arm's length. Handed to the model as
    presence, it answered a person sitting a metre away that nobody was there.
    A fact named wider than its sensor produces a confident falsehood.
    """
    from andy.device import DeviceState

    source = DeviceState.interpreted.__doc__ or ""
    assert "named for what its sensor can actually know" in source

    import inspect

    body = inspect.getsource(DeviceState.interpreted)
    assert "someone_close_to_me" in body
    assert "someone_present" not in body


def test_the_voice_carries_the_feeling_the_face_is_wearing() -> None:
    """Andy sounded identical delighted and sorry.

    Pace is the one prosodic control this synthesiser offers, and it is a real
    carrier of affect. The band is bounded by measurement, not taste: above it
    the recogniser starts hearing Andy's own name as something else.
    """
    from andy.effects import MAX_PACE_SHIFT, speech_pace

    assert speech_pace("neutral") == 1.0
    assert speech_pace(None) == 1.0
    assert speech_pace("a-feeling-that-does-not-exist") == 1.0

    assert speech_pace("delighted", 100) == 1.0 + MAX_PACE_SHIFT
    assert speech_pace("sad", 100) == 1.0 - MAX_PACE_SHIFT
    # Intensity scales it, so a feeling held weakly barely moves the voice.
    assert speech_pace("delighted", 0) == 1.0
    assert 1.0 < speech_pace("laughing", 50) < speech_pace("laughing", 100)


def test_the_pace_never_leaves_the_band_the_recogniser_survives() -> None:
    from andy.effects import speech_pace

    for emotion in ("delighted", "sad", "furious", "sleepy", "neutral"):
        for intensity in (-50, 0, 50, 100, 500):
            assert 0.8 <= speech_pace(emotion, intensity) <= 1.2


def test_andy_is_told_he_has_the_body_he_is_speaking_through() -> None:
    """Asked for music he answered that he had no speakers.

    He was speaking through one at the time. Declining was right and the reason
    was false, which is the same failure as denying the scheduler he was
    holding: what he is told he can do has to include the parts he is using.
    """
    import inspect

    from andy.agent import SYSTEM_PROMPT, AgentConversation

    listed = inspect.getsource(AgentConversation.capabilities)
    assert "speaker in his own body" in listed

    assert "never deny having a part of your body that you are using" in (
        SYSTEM_PROMPT.casefold()
    )
