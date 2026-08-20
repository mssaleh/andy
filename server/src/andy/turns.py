from __future__ import annotations

import asyncio
from array import array
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
import json
import logging
import re
from math import isqrt
import sys
from typing import Any, Protocol

from .actions import (
    ActionDecision,
    DecisionKind,
    MotionAction,
    motion_catalog_prompt,
    parse_agent_decision,
    resolve_calibrated_request,
)
from .events import DeviceEvent, EventKind, EventSink
from .media import AudioStore
from .vad import UtteranceDetector, VADDecision


log = logging.getLogger("andy.turns")


_NONSPEECH_ANNOTATION = re.compile(r"[\[(<][^\])>]*[\])>]")
_RESIDUE = " \t\r\n-\u2013\u2014.,;:*\"'"


def speech_only(transcript: str) -> str:
    """Drop the annotations Whisper writes when it hears no speech.

    The recogniser reports non-speech audio as bracketed labels -- [SOUND],
    [BLANK_AUDIO], [typing], (water running). They are descriptions of the
    room, not things anyone said, and a transcript made only of them carries no
    request. What survives the strip is what was actually spoken.
    """
    text = " ".join(_NONSPEECH_ANNOTATION.sub(" ", transcript).split())
    text = text.strip(_RESIDUE)
    # Question and exclamation marks survive the strip: they are how the gate
    # tells a question from a remark.
    return text if any(character.isalnum() for character in text) else ""


_VOICED = re.compile(r"voiced=(\d+)/(\d+)")
_NOISE = re.compile(r"noise=(\d+)")
_LOUD = re.compile(r"rms_p90=(\d+)")


def how_it_was_said(measured: str) -> str:
    """Describe an utterance acoustically, for a gate that only reads text.

    A mangled question addressed to Andy and a sentence from a television read
    the same on the page, and the gate was binning real questions as room
    noise. They do not sound the same: someone talking to Andy is voiced almost
    continuously and close to him, while a television across the room arrives
    in fragments well down toward the floor it sits in. Measured on one such
    exchange, the person ran 66% voiced at RMS 546 and the television 9% to 29%
    at 305 to 508.

    This is a hint and deliberately not a rule. It says how the room sounded,
    and the gate still decides.
    """
    voiced = _VOICED.search(measured)
    noise = _NOISE.search(measured)
    loud = _LOUD.search(measured)
    if voiced is None or int(voiced.group(2)) == 0:
        return ""
    fraction = int(voiced.group(1)) / int(voiced.group(2))
    above = None
    if noise is not None and loud is not None and int(noise.group(1)) > 0:
        above = int(loud.group(1)) / int(noise.group(1))

    if fraction >= 0.5 and (above is None or above >= 1.5):
        return (
            "This was said almost continuously and close to Andy, which is how "
            "someone speaking to him sounds rather than a television."
        )
    if fraction < 0.25:
        return (
            "This arrived in fragments and mostly near the level of the room, "
            "which is how a television or a distant conversation sounds."
        )
    return "This was neither close and continuous nor plainly distant."


def _pcm16_metrics(data: bytes) -> tuple[float, int, int]:
    samples = array("h")
    samples.frombytes(data[: len(data) - (len(data) % 2)])
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        return 0.0, 0, 0
    peak = max(abs(sample) for sample in samples)
    rms = isqrt(sum(sample * sample for sample in samples) // len(samples))
    return len(samples) / 16_000, rms, peak


DECISION_PROMPT = """
You are Andy's turn manager as well as his conversational intelligence. The
microphone is active whenever Andy is not speaking, so a transcript can be a
direct request, a continuation of the current conversation, background speech,
or incidental room noise. Decide what Andy should do.

Return exactly one JSON object and no markdown:
- {"kind":"ignore","reply":null,"motion":null} when the speech is not
  directed to Andy, is only noise, or does not warrant a reply.
- {"kind":"wait","reply":null,"motion":null} when the text plausibly is for
  Andy but is only an incomplete fragment that needs the next transcription.
- {"kind":"end_context","reply":null,"motion":null} when the conversational
  exchange has naturally ended; this clears context but keeps listening active.
- {"kind":"reply","reply":"short spoken answer","motion":null} for normal
  conversation directed to Andy.
- {"kind":"motion","reply":"short spoken acknowledgement","motion":"NAME"}
  when the request is a calibrated movement and nothing else.
Use motion only on a motion decision. Every other kind takes "motion":null; the
movement for a reply is decided after this step, not here.

- {"kind":"sleep","reply":"short acknowledgement","motion":null} only when
  the user explicitly asks Andy to stop listening. Do not use sleep merely
  because a transcript is noisy, nonsensical, unrelated, or says goodbye.

The calibrated motion catalog is:
{motion_catalog}

Choose reply, not motion, when the speech asks for a movement *and* something
else -- a reminder, a question, a fact to remember, anything Andy can look up or
look at. Reply routes the whole request to Andy's full abilities, which can move
him as well; motion routes only the movement and silently drops the rest.

Never say Andy is unable to do something that appears in the list of what he can
do below. If a request needs one of those abilities, choose reply and let them
answer it.

An exact natural-language request for a catalog motion is supported even when it
uses the catalog's documented angle instead of its internal name. Select motion
immediately without asking for confirmation. In particular, 30 degrees right is
look_right, 30 degrees left is look_left, and 30 degrees up is look_up. Never
approximate an unsupported angle, invent servo values or motion names, or combine
motions. For an unsupported angle, reply with the supported calibrated choice and
do not select a motion. A motion acknowledgement states what Andy will do; it is
not a question. Replies must be one or two concise sentences suitable for speech.

Each transcript may carry a note about how it sounded, measured rather than
guessed. Speech that was continuous and close is almost always someone talking
to Andy, even when the words came out mangled; speech that arrived in fragments
near the level of the room is usually a television. Weigh it with the words:
Andy has ignored real questions that the recogniser mangled, and answering
briefly is a smaller failure than sitting silent when someone asked.

Deciding whether speech is for Andy:
- Transcripts come from an imperfect recogniser in a real room. Judge intent
  through the errors rather than requiring the words to be right.
- Andy answers to Andy and the recogniser sometimes mangles the name.
  Anything that reasonably sounds like Andy being addressed by name.
- A question or an instruction aimed at "you", with no other person named, is
  addressed to Andy. Answer it. Being unsure who a question was for is not a
  reason to say nothing; answering briefly is the better failure.
- Reserve ignore for what is genuinely not addressed to Andy: two other people
  talking to each other, speech about Andy in the third person, a stray
  fragment with no request in it, or a transcript that is plainly a
  misrecognition of room noise rather than words.
""".strip()

DECISION_REPAIR_PROMPT = """
Your preceding answer did not satisfy Andy's decision protocol. Return only one
JSON object with exactly these keys: kind, reply, motion. kind must be one of
ignore, wait, end_context, reply, motion, sleep. reply and motion must be JSON
null when unused. A motion value must be one of the motion names in the system
instructions. Do not add markdown or explanation.
""".strip()


class ASRProvider(Protocol):
    async def transcribe(self, pcm16_16k: bytes) -> str: ...


class LLMProvider(Protocol):
    async def complete(self, messages: list[dict[str, str]]) -> str: ...


class TTSProvider(Protocol):
    async def synthesize(self, text: str, *, pace: float = 1.0) -> bytes: ...


class Conversation(Protocol):
    """The tool-using agent, run only on what survives the gate."""

    async def reply(
        self, transcript: str, history: list[dict[str, str]]
    ) -> Any: ...

    def capabilities(self) -> tuple[str, ...]: ...

    def situation(self) -> dict[str, Any]: ...


class ActionHandler(Protocol):
    def authorize(
        self, decision: ActionDecision, transcript: str
    ) -> ActionDecision: ...

    async def execute(self, action: MotionAction) -> str: ...

    async def stop_passive(self) -> None: ...

    def snapshot(self) -> dict[str, object]: ...


class ResponseOutput(Protocol):
    async def play_announcement(self, url: str) -> None: ...

    async def stop_announcement(self) -> None: ...


class Detector(Protocol):
    @property
    def speech_started(self) -> bool: ...

    @property
    def has_transcribable_speech(self) -> bool: ...

    def push(self, pcm16: bytes) -> tuple[VADDecision, ...]: ...

    def finish(self) -> VADDecision: ...


class TurnState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"


@dataclass(frozen=True, slots=True)
class TurnTimeouts:
    asr_seconds: float = 20.0
    llm_seconds: float = 45.0
    tts_seconds: float = 30.0


class TurnCoordinator:
    """Segment continuous capture and process utterances outside that stream."""

    def __init__(
        self,
        *,
        sink: EventSink,
        asr: ASRProvider,
        llm: LLMProvider,
        tts: TTSProvider,
        media: AudioStore,
        output: ResponseOutput,
        media_base_url: str,
        system_prompt: str,
        detector_factory: Callable[[], Detector] = UtteranceDetector,
        timeouts: TurnTimeouts | None = None,
        history_turns: int = 8,
        session_idle_seconds: float = 180.0,
        max_pending_chars: int = 1_000,
        max_audio_bytes: int = 16_000 * 2 * 16,
        preroll_bytes: int = 16_000 * 2 // 2,
        actions: ActionHandler | None = None,
        conversation: Conversation | None = None,
        effects=None,
    ) -> None:
        self._sink = sink
        self._asr = asr
        self._llm = llm
        self._tts = tts
        self._media = media
        self._output = output
        self._media_base_url = media_base_url.rstrip("/")
        self._system_prompt = system_prompt
        self._detector_factory = detector_factory
        self._timeouts = timeouts or TurnTimeouts()
        if history_turns < 0:
            raise ValueError("history_turns cannot be negative")
        if session_idle_seconds < 15.0:
            raise ValueError("session_idle_seconds cannot be less than 15")
        if max_audio_bytes < 1:
            raise ValueError("max_audio_bytes must be positive")
        if max_pending_chars < 1:
            raise ValueError("max_pending_chars must be positive")
        if not 0 < preroll_bytes <= max_audio_bytes:
            raise ValueError("preroll_bytes must fit inside max_audio_bytes")
        self._history_turns = history_turns
        self._session_idle_seconds = session_idle_seconds
        self._max_audio_bytes = max_audio_bytes
        self._max_pending_chars = max_pending_chars
        self._actions = actions
        self._conversation = conversation
        self._effects = effects

        self.state = TurnState.IDLE
        self._capture_generation = 0
        self._run_open = False
        self._audio = bytearray()
        self._preroll = bytearray()
        self._preroll_bytes = preroll_bytes
        self._speech_open = False
        self._detector: Detector | None = None
        self._response_generation = 0
        self._active_response_generation = 0
        self._response_task: asyncio.Task[None] | None = None
        self._utterance_tasks: set[asyncio.Task[None]] = set()
        self._action_task: asyncio.Task[None] | None = None
        self._session_expiry_handle: asyncio.TimerHandle | None = None
        self._history: list[dict[str, str]] = []
        self._pending_fragments: list[str] = []
        self._fragment_generation = 0

    async def on_start(self) -> int:
        if self._run_open:
            self._finish_capture(self._capture_generation, send_run_end=True)
        self._capture_generation += 1
        self._run_open = True
        self.state = TurnState.LISTENING
        self._audio.clear()
        self._preroll.clear()
        self._speech_open = False
        self._detector = self._detector_factory()
        self._emit(EventKind.RUN_START)
        self._emit(EventKind.STT_START)
        return 0

    async def on_audio(self, data: bytes, data2: bytes | None = None) -> None:
        del data2
        if self.state is not TurnState.LISTENING or self._detector is None:
            return
        decisions = self._detector.push(data)
        if self._speech_open:
            remaining = self._max_audio_bytes - len(self._audio)
            if remaining > 0:
                self._audio.extend(data[:remaining])
        else:
            # Before speech begins, keep only a short run-up. Handing the
            # recogniser the whole window makes it transcribe minutes of room
            # around a moment of speech, which is what it reports back as
            # [BLANK_AUDIO].
            self._preroll.extend(data)
            excess = len(self._preroll) - self._preroll_bytes
            if excess > 0:
                del self._preroll[:excess]
            if VADDecision.SPEECH_STARTED in decisions:
                self._speech_open = True
                self._audio.extend(self._preroll[: self._max_audio_bytes])
                self._preroll.clear()
        await self._apply_vad_decisions(decisions)

    async def on_stop(self, abort: bool) -> None:
        if not self._run_open:
            return
        if abort:
            self._finish_capture(self._capture_generation, send_run_end=False)
            return
        if self._detector is not None:
            await self._apply_vad_decisions((self._detector.finish(),))

    async def on_disconnect(self) -> None:
        self._finish_capture(self._capture_generation, send_run_end=False)
        await self._cancel_response(stop_output=True)
        await self._cancel_action()
        await self._cancel_session_expiry()
        self._pending_fragments.clear()
        self._history.clear()

    async def close(self) -> None:
        await self.on_disconnect()

    async def wait_until_idle(self, timeout: float = 60.0) -> None:
        tasks = list(self._utterance_tasks)
        if self._action_task is not None:
            tasks.append(self._action_task)
        if tasks:
            await asyncio.wait_for(
                asyncio.gather(
                    *(asyncio.shield(task) for task in tasks),
                    return_exceptions=True,
                ),
                timeout=timeout,
            )

    async def wait_until_action_idle(self, timeout: float = 30.0) -> None:
        task = self._action_task
        if task is not None:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)

    async def _apply_vad_decisions(
        self, decisions: tuple[VADDecision, ...]
    ) -> None:
        for decision in decisions:
            if self.state is not TurnState.LISTENING:
                return
            if decision is VADDecision.SPEECH_STARTED:
                self._emit(EventKind.STT_VAD_START)
                continue
            if decision is VADDecision.SPEECH_ENDED:
                await self._finalize_utterance()
                return
            if decision is VADDecision.NO_SPEECH_TIMEOUT:
                self._finish_capture(
                    self._capture_generation, send_run_end=True
                )
                return
            if decision is VADDecision.MAX_DURATION:
                if self._detector and self._detector.has_transcribable_speech:
                    await self._finalize_utterance()
                else:
                    self._finish_capture(
                        self._capture_generation, send_run_end=True
                    )
                return

    async def _finalize_utterance(self) -> None:
        audio = bytes(self._audio)
        measured = getattr(self._detector, "capture_summary", "vad=off")
        self._finish_capture(self._capture_generation, send_run_end=True)
        self._response_generation += 1
        generation = self._response_generation
        task = asyncio.create_task(
            self._process_utterance(generation, audio, measured),
            name=f"andy-response-{generation}",
        )
        self._utterance_tasks.add(task)
        task.add_done_callback(self._utterance_tasks.discard)

    async def _process_utterance(
        self, generation: int, audio: bytes, measured: str = "vad=off"
    ) -> None:
        decision: ActionDecision | None = None
        transcript = ""
        playback_task: asyncio.Task[None] | None = None
        try:
            raw_transcript = (
                await asyncio.wait_for(
                    self._asr.transcribe(audio),
                    timeout=self._timeouts.asr_seconds,
                )
            ).strip()
            duration, rms, peak = _pcm16_metrics(audio)
            transcript = speech_only(raw_transcript)
            if not transcript:
                log.info(
                    "discarded segment with no speech in it "
                    "(audio=%.2fs rms=%d peak=%d %s stt=%r)",
                    duration,
                    rms,
                    peak,
                    measured,
                    raw_transcript[:60],
                )
                return
            log.info(
                "ASR accepted transcript "
                "(audio=%.2fs rms=%d peak=%d %s chars=%d)",
                duration,
                rms,
                peak,
                measured,
                len(transcript),
            )
            self._schedule_session_expiry()

            combined_transcript = " ".join(
                [*self._pending_fragments, transcript]
            ).strip()
            if len(combined_transcript) > self._max_pending_chars:
                self._pending_fragments.clear()
                log.info("discarded overlong pending transcript")
                return

            decision = await self._gate_decision(
                combined_transcript,
                self._history[-self._history_turns * 2 :]
                if self._history_turns
                else [],
                heard=how_it_was_said(measured),
            )
            if self._actions is not None:
                decision = self._actions.authorize(decision, combined_transcript)
            if decision.kind is DecisionKind.IGNORE:
                # Not for Andy. It must not disturb anything already in
                # progress: it never took the floor, and a held fragment
                # belongs to whoever was mid-sentence, not to this.
                log.info("gate ignored transcript: %r", transcript[:160])
                return
            if decision.kind is DecisionKind.WAIT:
                if generation > self._fragment_generation:
                    self._fragment_generation = generation
                    self._pending_fragments.append(transcript)
                    self._schedule_session_expiry()
                    log.info(
                        "retained incomplete transcript fragment: %r",
                        transcript[:160],
                    )
                return

            # Everything below speaks or moves, so it needs the floor. Claiming
            # it here rather than on arrival is what stops a passing noise from
            # cancelling an answer that is already being prepared.
            if not await self._claim_response(generation):
                log.info("discarded stale transcript after a newer utterance")
                return
            self._schedule_session_expiry()

            if decision.kind is DecisionKind.CONTEXT_END:
                self._pending_fragments.clear()
                self._history.clear()
                await self._cancel_session_expiry()
                return
            self._pending_fragments.clear()
            if decision.kind is DecisionKind.SESSION_END:
                if self._actions is not None:
                    await self._actions.stop_passive()
                await self._cancel_session_expiry()
                self._history.clear()

            reply = (decision.reply or "").strip()
            agent_movement: MotionAction | None = None
            agent_feeling = ""
            if (
                decision.kind is DecisionKind.CHAT
                and self._conversation is not None
            ):
                # The gate has decided this is worth answering. Only now is it
                # worth spending a tool-using agent turn on it: the microphone
                # hears the whole room, and most of what it hears is not for
                # Andy. If the agent fails, the gate's own reply still stands.
                try:
                    turn = await asyncio.wait_for(
                        self._conversation.reply(
                            combined_transcript,
                            self._history[-self._history_turns * 2 :]
                            if self._history_turns
                            else [],
                        ),
                        timeout=self._timeouts.llm_seconds,
                    )
                    agent_reply = (getattr(turn, "speech", "") or "").strip()
                    agent_feeling = getattr(turn, "feeling", "") or ""
                    if agent_reply:
                        reply = agent_reply
                    # The agent moves by naming a movement in its answer rather
                    # than by waiting on a motion program, so speech and body
                    # are dispatched together below exactly as the gate's own
                    # motion decision is.
                    chosen = getattr(turn, "movement", None)
                    if chosen is not None and self._actions is not None:
                        agent_movement = self._actions.authorize(
                            ActionDecision(
                                kind=DecisionKind.MOTION, action=chosen
                            ),
                            combined_transcript,
                        ).action
                except (TimeoutError, asyncio.TimeoutError):
                    log.warning("agent timed out; using the gate's reply")
                except Exception:
                    log.exception("agent failed; using the gate's reply")
            if not reply:
                raise RuntimeError("agent decision omitted its spoken response")
            # The face already wears the feeling; the voice should carry it
            # too, or Andy sounds identical delighted and sorry.
            from .effects import speech_pace

            wav = await asyncio.wait_for(
                self._tts.synthesize(reply, pace=speech_pace(agent_feeling)),
                timeout=self._timeouts.tts_seconds,
            )
            if not wav:
                raise RuntimeError("speech synthesizer returned empty audio")
            key = self._media.put(wav, "audio/wav")
            url = f"{self._media_base_url}/tts/{key}.wav"
            log.info(
                "response synthesized: kind=%s action=%s chars=%d bytes=%d "
                "media_key=%s",
                decision.kind.value,
                decision.action.value if decision.action is not None else "none",
                len(reply),
                len(wav),
                key,
            )

            if decision.kind is not DecisionKind.SESSION_END:
                self._remember(combined_transcript, reply)
            playback_task = asyncio.create_task(
                self._output.play_announcement(url),
                name=f"andy-playback-{generation}",
            )
            if (
                decision.kind is DecisionKind.MOTION
                and decision.action is not None
                and self._effects is not None
            ):
                # A movement the gate authorised never reaches the agent, so
                # nothing would otherwise change the face for it.
                await self._effects.wear_for_motion(decision.action.value)
            movement = (
                decision.action
                if decision.kind is DecisionKind.MOTION
                else agent_movement
            )
            if movement is not None and self._actions is not None:
                await self._cancel_action()
                self._action_task = asyncio.create_task(
                    self._execute_action(movement),
                    name=f"andy-action-{generation}-{movement.value}",
                )
            await playback_task
            if decision.kind is not DecisionKind.SESSION_END:
                self._schedule_session_expiry()
        except asyncio.CancelledError:
            raise
        except TimeoutError as exc:
            log.warning("utterance provider timed out: %s", exc)
        except ValueError as exc:
            log.warning("unsafe or malformed LLM decision ignored: %s", exc)
        except Exception:
            log.exception("utterance processing failed")
        finally:
            if playback_task is not None and not playback_task.done():
                playback_task.cancel()
                with suppress(asyncio.CancelledError):
                    await playback_task
            if self._response_task is asyncio.current_task():
                self._response_task = None

    async def _claim_response(self, generation: int) -> bool:
        current = asyncio.current_task()
        if current is None or generation <= self._active_response_generation:
            return False
        self._active_response_generation = generation
        previous = self._response_task
        self._response_task = current
        if previous is not None and not previous.done() and previous is not current:
            previous.cancel()
            with suppress(asyncio.CancelledError):
                await previous
        return (
            self._response_task is current
            and self._active_response_generation == generation
        )

    async def _execute_action(self, action: MotionAction) -> None:
        try:
            if self._actions is not None:
                await self._actions.execute(action)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("motion did not complete: %s", action, exc_info=True)
        finally:
            if self._action_task is asyncio.current_task():
                self._action_task = None

    def _agent_system_prompt(self) -> str:
        decision_prompt = DECISION_PROMPT.replace(
            "{motion_catalog}", motion_catalog_prompt()
        )
        prompt = f"{self._system_prompt}\n\n{decision_prompt}"
        prompt = f"{prompt}\n\n{self._capability_prompt()}"
        prompt = f"{prompt}\n\n{self._situation_prompt()}"
        if self._actions is None:
            return prompt
        runtime = json.dumps(
            self._actions.snapshot(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return (
            f"{prompt}\n\nCurrent trusted runtime state (telemetry only; "
            f"never copy counters into speech):\n{runtime}"
        )

    def _situation_prompt(self) -> str:
        """The same facts the agent gets, for the half of the turns it misses.

        Andy answered that he did not know the weather while the reading was on
        the device and in the agent's instructions: the agent had failed its
        structured output, the gate spoke instead, and the gate had never been
        told anything it could sense.
        """
        facts = (
            self._conversation.situation()
            if self._conversation is not None
            else {}
        )
        if not facts:
            return "You cannot sense anything about the room at the moment."
        lines = "\n".join(
            f"- {key}: {value}" for key, value in sorted(facts.items())
        )
        return (
            "What Andy can sense right now. Answer from these rather than "
            "saying you do not know:\n" + lines
        )

    def _capability_prompt(self) -> str:
        """Tell the gate what Andy can do, from what is actually wired.

        The gate speaks for Andy on every turn it does not hand to the agent,
        so anything it does not know about is something Andy will deny having.
        Asked for a reminder it answered "I can't set timers" while holding a
        working scheduler, because this list did not exist.
        """
        able = (
            self._conversation.capabilities()
            if self._conversation is not None
            else ()
        )
        if not able:
            return (
                "Andy can move and speak. He cannot set reminders, remember "
                "anything, or see."
            )
        return "What Andy can do, beyond moving and speaking:\n" + "\n".join(
            f"- {item}" for item in able
        )

    async def _gate_decision(
        self,
        transcript: str,
        history: list[dict[str, str]],
        heard: str = "",
    ) -> ActionDecision:
        """Decide what to do with a sentence: the router first, then the gate.

        One path, used by a heard utterance and by the control API alike. The
        gate is where a real defect lived -- it answers for Andy on every turn
        it does not hand over, and it was answering blind -- so a second copy
        of this for testing would be a copy that does not have the bug.
        """
        decision = (
            resolve_calibrated_request(transcript)
            if self._actions is not None
            else None
        )
        if decision is not None:
            log.info(
                "deterministic calibrated request resolved: kind=%s action=%s",
                decision.kind,
                decision.action,
            )
            return decision
        messages = [
            {"role": "system", "content": self._agent_system_prompt()}
        ]
        messages.extend(history)
        messages.append(
            {
                "role": "user",
                "content": (
                    f"{transcript}\n\n[how it sounded: {heard}]"
                    if heard
                    else transcript
                ),
            }
        )
        return await self._request_agent_decision(messages)

    async def consider(self, transcript: str) -> ActionDecision:
        """What Andy would make of a sentence, with no voice in the room.

        The same router and the same gate a spoken sentence meets, on the same
        prompt, without the audio around it. Nothing is authorised, spoken or
        moved here: the caller decides whether to act on what comes back.
        """
        text = speech_only(transcript)
        if not text:
            return ActionDecision(kind=DecisionKind.IGNORE)
        return await self._gate_decision(text, [])

    async def _request_agent_decision(
        self, messages: list[dict[str, str]]
    ) -> ActionDecision:
        async with asyncio.timeout(self._timeouts.llm_seconds):
            raw = await self._llm.complete(messages)
            try:
                return parse_agent_decision(raw)
            except ValueError as first_error:
                log.warning(
                    "requesting one bounded repair for malformed agent decision: %s",
                    first_error,
                )
                repair_messages = [
                    *messages,
                    {"role": "assistant", "content": raw[:2_000]},
                    {"role": "user", "content": DECISION_REPAIR_PROMPT},
                ]
                repaired = await self._llm.complete(repair_messages)
                return parse_agent_decision(repaired)

    def _remember(self, transcript: str, reply: str) -> None:
        self._history.extend(
            [
                {"role": "user", "content": transcript},
                {"role": "assistant", "content": reply},
            ]
        )
        if self._history_turns:
            self._history = self._history[-self._history_turns * 2 :]
        else:
            self._history.clear()

    def _schedule_session_expiry(self) -> None:
        handle = self._session_expiry_handle
        if handle is not None:
            handle.cancel()
        self._session_expiry_handle = asyncio.get_running_loop().call_later(
            self._session_idle_seconds, self._expire_session
        )

    def _expire_session(self) -> None:
        self._session_expiry_handle = None
        self._pending_fragments.clear()
        self._history.clear()
        log.info(
            "transcript and conversation context expired after %.1fs of silence",
            self._session_idle_seconds,
        )

    async def _cancel_session_expiry(self) -> None:
        handle = self._session_expiry_handle
        if handle is not None:
            handle.cancel()
            self._session_expiry_handle = None

    async def _cancel_response(self, *, stop_output: bool) -> None:
        current = asyncio.current_task()
        tasks = [
            task
            for task in self._utterance_tasks
            if not task.done() and task is not current
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._response_task in tasks:
            self._response_task = None
        if stop_output:
            await self._output.stop_announcement()

    async def _cancel_action(self) -> None:
        task = self._action_task
        if task is None or task.done() or task is asyncio.current_task():
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        if self._action_task is task:
            self._action_task = None

    def _finish_capture(self, generation: int, *, send_run_end: bool) -> None:
        if generation != self._capture_generation or not self._run_open:
            return
        self._run_open = False
        self.state = TurnState.IDLE
        self._detector = None
        self._audio.clear()
        self._preroll.clear()
        self._speech_open = False
        if send_run_end:
            self._emit(EventKind.RUN_END)

    def _emit(
        self, kind: EventKind, data: dict[str, str] | None = None
    ) -> None:
        self._sink.emit(DeviceEvent(kind, data or {}))
