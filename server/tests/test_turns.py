from __future__ import annotations

import asyncio
from collections import deque
import json
import struct

import pytest

from andy.actions import ActionDecision, DecisionKind, MotionAction
from andy.events import DeviceEvent, EventKind
from andy.media import AudioStore
from andy.turns import (
    TurnCoordinator,
    TurnState,
    TurnTimeouts,
    _pcm16_metrics,
    speech_only,
)
from andy.vad import VADDecision


def test_pcm16_metrics_reports_duration_rms_and_peak() -> None:
    assert _pcm16_metrics(struct.pack("<hhhh", -3, 4, 0, 0)) == (
        4 / 16_000,
        2,
        4,
    )
    assert _pcm16_metrics(b"") == (0.0, 0, 0)


class Sink:
    def __init__(self) -> None:
        self.events: list[DeviceEvent] = []

    def emit(self, event: DeviceEvent) -> None:
        self.events.append(event)


class Detector:
    def __init__(self, batches: list[tuple[VADDecision, ...]]) -> None:
        self._batches = deque(batches)
        self.speech_started = False
        self.has_transcribable_speech = False

    def push(self, pcm16: bytes) -> tuple[VADDecision, ...]:
        del pcm16
        batch = self._batches.popleft() if self._batches else ()
        if VADDecision.SPEECH_STARTED in batch:
            self.speech_started = True
        if VADDecision.SPEECH_ENDED in batch:
            self.has_transcribable_speech = True
        return batch

    def finish(self) -> VADDecision:
        return (
            VADDecision.SPEECH_ENDED
            if self.has_transcribable_speech
            else VADDecision.NO_SPEECH_TIMEOUT
        )


class ASR:
    def __init__(self, text: str = "Hello Andy") -> None:
        self.text = text
        self.calls = 0

    async def transcribe(self, pcm16_16k: bytes) -> str:
        assert pcm16_16k
        self.calls += 1
        return self.text


class SequenceASR(ASR):
    def __init__(self, texts: list[str]) -> None:
        super().__init__()
        self._texts = deque(texts)

    async def transcribe(self, pcm16_16k: bytes) -> str:
        assert pcm16_16k
        self.calls += 1
        return self._texts.popleft()


class LLM:
    def __init__(
        self,
        decision: dict[str, object] | None = None,
    ) -> None:
        self.decision = decision or {
            "kind": "reply",
            "reply": "Hello from Andy.",
            "motion": None,
        }
        self.calls = 0
        self.requests: list[list[dict[str, str]]] = []

    async def complete(self, messages: list[dict[str, str]]) -> str:
        assert messages[-1]["content"]
        self.calls += 1
        self.requests.append(list(messages))
        return json.dumps(self.decision)


class SequenceLLM(LLM):
    def __init__(self, decisions: list[dict[str, object]]) -> None:
        super().__init__()
        self._decisions = deque(decisions)

    async def complete(self, messages: list[dict[str, str]]) -> str:
        assert messages[-1]["content"]
        self.calls += 1
        self.requests.append(list(messages))
        return json.dumps(self._decisions.popleft())


class TTS:
    def __init__(self, wav: bytes = b"RIFF-test") -> None:
        self.wav = wav
        self.calls = 0
        self.texts: list[str] = []
        self.paces: list[float] = []

    async def synthesize(self, text: str, *, pace: float = 1.0) -> bytes:
        assert text
        self.calls += 1
        self.texts.append(text)
        self.paces.append(pace)
        return self.wav


class Output:
    def __init__(self) -> None:
        self.played: list[str] = []
        self.stops = 0

    async def play_announcement(self, url: str) -> None:
        self.played.append(url)

    async def stop_announcement(self) -> None:
        self.stops += 1


class Actions:
    def __init__(self) -> None:
        self.decisions: list[tuple[ActionDecision, str]] = []
        self.executed: list[MotionAction] = []
        self.passive_stops = 0

    def authorize(
        self, decision: ActionDecision, transcript: str
    ) -> ActionDecision:
        self.decisions.append((decision, transcript))
        return decision

    async def execute(self, action: MotionAction) -> str:
        self.executed.append(action)
        return "complete: torque=0/0"

    async def stop_passive(self) -> None:
        self.passive_stops += 1

    def snapshot(self) -> dict[str, object]:
        return {
            "state": "idle",
            "allowed": [action.value for action in MotionAction],
            "device": {
                "motion_active": False,
                "voice_state": "listening",
            },
        }


def make_coordinator(
    batches: list[tuple[VADDecision, ...]],
    *,
    asr: ASR | None = None,
    llm: LLM | None = None,
    tts: TTS | None = None,
    output: Output | None = None,
    actions: Actions | None = None,
    conversation: object | None = None,
    history_turns: int = 8,
    timeouts: TurnTimeouts | None = None,
) -> tuple[TurnCoordinator, Sink, ASR, LLM, TTS, Output]:
    sink = Sink()
    asr = asr or ASR()
    llm = llm or LLM()
    tts = tts or TTS()
    output = output or Output()
    coordinator = TurnCoordinator(
        sink=sink,
        asr=asr,
        llm=llm,
        tts=tts,
        media=AudioStore(),
        output=output,
        media_base_url="http://andy.test:8900",
        system_prompt="You are Andy.",
        detector_factory=lambda: Detector(list(batches)),
        history_turns=history_turns,
        timeouts=timeouts,
        actions=actions,
        conversation=conversation,
    )
    return coordinator, sink, asr, llm, tts, output


@pytest.mark.asyncio
async def test_utterance_closes_capture_before_server_reasoning() -> None:
    coordinator, sink, _, llm, tts, output = make_coordinator(
        [(VADDecision.SPEECH_STARTED,), (VADDecision.SPEECH_ENDED,)]
    )

    assert await coordinator.on_start() == 0
    await coordinator.on_audio(b"speech")
    await coordinator.on_audio(b"silence")
    assert coordinator.state is TurnState.IDLE
    assert [event.kind for event in sink.events] == [
        EventKind.RUN_START,
        EventKind.STT_START,
        EventKind.STT_VAD_START,
        EventKind.RUN_END,
    ]
    await coordinator.wait_until_idle()

    assert llm.calls == tts.calls == 1
    assert len(output.played) == 1
    assert output.played[0].endswith(".wav")
    await coordinator.close()


@pytest.mark.asyncio
async def test_silent_window_is_routine_and_immediately_renewable() -> None:
    coordinator, sink, asr, llm, tts, output = make_coordinator(
        [(VADDecision.NO_SPEECH_TIMEOUT,)]
    )

    await coordinator.on_start()
    await coordinator.on_audio(b"quiet")

    assert [event.kind for event in sink.events] == [
        EventKind.RUN_START,
        EventKind.STT_START,
        EventKind.RUN_END,
    ]
    assert asr.calls == llm.calls == tts.calls == 0
    assert output.played == []

    await coordinator.on_start()
    assert coordinator.state is TurnState.LISTENING
    await coordinator.close()


@pytest.mark.asyncio
async def test_empty_stt_is_not_a_device_error() -> None:
    coordinator, sink, _, llm, tts, output = make_coordinator(
        [(VADDecision.SPEECH_STARTED, VADDecision.SPEECH_ENDED)],
        asr=ASR(""),
    )

    await coordinator.on_start()
    await coordinator.on_audio(b"speech")
    await coordinator.wait_until_idle()

    kinds = [event.kind for event in sink.events]
    assert kinds[-1] is EventKind.RUN_END
    assert EventKind.ERROR not in kinds
    assert llm.calls == tts.calls == 0
    assert output.played == []
    await coordinator.close()


@pytest.mark.asyncio
async def test_llm_can_ignore_background_speech_without_tts() -> None:
    llm = LLM({"kind": "ignore", "reply": None, "motion": None})
    actions = Actions()
    coordinator, _, _, _, tts, output = make_coordinator(
        [(VADDecision.SPEECH_STARTED, VADDecision.SPEECH_ENDED)],
        llm=llm,
        actions=actions,
    )

    await coordinator.on_start()
    await coordinator.on_audio(b"background")
    await coordinator.wait_until_idle()

    assert actions.decisions[0][0].kind is DecisionKind.IGNORE
    assert tts.calls == 0
    assert output.played == []
    await coordinator.close()


@pytest.mark.asyncio
async def test_agent_receives_trusted_runtime_state() -> None:
    llm = LLM({"kind": "ignore", "reply": None, "motion": None})
    actions = Actions()
    coordinator, _, _, _, _, _ = make_coordinator(
        [(VADDecision.SPEECH_STARTED, VADDecision.SPEECH_ENDED)],
        llm=llm,
        actions=actions,
    )

    await coordinator.on_start()
    await coordinator.on_audio(b"background")
    await coordinator.wait_until_idle()

    system_prompt = llm.requests[0][0]["content"]
    assert "Current trusted runtime state" in system_prompt
    assert '"motion_active":false' in system_prompt
    assert '"voice_state":"listening"' in system_prompt
    assert (
        "- look_right: look exactly 30 degrees right, hold briefly, "
        "then return home"
    ) in system_prompt
    assert "Select motion immediately without asking for confirmation" in (
        system_prompt.replace("\n", " ")
    )
    await coordinator.close()


@pytest.mark.asyncio
async def test_malformed_agent_decision_gets_one_bounded_repair() -> None:
    class RepairingLLM(LLM):
        async def complete(self, messages: list[dict[str, str]]) -> str:
            self.calls += 1
            self.requests.append(list(messages))
            if self.calls == 1:
                return "I think Andy should answer."
            return json.dumps(
                {"kind": "reply", "reply": "Hello.", "motion": None}
            )

    llm = RepairingLLM()
    coordinator, _, _, _, tts, output = make_coordinator(
        [(VADDecision.SPEECH_STARTED, VADDecision.SPEECH_ENDED)],
        llm=llm,
    )

    await coordinator.on_start()
    await coordinator.on_audio(b"hello")
    await coordinator.wait_until_idle()

    assert llm.calls == 2
    assert llm.requests[1][-1]["content"].startswith(
        "Your preceding answer did not satisfy"
    )
    assert tts.texts == ["Hello."]
    assert len(output.played) == 1
    await coordinator.close()


@pytest.mark.asyncio
async def test_llm_combines_incomplete_transcript_fragments_semantically() -> None:
    llm = SequenceLLM(
        [
            {"kind": "wait", "reply": None, "motion": None},
            {
                "kind": "motion",
                "reply": "I'll look right.",
                "motion": "look_right",
            },
        ]
    )
    actions = Actions()
    coordinator, _, _, _, tts, _ = make_coordinator(
        [(VADDecision.SPEECH_STARTED, VADDecision.SPEECH_ENDED)],
        asr=SequenceASR(["Andy could you", "please look right"]),
        llm=llm,
        actions=actions,
    )

    await coordinator.on_start()
    await coordinator.on_audio(b"fragment-one")
    await coordinator.wait_until_idle()
    assert coordinator._pending_fragments == ["Andy could you"]
    assert tts.calls == 0

    await coordinator.on_start()
    await coordinator.on_audio(b"fragment-two")
    await coordinator.wait_until_idle()

    assert llm.calls == 1
    assert llm.requests[-1][-1]["content"] == "Andy could you"
    assert coordinator._pending_fragments == []
    assert actions.executed == [MotionAction.LOOK_RIGHT]
    await coordinator.close()


@pytest.mark.asyncio
async def test_exact_calibrated_angle_bypasses_a_confused_llm() -> None:
    llm = LLM(
        {
            "kind": "reply",
            "reply": "Want me to look right?",
            "motion": None,
        }
    )
    actions = Actions()
    coordinator, _, _, _, tts, output = make_coordinator(
        [(VADDecision.SPEECH_STARTED, VADDecision.SPEECH_ENDED)],
        asr=ASR("Please turn your head to the right by 30 degrees."),
        llm=llm,
        actions=actions,
    )

    await coordinator.on_start()
    await coordinator.on_audio(b"exact-calibrated-request")
    await coordinator.wait_until_idle()

    assert llm.calls == 0
    assert actions.executed == [MotionAction.LOOK_RIGHT]
    assert tts.texts == ["I'll look to my right."]
    assert len(output.played) == 1
    await coordinator.close()


@pytest.mark.asyncio
async def test_unsupported_angle_never_reaches_the_llm_or_motion() -> None:
    llm = LLM(
        {
            "kind": "motion",
            "reply": "Moving.",
            "motion": "look_right",
        }
    )
    actions = Actions()
    coordinator, _, _, _, tts, output = make_coordinator(
        [(VADDecision.SPEECH_STARTED, VADDecision.SPEECH_ENDED)],
        asr=ASR("Please turn your head to the right by 20 degrees."),
        llm=llm,
        actions=actions,
    )

    await coordinator.on_start()
    await coordinator.on_audio(b"unsupported-angle-request")
    await coordinator.wait_until_idle()

    assert llm.calls == 0
    assert actions.executed == []
    assert "exactly 30 degrees" in tts.texts[0]
    assert len(output.played) == 1
    await coordinator.close()


@pytest.mark.asyncio
async def test_llm_motion_runs_only_through_action_handler() -> None:
    llm = LLM(
        {
            "kind": "motion",
            "reply": "Yes, I'll nod.",
            "motion": "nod_yes",
        }
    )
    actions = Actions()
    coordinator, _, _, _, tts, output = make_coordinator(
        [(VADDecision.SPEECH_STARTED, VADDecision.SPEECH_ENDED)],
        llm=llm,
        actions=actions,
    )

    await coordinator.on_start()
    await coordinator.on_audio(b"please nod")
    await coordinator.wait_until_idle()

    assert actions.executed == [MotionAction.NOD_YES]
    assert tts.texts == ["Yes, I'll nod."]
    assert len(output.played) == 1
    await coordinator.close()


@pytest.mark.asyncio
async def test_sleep_decision_stops_continuous_capture_then_speaks_once() -> None:
    llm = LLM(
        {"kind": "sleep", "reply": "Okay, I'll stop listening.", "motion": None}
    )
    actions = Actions()
    coordinator, _, _, _, tts, output = make_coordinator(
        [(VADDecision.SPEECH_STARTED, VADDecision.SPEECH_ENDED)],
        llm=llm,
        actions=actions,
    )

    await coordinator.on_start()
    await coordinator.on_audio(b"stop listening")
    await coordinator.wait_until_idle()

    assert actions.passive_stops == 1
    assert tts.calls == 1
    assert len(output.played) == 1
    assert coordinator._history == []
    await coordinator.close()


@pytest.mark.asyncio
async def test_provider_failure_never_corrupts_the_next_capture_pipeline() -> None:
    class BrokenLLM(LLM):
        async def complete(self, messages: list[dict[str, str]]) -> str:
            raise RuntimeError("unavailable")

    coordinator, sink, _, _, _, output = make_coordinator(
        [(VADDecision.SPEECH_STARTED, VADDecision.SPEECH_ENDED)],
        llm=BrokenLLM(),
    )

    await coordinator.on_start()
    await coordinator.on_audio(b"speech")
    await coordinator.wait_until_idle()
    await coordinator.on_start()

    kinds = [event.kind for event in sink.events]
    assert EventKind.ERROR not in kinds
    assert kinds.count(EventKind.RUN_END) == 1
    assert kinds[-2:] == [EventKind.RUN_START, EventKind.STT_START]
    assert output.played == []
    await coordinator.close()


@pytest.mark.asyncio
async def test_raw_vad_does_not_cancel_pending_asr() -> None:
    entered = asyncio.Event()

    class BlockingASR(ASR):
        async def transcribe(self, pcm16_16k: bytes) -> str:
            assert pcm16_16k
            entered.set()
            await asyncio.Future()
            return ""

    coordinator, _, _, _, _, _ = make_coordinator(
        [(VADDecision.SPEECH_STARTED,), (VADDecision.SPEECH_ENDED,)],
        asr=BlockingASR(),
    )
    await coordinator.on_start()
    await coordinator.on_audio(b"first")
    await coordinator.on_audio(b"first-end")
    await entered.wait()

    await coordinator.on_start()
    await coordinator.on_audio(b"second")

    assert len(coordinator._utterance_tasks) == 1
    assert all(not task.done() for task in coordinator._utterance_tasks)
    await coordinator.close()


@pytest.mark.asyncio
async def test_new_transcript_cancels_stale_reasoning() -> None:
    first_entered = asyncio.Event()
    first_cancelled = asyncio.Event()

    class SupersedingLLM(LLM):
        async def complete(self, messages: list[dict[str, str]]) -> str:
            self.calls += 1
            self.requests.append(list(messages))
            if self.calls == 1:
                first_entered.set()
                try:
                    await asyncio.Future()
                finally:
                    first_cancelled.set()
            return json.dumps(
                {"kind": "ignore", "reply": None, "motion": None}
            )

    llm = SupersedingLLM()
    coordinator, _, _, _, tts, output = make_coordinator(
        [(VADDecision.SPEECH_STARTED,), (VADDecision.SPEECH_ENDED,)],
        llm=llm,
    )
    await coordinator.on_start()
    await coordinator.on_audio(b"first")
    await coordinator.on_audio(b"first-end")
    await first_entered.wait()

    await coordinator.on_start()
    await coordinator.on_audio(b"second")
    await coordinator.on_audio(b"second-end")
    await first_cancelled.wait()
    await coordinator.wait_until_idle()

    assert llm.calls == 2
    assert coordinator._response_task is None
    assert tts.calls == 0
    assert output.played == []
    await coordinator.close()


@pytest.mark.asyncio
async def test_abort_discards_partial_capture_without_cancelling_response() -> None:
    coordinator, sink, _, _, _, _ = make_coordinator([])
    await coordinator.on_start()
    await coordinator.on_audio(b"partial")
    await coordinator.on_stop(True)
    await coordinator.on_stop(True)

    assert [event.kind for event in sink.events].count(EventKind.RUN_END) == 0
    assert coordinator.state is TurnState.IDLE
    await coordinator.close()


@pytest.mark.asyncio
async def test_provider_timeout_is_recoverable() -> None:
    class SlowASR(ASR):
        async def transcribe(self, pcm16_16k: bytes) -> str:
            await asyncio.sleep(0.05)
            return "hello"

    coordinator, sink, _, _, _, output = make_coordinator(
        [(VADDecision.SPEECH_STARTED, VADDecision.SPEECH_ENDED)],
        asr=SlowASR(),
        timeouts=TurnTimeouts(asr_seconds=0.001),
    )
    await coordinator.on_start()
    await coordinator.on_audio(b"speech")
    await coordinator.wait_until_idle()

    assert [event.kind for event in sink.events].count(EventKind.RUN_END) == 1
    assert EventKind.ERROR not in [event.kind for event in sink.events]
    assert output.played == []
    await coordinator.close()


@pytest.mark.asyncio
async def test_context_is_bounded_and_can_expire_after_silence() -> None:
    coordinator, _, _, llm, _, _ = make_coordinator(
        [(VADDecision.SPEECH_STARTED, VADDecision.SPEECH_ENDED)],
        history_turns=1,
    )
    for _ in range(2):
        await coordinator.on_start()
        await coordinator.on_audio(b"speech")
        await coordinator.wait_until_idle()

    assert [message["role"] for message in llm.requests[-1]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert len(coordinator._history) == 2
    coordinator._pending_fragments.append("unfinished")
    coordinator._session_idle_seconds = 0.01
    coordinator._schedule_session_expiry()
    await asyncio.sleep(0.02)
    assert coordinator._history == []
    assert coordinator._pending_fragments == []
    await coordinator.close()


@pytest.mark.asyncio
async def test_nonempty_transcript_restarts_the_context_silence_window() -> None:
    entered = asyncio.Event()

    class BlockingLLM(LLM):
        async def complete(self, messages: list[dict[str, str]]) -> str:
            entered.set()
            await asyncio.Future()
            return ""

    coordinator, _, _, _, _, _ = make_coordinator(
        [(VADDecision.SPEECH_STARTED, VADDecision.SPEECH_ENDED)],
        llm=BlockingLLM(),
    )
    coordinator._history = [
        {"role": "user", "content": "Earlier question"},
        {"role": "assistant", "content": "Earlier answer"},
    ]
    coordinator._session_idle_seconds = 0.01
    coordinator._schedule_session_expiry()
    coordinator._session_idle_seconds = 1.0

    await coordinator.on_start()
    await coordinator.on_audio(b"new-transcript")
    await entered.wait()
    await asyncio.sleep(0.02)

    assert len(coordinator._history) == 2
    await coordinator.close()


@pytest.mark.asyncio
async def test_audio_storage_is_bounded_without_blinding_vad() -> None:
    class RecordingDetector(Detector):
        def __init__(self) -> None:
            super().__init__([])
            self.received = bytearray()
            self.decisions: list[tuple[VADDecision, ...]] = []

        def push(self, pcm16: bytes) -> tuple[VADDecision, ...]:
            self.received.extend(pcm16)
            return tuple(self.decisions.pop(0)) if self.decisions else ()

    detector = RecordingDetector()
    output = Output()
    coordinator = TurnCoordinator(
        sink=Sink(),
        asr=ASR(),
        llm=LLM(),
        tts=TTS(),
        media=AudioStore(),
        output=output,
        media_base_url="http://andy.test:8900",
        system_prompt="You are Andy.",
        detector_factory=lambda: detector,
        max_audio_bytes=5,
        preroll_bytes=4,
    )
    await coordinator.on_start()
    await coordinator.on_audio(b"0123456789")

    # The detector sees every sample; before speech starts only a bounded
    # run-up is kept, so the recogniser is never handed the whole room.
    assert detector.received == b"0123456789"
    assert coordinator._audio == b""
    assert coordinator._preroll == b"6789"

    detector.decisions = [(VADDecision.SPEECH_STARTED,)]
    await coordinator.on_audio(b"abcdefgh")

    # On speech onset the retained run-up becomes the head of the utterance.
    assert coordinator._audio == b"efgh"
    assert coordinator._preroll == b""
    await coordinator.close()


@pytest.mark.asyncio
async def test_motion_is_not_dispatched_when_tts_fails() -> None:
    class BrokenTTS(TTS):
        async def synthesize(self, text: str, *, pace: float = 1.0) -> bytes:
            raise RuntimeError("unavailable")

    actions = Actions()
    coordinator, _, _, _, _, output = make_coordinator(
        [(VADDecision.SPEECH_STARTED, VADDecision.SPEECH_ENDED)],
        llm=LLM(
            {
                "kind": "motion",
                "reply": "I'll return home.",
                "motion": "home",
            }
        ),
        tts=BrokenTTS(),
        actions=actions,
    )

    await coordinator.on_start()
    await coordinator.on_audio(b"speech")
    await coordinator.wait_until_idle()

    assert actions.executed == []
    assert output.played == []
    await coordinator.close()


def test_speech_only_keeps_words_and_drops_room_descriptions() -> None:
    assert speech_only("[BLANK_AUDIO]") == ""
    assert speech_only("[SOUND]") == ""
    assert speech_only("(water running)") == ""
    assert speech_only("[Tapping] [Laughing]") == ""
    assert speech_only("  [typing] . ") == ""
    assert speech_only("(laughs) yes please") == "yes please"
    assert speech_only("Andy, what time is it?") == "Andy, what time is it?"


@pytest.mark.asyncio
async def test_room_noise_never_reaches_the_gate() -> None:
    asr = SequenceASR(["[BLANK_AUDIO]"])
    coordinator, _, _, llm, tts, output = make_coordinator(
        [(VADDecision.SPEECH_STARTED, VADDecision.SPEECH_ENDED)], asr=asr
    )

    await coordinator.on_start()
    await coordinator.on_audio(b"keyboard")
    await coordinator.wait_until_idle()

    assert llm.calls == 0
    assert tts.calls == 0
    assert output.played == []
    await coordinator.close()


@pytest.mark.asyncio
async def test_room_noise_cannot_cancel_an_answer_in_flight() -> None:
    """A passing noise must not take the floor from an answer being prepared.

    This is the failure that made Andy go quiet when spoken to: any non-empty
    recogniser output used to pre-empt the response already under way, so a
    keystroke landing while Andy was thinking silently discarded the reply.
    """

    synthesizing = asyncio.Event()
    release = asyncio.Event()

    class SlowTTS(TTS):
        async def synthesize(self, text: str, *, pace: float = 1.0) -> bytes:
            synthesizing.set()
            await release.wait()
            return await TTS.synthesize(self, text, pace=pace)

    class SignallingASR(SequenceASR):
        def __init__(self, texts: list[str]) -> None:
            super().__init__(texts)
            self.noise_seen = asyncio.Event()

        async def transcribe(self, pcm16_16k: bytes) -> str:
            text = await super().transcribe(pcm16_16k)
            if self.calls >= 2:
                self.noise_seen.set()
            return text

    asr = SignallingASR(["What time is it?", "[typing]"])
    coordinator, _, _, llm, tts, output = make_coordinator(
        [(VADDecision.SPEECH_STARTED, VADDecision.SPEECH_ENDED)],
        asr=asr,
        tts=SlowTTS(),
    )

    await coordinator.on_start()
    await coordinator.on_audio(b"question")
    await synthesizing.wait()

    await coordinator.on_start()
    await coordinator.on_audio(b"keystroke")
    await asr.noise_seen.wait()
    for _ in range(10):
        await asyncio.sleep(0)

    release.set()
    await coordinator.wait_until_idle()

    assert llm.calls == 1
    assert tts.texts == ["Hello from Andy."]
    assert output.played, "the answer that was in flight must still be spoken"
    await coordinator.close()


@pytest.mark.asyncio
async def test_ignored_speech_leaves_a_held_fragment_alone() -> None:
    asr = SequenceASR(["Hey Andy", "so anyway I told her no"])
    llm = SequenceLLM(
        [
            {"kind": "wait", "reply": None, "motion": None},
            {"kind": "ignore", "reply": None, "motion": None},
        ]
    )
    coordinator, _, _, _, _, _ = make_coordinator(
        [(VADDecision.SPEECH_STARTED, VADDecision.SPEECH_ENDED)],
        asr=asr,
        llm=llm,
    )

    await coordinator.on_start()
    await coordinator.on_audio(b"first")
    await coordinator.wait_until_idle()
    assert coordinator._pending_fragments == ["Hey Andy"]

    await coordinator.on_start()
    await coordinator.on_audio(b"someone else")
    await coordinator.wait_until_idle()

    assert coordinator._pending_fragments == ["Hey Andy"]
    await coordinator.close()


# --- the agent's half of a turn ------------------------------------------


class Agent:
    """A stand-in for the tool-using agent, with the seam the real one has."""

    def __init__(
        self,
        speech: str = "Done.",
        movement: MotionAction | None = None,
        able: tuple[str, ...] = ("set reminders and timers",),
        delay: float = 0.0,
    ) -> None:
        from andy.agent import AgentTurn

        self._turn = AgentTurn(speech=speech, movement=movement)
        self._able = able
        self._delay = delay
        self.transcripts: list[str] = []

    def capabilities(self) -> tuple[str, ...]:
        return self._able

    def situation(self) -> dict:
        return {}

    async def reply(self, transcript: str, history: list[dict[str, str]]):
        self.transcripts.append(transcript)
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._turn


@pytest.mark.asyncio
async def test_a_compound_request_reaches_the_agent_and_still_moves() -> None:
    """A reminder and a movement in one sentence must produce both.

    Routed as a motion, the movement runs and everything else is dropped: the
    agent that owns the scheduler is never asked. The gate is told to send
    these to reply instead, and the movement rides on the agent's answer.
    """
    actions = Actions()
    agent = Agent(speech="Reminder set, and looking left.",
                  movement=MotionAction.LOOK_LEFT)
    coordinator, _, _, llm, tts, output = make_coordinator(
        [(VADDecision.SPEECH_STARTED,), (VADDecision.SPEECH_ENDED,)],
        asr=ASR("Andy, remind me in ten minutes and look to your left."),
        llm=LLM({"kind": "reply", "reply": "Sure.", "motion": None}),
        actions=actions,
        conversation=agent,
    )

    await coordinator.on_start()
    await coordinator.on_audio(b"speech")
    await coordinator.on_audio(b"silence")
    await coordinator.wait_until_idle()
    await coordinator.wait_until_action_idle()

    # speech_only strips the trailing stop before the gate ever sees it.
    assert agent.transcripts == [
        "Andy, remind me in ten minutes and look to your left"
    ]
    assert tts.texts == ["Reminder set, and looking left."]
    assert actions.executed == [MotionAction.LOOK_LEFT]
    assert len(output.played) == 1
    await coordinator.close()


@pytest.mark.asyncio
async def test_the_agents_movement_goes_through_the_same_allowlist() -> None:
    actions = Actions()
    coordinator, *_ = make_coordinator(
        [(VADDecision.SPEECH_STARTED,), (VADDecision.SPEECH_ENDED,)],
        llm=LLM({"kind": "reply", "reply": "Sure.", "motion": None}),
        actions=actions,
        conversation=Agent(movement=MotionAction.DANCE),
    )
    await coordinator.on_start()
    await coordinator.on_audio(b"speech")
    await coordinator.on_audio(b"silence")
    await coordinator.wait_until_idle()
    await coordinator.wait_until_action_idle()

    authorized = [
        decision for decision, _ in actions.decisions
        if decision.kind is DecisionKind.MOTION
    ]
    assert [decision.action for decision in authorized] == [MotionAction.DANCE]
    await coordinator.close()


@pytest.mark.asyncio
async def test_speech_is_not_held_back_by_the_movement_it_starts() -> None:
    """Andy talks while he moves; he does not dance in silence first."""

    class SlowActions(Actions):
        def __init__(self) -> None:
            super().__init__()
            self.finished = False

        async def execute(self, action: MotionAction) -> str:
            await asyncio.sleep(0.2)
            self.finished = True
            return await super().execute(action)

    actions = SlowActions()
    coordinator, _, _, _, _, output = make_coordinator(
        [(VADDecision.SPEECH_STARTED,), (VADDecision.SPEECH_ENDED,)],
        llm=LLM({"kind": "reply", "reply": "Sure.", "motion": None}),
        actions=actions,
        conversation=Agent(movement=MotionAction.DANCE),
    )
    await coordinator.on_start()
    await coordinator.on_audio(b"speech")
    await coordinator.on_audio(b"silence")
    await coordinator.wait_until_idle()

    # Playback has already happened while the program is still running.
    assert len(output.played) == 1
    assert not actions.finished
    await coordinator.wait_until_action_idle()
    assert actions.executed == [MotionAction.DANCE]
    await coordinator.close()


@pytest.mark.asyncio
async def test_the_gate_is_told_what_andy_can_actually_do() -> None:
    """The gate answers for Andy whenever it does not call the agent.

    Without this it denied having a scheduler it was holding, so what it is
    told has to come from what is wired rather than from a fixed paragraph.
    """
    llm = LLM({"kind": "reply", "reply": "Sure.", "motion": None})
    coordinator, *_ = make_coordinator(
        [(VADDecision.SPEECH_STARTED,), (VADDecision.SPEECH_ENDED,)],
        llm=llm,
        actions=Actions(),
        conversation=Agent(able=("set reminders and timers",
                                 "look through his camera")),
    )
    await coordinator.on_start()
    await coordinator.on_audio(b"speech")
    await coordinator.on_audio(b"silence")
    await coordinator.wait_until_idle()

    system = llm.requests[0][0]["content"]
    assert "set reminders and timers" in system
    assert "look through his camera" in system
    assert "Never say Andy is unable" in system
    await coordinator.close()


@pytest.mark.asyncio
async def test_without_an_agent_the_gate_is_told_the_plain_truth() -> None:
    llm = LLM({"kind": "reply", "reply": "Sure.", "motion": None})
    coordinator, *_ = make_coordinator(
        [(VADDecision.SPEECH_STARTED,), (VADDecision.SPEECH_ENDED,)],
        llm=llm,
        actions=Actions(),
    )
    await coordinator.on_start()
    await coordinator.on_audio(b"speech")
    await coordinator.on_audio(b"silence")
    await coordinator.wait_until_idle()

    system = llm.requests[0][0]["content"]
    assert "He cannot set reminders" in system
    await coordinator.close()


@pytest.mark.asyncio
async def test_a_failing_agent_still_leaves_the_gates_reply_spoken() -> None:
    class Broken(Agent):
        async def reply(self, transcript, history):
            raise RuntimeError("model unavailable")

    coordinator, _, _, _, tts, output = make_coordinator(
        [(VADDecision.SPEECH_STARTED,), (VADDecision.SPEECH_ENDED,)],
        llm=LLM({"kind": "reply", "reply": "Gate answer.", "motion": None}),
        actions=Actions(),
        conversation=Broken(),
    )
    await coordinator.on_start()
    await coordinator.on_audio(b"speech")
    await coordinator.on_audio(b"silence")
    await coordinator.wait_until_idle()

    assert tts.texts == ["Gate answer."]
    assert len(output.played) == 1
    await coordinator.close()


@pytest.mark.asyncio
async def test_the_gate_can_sense_what_the_agent_can_sense() -> None:
    """The gate answers for Andy on every turn it does not hand over.

    Andy said he did not know the weather while the reading sat on the device
    and in the agent's instructions: the agent had failed its structured
    output, so the gate spoke instead, and the gate had never been told
    anything Andy could sense.
    """
    llm = LLM({"kind": "reply", "reply": "Sure.", "motion": None})

    class Sensing(Agent):
        def situation(self) -> dict:
            return {
                "weather_outside": "Haze, 31 degrees, humidity 75%",
                "where_andy_is": "Sharjah",
            }

    coordinator, *_ = make_coordinator(
        [(VADDecision.SPEECH_STARTED,), (VADDecision.SPEECH_ENDED,)],
        llm=llm,
        actions=Actions(),
        conversation=Sensing(),
    )
    await coordinator.on_start()
    await coordinator.on_audio(b"speech")
    await coordinator.on_audio(b"silence")
    await coordinator.wait_until_idle()

    system = llm.requests[0][0]["content"]
    assert "Haze, 31 degrees" in system
    assert "Sharjah" in system
    assert "rather than saying you do not know" in system
    await coordinator.close()
