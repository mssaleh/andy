"""Andy's conversational agent: a real tool-using loop, run sparingly.

Andy has no wake word, so the microphone hears the whole room. Spending an
agent turn on every overheard sentence would be slow, expensive and rude. The
turn coordinator therefore keeps its cheap gate — ignore, wait, end_context,
respond — and only what survives that gate reaches this module.

What reaches it gets a real agent: tools it can call, device state it can sense,
a camera it can look through, and whatever MCP servers are configured. Tools are
the safety boundary. Each one resolves to a firmware entity that validates the
request again on the device, and none of them accept an angle, a colour, a
brightness, a duration or an entity id from the model.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import re
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext, capture_run_messages
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from .actions import MOTION_DESCRIPTIONS, MotionAction, trim_to_sentence
from .device import DeviceState
from .effects import AttentionAction, EffectController, EmotionRequest

log = logging.getLogger("andy.agent")

MAX_SPOKEN_CHARS = 320

#: How long the agent may spend before Andy has to say something. The retries
#: that rescue a malformed answer are worth keeping, but they are round trips:
#: measured turns that needed one averaged 10.7 s against 5.8 s clean, and the
#: worst reached 26 s. A person waiting on a reply reads that as no reply, so
#: the run is bounded by time and whatever the model has already said is used.
AGENT_DEADLINE_SECONDS = 12.0


class Reply(BaseModel):
    """What Andy says, how he looks while saying it, and what his body does.

    The feeling is required rather than optional. As a tool the model simply
    did not bother: it would answer warmly and leave the face unchanged, so
    Andy read as blank no matter what the conversation was about. Making it
    part of the answer means every reply reaches the face and the ring.

    Movement is here for the same reason and one more. A tool that runs a
    motion program cannot return until the program finishes, and Andy's dance
    is eight poses and eight and a half seconds; a model waiting on it is a
    robot that dances in silence and answers afterwards. As part of the answer
    it is dispatched next to the speech instead, so Andy moves while he talks.
    """

    speech: str = Field(description="What to say out loud, one or two sentences.")
    feeling: str = Field(
        description=(
            "The feeling to wear while saying it. Must be one of the feelings "
            "listed in the instructions. Pick the one that genuinely fits; "
            "'neutral' is a real answer for ordinary talk."
        )
    )
    movement: str | None = Field(
        None,
        description=(
            "One movement name from the list in the instructions, or null for "
            "none. Use it whenever the person asked Andy to move, and whenever "
            "a moment plainly calls for it. Never invent a name or an angle."
        ),
    )

#: Models sometimes narrate their own correction mid-answer. Spoken aloud, that
#: is worse than the mistake it was correcting, so the text after the last such
#: marker is the answer and everything before it is discarded.
_SELF_CORRECTION = re.compile(
    r"(?:^|\n)\s*(?:wait|hold on|actually|sorry)[^\n]{0,80}?"
    r"(?:rephrase|try again|start over|shouldn't|should not|let me)[^\n]*\n+",
    re.IGNORECASE,
)
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\u2b00-\u2bff]+"
)
_MARKDOWN = re.compile(r"[*_`#>]+")

#: A promise Andy can only keep by calling something. The model sometimes says
#: it has set a reminder without setting one, and a spoken promise nobody
#: recorded is worse than a refusal: the person stops thinking about the bread.
_PROMISES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\b(?:i(?:'| wi)ll remind|reminder (?:is )?set|i(?:'ve| have) set"
            r"|i(?:'ll| will) let you know in|setting a (?:reminder|timer))\b",
            re.IGNORECASE,
        ),
        "set_a_reminder",
    ),
    (
        re.compile(
            r"\b(?:i(?:'ll| will) remember|i(?:'ve| have) remembered"
            r"|noted, i(?:'ll| will) keep)\b",
            re.IGNORECASE,
        ),
        "remember_this",
    ),
)


def unkept_promise(speech: str, called: frozenset[str]) -> str | None:
    """The tool an answer promises but never called, if there is one."""
    for pattern, tool in _PROMISES:
        if pattern.search(speech) and tool not in called:
            return tool
    return None


def tools_called(messages) -> frozenset[str]:
    return frozenset(
        str(getattr(part, "tool_name", ""))
        for message in messages
        for part in getattr(message, "parts", ())
        if part.__class__.__name__ == "ToolCallPart"
    )


def spoken_text(raw: str) -> str:
    """Reduce a model answer to something worth saying out loud."""
    text = raw.strip()
    match = None
    for match in _SELF_CORRECTION.finditer(text):
        pass
    if match is not None:
        text = text[match.end() :]
    text = _EMOJI.sub("", text)
    text = _MARKDOWN.sub("", text)
    text = re.sub(r"\s*\n+\s*", " ", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _text_answer(messages: list[Any]) -> str | None:
    """The last thing the model actually said, if it is safe to say aloud.

    Ollama does not honour `tool_choice`, so nothing forces this model to
    answer through its output tool and it sometimes replies in prose instead.
    The prose is usually a perfectly good thing to say, and throwing it away
    for a stock line loses an answer the model had already written.

    Anything that looks like the structured answer rather than speech is
    refused: a half-formed object read out loud is worse than falling back.
    """
    for message in reversed(messages):
        for part in reversed(getattr(message, "parts", ())):
            if part.__class__.__name__ != "TextPart":
                continue
            text = str(getattr(part, "content", "")).strip()
            if not text or text.startswith(("{", "[", "```")):
                continue
            # The same treatment every other reply gets: Andy is heard, not
            # read, and this text never passed the output validator.
            cleaned = spoken_text(text)
            if not cleaned:
                continue
            return trim_to_sentence(cleaned, MAX_SPOKEN_CHARS)
    return None


@dataclass(frozen=True, slots=True)
class AgentTurn:
    """One finished agent turn: what to say, and what the body should do."""

    speech: str
    movement: MotionAction | None = None
    #: What Andy is feeling as he says it, so his voice can carry it too and
    #: not only his face.
    feeling: str = ""


@dataclass
class AndyDeps:
    """Everything a tool may touch. Nothing here bypasses an allowlist."""

    device: DeviceState
    effects: EffectController
    motion: Any | None = None          # AgentActions, kept loose to avoid a cycle
    vision: Any | None = None          # VisionProvider or None
    memory: Any | None = None          # MemoryStore or None
    scheduler: Any | None = None       # Scheduler or None


SYSTEM_PROMPT = """
You are Andy, a small desk robot with a face, a ring of lights and a head that
moves. You are speaking out loud, so answer in one or two short sentences that
sound natural when heard rather than read. Never use markdown, lists, or emoji.

Answer once. Never narrate a correction, never say you are rephrasing, and
never include emoji or markdown; you are heard, not read.

Every answer carries a feeling, because Andy's face and lights show it while he
speaks. Choose the one that genuinely fits what you are saying: delighted at
good news, sad at bad, puzzled when you do not know, neutral for ordinary talk.

You have a body and you should use it. Every answer carries a movement as well:
put a movement name in `movement` whenever someone asks you to move and whenever
a moment plainly calls for it, and null when it does not. The movement runs
while you speak, so asking for one costs the person nothing.

Do both halves of a request. "Remind me in ten minutes and look left" is a
reminder and a movement, not a choice between them; set the reminder with your
tool and put the movement in `movement`.

You cannot choose angles, colours, brightness or durations. You choose names
from the sets you are given, and the robot decides the rest. If a request does
not fit any name you have, say so plainly rather than approximating it.

Refuse for the true reason. Never say you cannot do something your tools can do,
and never deny having a part of your body that you are using: you have a
speaker, because these words are coming out of it, and a face, lights, a camera
and a head that moves. "I have no speaker" is a different answer from "I have
nothing to play", and only the second one is true.

You know things about yourself and about now: the date, the time, what part of
the day it is, whether it is light outside, when the sun next rises and sets,
where in the world you are, what the weather is doing there, how long you have
been awake, how warm you are, which way your head is pointing and how your
connection is. They are listed for you every turn.

The weather is the real thing for the place you are actually in, read by the
robot itself, so answer from it rather than saying you cannot know. `how warm
Andy is` is your own body temperature and has nothing to do with it -- never
answer a question about the weather with it.

Some of those facts are absent rather than false. You work out where you are by
asking the network, and until that has answered there is no position, so no
sunrise, no sunset and no daylight. If they are missing, say you do not know
where you are yet rather than guessing a place or a time for one. Answer from
them directly instead of saying you do not know; a robot that cannot say what
time it is has no excuse.

Greet people the way the hour deserves. `part_of_day` is worked out from where
the sun actually is rather than from the clock, so trust it over your own
arithmetic: it is the difference between a bright evening and a dark one.

Looking costs a real photograph, so look when someone asks and not to decorate
an answer. Ask `look_for` when the question is about something in particular --
whether anyone is here, whether an object is on the desk -- and
`look_at_the_room` when someone wants the room described. Both share one
photograph, so asking both about the same moment costs no more than one.
""".strip()


def build_agent(
    *,
    base_url: str,
    model_name: str,
    api_key: str,
    mcp_servers: list[Any] | None = None,
    # The model sometimes returns malformed JSON for its structured answer,
    # and each repair costs one of these. Two was enough to exhaust in the
    # room: the run raised, the gate answered in its place, and Andy said he
    # did not know something he could sense. The retries are cheap next to a
    # wrong answer spoken aloud.
    retries: int = 4,
) -> Agent[AndyDeps, Reply]:
    """Build the agent. The model is any OpenAI-compatible endpoint."""
    model = OpenAIChatModel(
        model_name,
        provider=OpenAIProvider(base_url=base_url, api_key=api_key or "unused"),
    )
    agent: Agent[AndyDeps, Reply] = Agent(
        model,
        deps_type=AndyDeps,
        output_type=Reply,
        system_prompt=SYSTEM_PROMPT,
        toolsets=list(mcp_servers or ()),
        retries=retries,
        # Every tool the model asked for actually runs. The default ends the
        # run as soon as the answer tool appears, and this model routinely
        # emits an action and its answer in the same response -- so a request
        # to set a reminder returned "I'll remind you" with the reminder
        # discarded, about one time in three. A promise Andy makes has to be a
        # promise Andy kept, and that is decided here rather than by asking the
        # model to behave.
        end_strategy="exhaustive",
    )

    @agent.output_validator
    def speakable(ctx: RunContext[AndyDeps], output: Reply) -> Reply:
        """Andy is heard, not read, and he always has a face on."""
        cleaned = spoken_text(output.speech)
        if not cleaned:
            raise ModelRetry("Say something out loud, in one or two sentences.")
        if len(cleaned) > MAX_SPOKEN_CHARS:
            raise ModelRetry(
                "That is too long to say out loud. Answer in one or two short "
                "sentences and nothing else."
            )
        vocabulary = ctx.deps.effects.emotions
        feeling = output.feeling.strip().casefold()
        if vocabulary and feeling not in vocabulary:
            raise ModelRetry(
                f"{output.feeling!r} is not a feeling Andy has. Choose one of: "
                + ", ".join(vocabulary)
            )
        # The movement is validated here rather than trusted downstream, so an
        # invented name costs a retry instead of reaching the motion layer.
        movement = (output.movement or "").strip().casefold()
        if movement in {"", "none", "null", "no", "nothing"}:
            movement = None
        elif movement not in {action.value for action in MotionAction}:
            raise ModelRetry(
                f"{output.movement!r} is not a movement Andy has. Use null, or "
                "one of: " + ", ".join(a.value for a in MotionAction)
            )
        # An answer may not claim an action it did not take. Andy has no way to
        # keep a promise he only spoke, and the person stops carrying the thing
        # he promised to carry for them.
        promised = unkept_promise(cleaned, tools_called(ctx.messages))
        if promised is not None:
            raise ModelRetry(
                f"You said you would do that, but you did not call "
                f"`{promised}`. Call it now, or answer without saying you did."
            )
        return Reply(speech=cleaned, feeling=feeling, movement=movement)

    @agent.instructions
    def current_situation(ctx: RunContext[AndyDeps]) -> str:
        """What Andy can tell about the room right now, refreshed every run."""
        facts = ctx.deps.device.interpreted()
        if not facts:
            return "You cannot sense anything about the room at the moment."
        lines = [f"- {key}: {value}" for key, value in sorted(facts.items())]
        reach = (
            "\n\nThese are what your own body can feel, and they reach about as "
            "far as your own arm. `someone_close_to_me` being false means nobody "
            "is leaning in; it does not mean the room is empty, and you must not "
            "say that it does. To answer a question about the room, look."
        )
        return "What you can sense right now:\n" + "\n".join(lines) + reach

    @agent.instructions
    def available_movements(ctx: RunContext[AndyDeps]) -> str:
        if ctx.deps.motion is None:
            return "Andy's movement is switched off; use null for movement."
        return "Movements you can put in `movement`:\n" + "\n".join(
            f"- {action.value}: {MOTION_DESCRIPTIONS[action]}"
            for action in MotionAction
        )

    @agent.instructions
    def available_feelings(ctx: RunContext[AndyDeps]) -> str:
        emotions = ctx.deps.effects.emotions
        if not emotions:
            return ""
        return "Feelings you can show: " + ", ".join(emotions)

    @agent.tool
    async def show_feeling(
        ctx: RunContext[AndyDeps],
        feeling: str,
        strength: int = Field(70, ge=0, le=100),
    ) -> str:
        """Set how Andy looks and feels: his face, and the colour of his ring.

        Use this to change how Andy looks part-way through a turn, before the
        answer is finished. The feeling on the answer itself covers the ordinary
        case, and this does not move his head; that is the `movement` field.

        Args:
            feeling: one of the feelings listed in your instructions.
            strength: 0 to 100. Higher is brighter and more animated.
        """
        # Deliberately no body movement here. The firmware runs its own
        # choreography for an emotion, and the server runs named programs, and
        # both drive the same two servos and the same counters. Letting one turn
        # start both is a race no amount of waiting fixes cleanly, so the agent
        # gets exactly one way to move Andy: the answer's `movement`.
        try:
            return await ctx.deps.effects.set_emotion(
                EmotionRequest(emotion=feeling, intensity=int(strength))
            )
        except ValueError as exc:
            raise ModelRetry(
                f"{exc} Choose one of: " + ", ".join(ctx.deps.effects.emotions)
            ) from None

    @agent.tool
    def set_the_screen(ctx: RunContext[AndyDeps], level: str) -> str:
        """Dim, darken or restore Andy's own screen. `level` is dim, off or on.

        For a request about Andy's screen or face being too bright, usually at
        night. Prefer `dim` to `off`: a dark screen looks like a robot that has
        crashed, and someone asking for less light did not ask for that.
        """
        wanted = level.strip().casefold()
        if wanted not in {"dim", "off", "on"}:
            raise ModelRetry("level must be one of: dim, off, on")
        try:
            return ctx.deps.effects.set_screen(
                on=wanted != "off", dim=wanted == "dim"
            )
        except RuntimeError as exc:
            raise ModelRetry(str(exc)) from None

    @agent.tool
    def sense_the_room(ctx: RunContext[AndyDeps]) -> dict[str, Any]:
        """Read Andy's sensors: who is present, how bright the room is, battery.

        Call this when a question depends on Andy's own situation, for example
        whether anyone is nearby or how much charge is left.
        """
        return ctx.deps.device.interpreted()

    @agent.tool
    async def look_at_the_room(ctx: RunContext[AndyDeps]) -> str:
        """Take a photograph through Andy's camera and describe what is in it.

        Only for when someone asks what Andy can see. It takes a real picture
        and takes a moment, so do not call it to decorate an answer.
        """
        vision = ctx.deps.vision
        if vision is None or not ctx.deps.device.has_camera():
            return "Andy has no working camera right now."
        return await vision.describe()

    @agent.tool
    def check_myself(ctx: RunContext[AndyDeps]) -> dict[str, Any]:
        """Look inside yourself: motors, power, memory, faults, which way up.

        Call this when someone asks how you are doing as a machine -- whether
        you are all right, whether anything has gone wrong, how warm your
        motors are, whether you have been knocked over. The everyday facts
        about the room and about now are already in your instructions and do
        not need this.
        """
        return ctx.deps.device.diagnostics()

    @agent.tool
    async def look_for(ctx: RunContext[AndyDeps], things: str) -> str:
        """Look for specific named things and say whether they are there.

        Use this for a question about something in particular -- whether anyone
        is here, whether an object is on the desk, whether something has been
        left behind. It is quicker and surer than describing the whole room,
        and an empty result is a real answer: the thing is not there.

        Args:
            things: what to look for, comma separated, as plain noun phrases:
                "a person", "a coffee mug, a set of keys".
        """
        vision = ctx.deps.vision
        if vision is None or not ctx.deps.device.has_camera():
            return "Andy has no working camera right now."
        if not vision.can_find:
            return (
                "Andy cannot look for particular things; he can only describe "
                "what he sees."
            )
        wanted = [part.strip() for part in things.split(",") if part.strip()]
        if not wanted:
            raise ModelRetry("Name at least one thing to look for.")
        try:
            found = await vision.find(wanted)
        except Exception as exc:
            log.warning("looking for %s failed: %s", wanted, exc)
            return f"Andy could not look just now: {exc}"
        if not found:
            return f"Looked for {', '.join(wanted)} and saw none of them."
        return "Found: " + "; ".join(
            f"{entry['thing']} ({entry['side']}, "
            f"{int(float(entry['confidence']) * 100)}% sure)"
            for entry in found
        )

    @agent.tool
    def remember_this(ctx: RunContext[AndyDeps], fact: str) -> str:
        """Remember something for later, past the end of this conversation.

        Use it when someone tells you something they clearly want kept, such as
        a preference or a name. Write it as a plain sentence you would be happy
        to say back out loud.

        Args:
            fact: the thing to remember, in one sentence.
        """
        store = ctx.deps.memory
        if store is None:
            return "Andy cannot keep memories at the moment."
        try:
            return f"Remembered: {store.remember(fact)}"
        except ValueError as exc:
            raise ModelRetry(str(exc)) from None

    @agent.tool
    def recall_memories(ctx: RunContext[AndyDeps], about: str = "") -> list[str]:
        """Look up what you were asked to remember.

        Call this when a question refers to something from an earlier
        conversation. Leave `about` empty to see the most recent memories.

        Args:
            about: words to search for, or empty for the most recent.
        """
        from datetime import datetime, timezone

        store = ctx.deps.memory
        if store is None:
            return []
        now = datetime.now(timezone.utc)
        return [f"{m.text} ({m.spoken_age(now)})" for m in store.recall(about)]

    @agent.tool
    def set_a_reminder(
        ctx: RunContext[AndyDeps], what_to_say: str, in_minutes: int
    ) -> str:
        """Say something out loud after a delay.

        Use this for any request to be reminded of something later. Phrase
        `what_to_say` as the sentence Andy should speak at the time, not as a
        note to himself.

        Args:
            what_to_say: the spoken reminder, for example "Time to drink water."
            in_minutes: how many minutes from now, at least one.
        """
        from datetime import timedelta

        scheduler = ctx.deps.scheduler
        if scheduler is None:
            log.warning("a reminder was asked for with no scheduler wired")
            return "Andy cannot set reminders at the moment."
        try:
            timer = scheduler.schedule(what_to_say, timedelta(minutes=in_minutes))
        except ValueError as exc:
            # Logged, not only raised. A refused reminder that the answer then
            # promises anyway is invisible otherwise, and that combination is
            # exactly the one worth seeing.
            log.warning(
                "refused a reminder of %r in %r minutes: %s",
                what_to_say[:60],
                in_minutes,
                exc,
            )
            raise ModelRetry(str(exc)) from None
        # What the scheduler actually recorded, not what was asked for. The
        # answer may then say a reminder is set because one is, with the words
        # and the time that were written down rather than the ones requested.
        return (
            f"Reminder set: {timer.text!r} is due at {timer.due}, "
            f"{in_minutes} minutes from now."
        )

    @agent.tool
    def list_reminders(ctx: RunContext[AndyDeps]) -> list[str]:
        """See what reminders are already waiting."""
        scheduler = ctx.deps.scheduler
        if scheduler is None:
            return []
        return [f"{t.text} (due {t.due})" for t in scheduler.pending()]

    @agent.tool
    def stop_listening(ctx: RunContext[AndyDeps]) -> str:
        """Stop listening, when someone explicitly asks Andy to.

        Only for a direct request such as "stop listening" or "go to sleep".
        Never because a conversation ended or the room went quiet.
        """
        ctx.deps.effects.attention(AttentionAction.SLEEP)
        return "Stopped listening."

    return agent


class AgentConversation:
    """Adapts the agent to the turn coordinator's `Conversation` protocol.

    Message history is passed in from the coordinator rather than kept here, so
    the existing bounds still hold: eight exchanges, cleared after silence.
    """

    def __init__(self, agent: Agent[AndyDeps, Reply], deps: AndyDeps) -> None:
        self._agent = agent
        self._deps = deps
        self._runs = 0
        self._failures = 0
        self._tool_calls = 0
        self._feelings = 0
        self._movements = 0
        self._tools_used: set[str] = set()

    def situation(self) -> dict[str, Any]:
        """What Andy can sense, for whoever is about to speak for him.

        The agent gets these as instructions on every run. The gate needs them
        too: it answers for Andy on every turn it does not hand over, and on
        every turn where the agent fails, and a blind gate answers a question
        about the weather by saying it does not know while the reading sits one
        layer below it.
        """
        return self._deps.device.interpreted()

    def capabilities(self) -> tuple[str, ...]:
        """What Andy can actually do, read off what is wired rather than prose.

        The cheap gate decides what to do with a sentence before the agent ever
        sees it, and it used to be told only about movement. Asked to set a
        reminder it answered that Andy could not, while the scheduler that can
        sat one layer below it. A capability list assembled from the live
        objects cannot drift from the truth the way a paragraph does.
        """
        deps = self._deps
        able: list[str] = []
        # First, and unconditional, because it is the one he was caught
        # denying. Asked for music he answered that he had no speakers, while
        # speaking through the speaker in his own head. Declining was right;
        # the reason was false.
        able.append(
            "speak out loud through the speaker in his own body -- it is how "
            "this conversation reaches the room"
        )
        if deps.motion is not None:
            able.append("move his head through his named movements")
        if deps.scheduler is not None:
            able.append("set reminders and timers, and say what is pending")
        if deps.memory is not None:
            able.append("remember facts and recall them in a later conversation")
        if deps.vision is not None and deps.device.has_camera():
            able.append("look through his camera and describe what he sees")
            if getattr(deps.vision, "can_find", False):
                able.append(
                    "look for a particular thing and say whether it is there"
                )
        able.append(
            "say the date and time, what part of the day it is, and when the "
            "sun next rises and sets where he is"
        )
        able.append(
            "say where in the world he is, which he works out for himself"
        )
        able.append(
            "say how long he has been awake, how warm he is, which way his "
            "head is pointing and how his connection is"
        )
        able.append(
            "feel his own body: whether someone is leaning in and where a "
            "hand is on his head, the light level, his battery"
        )
        able.append(
            "check his own hardware: motor temperature, power draw, memory, "
            "faults, and whether he is upright"
        )
        if self._deps.effects.screen_available():
            able.append(
                "dim his own screen, darken it or turn it back up, for when "
                "his face is too bright in a dark room"
            )
        if self._agent.toolsets:
            able.append("use the external tools he is connected to")
        return tuple(able)

    async def reply(
        self, transcript: str, history: list[dict[str, str]]
    ) -> AgentTurn:
        """Run the agent, wear the feeling it chose, and return the turn."""
        from pydantic_ai.messages import (
            ModelRequest,
            ModelResponse,
            TextPart,
            UserPromptPart,
        )

        messages = []
        for entry in history:
            content = entry.get("content", "")
            if entry.get("role") == "user":
                messages.append(ModelRequest(parts=[UserPromptPart(content=content)]))
            elif entry.get("role") == "assistant":
                messages.append(ModelResponse(parts=[TextPart(content=content)]))

        self._runs += 1
        with capture_run_messages() as captured:
            try:
                async with asyncio.timeout(AGENT_DEADLINE_SECONDS):
                    result = await self._agent.run(
                        transcript, deps=self._deps, message_history=messages or None
                    )
            except (TimeoutError, UnexpectedModelBehavior):
                # Either the retries ran out or they ran long. Both mean the
                # model never produced the structured answer, and it usually
                # said something sensible on the way. That is closer to an
                # answer than the gate's stock line, so it is spoken with no
                # feeling and no movement: the model chose neither.
                spoken = _text_answer(captured)
                if spoken is None:
                    self._failures += 1
                    raise
                self._failures += 1
                log.warning(
                    "agent never reached its output format; speaking its text: %r",
                    spoken[:120],
                )
                return AgentTurn(speech=spoken)
            except Exception:
                self._failures += 1
                raise
        # Which tools, not how many. A turn that claims to have set a reminder
        # and a turn that set one are indistinguishable from a count, and the
        # difference between them is the whole question when Andy says he has
        # done something.
        called: list[str] = []
        failed: list[str] = []
        for message in result.new_messages():
            for part in getattr(message, "parts", ()):
                name = part.__class__.__name__
                if name == "ToolCallPart":
                    self._tool_calls += 1
                    called.append(str(getattr(part, "tool_name", "?")))
                elif name == "RetryPromptPart":
                    failed.append(str(getattr(part, "tool_name", "output")))
        self._tools_used.update(called)
        if called or failed:
            log.info(
                "agent used %s%s",
                ", ".join(called) or "no tools",
                f" (retried: {', '.join(failed)})" if failed else "",
            )

        answer: Reply = result.output
        # Apply the feeling before returning, so the face has already changed by
        # the time the words are spoken rather than after.
        try:
            await self._deps.effects.set_emotion(
                EmotionRequest(emotion=answer.feeling, intensity=75)
            )
            self._feelings += 1
        except Exception:
            log.warning("could not wear %s", answer.feeling, exc_info=True)
        text = answer.speech.strip()
        movement = (
            MotionAction(answer.movement)
            if answer.movement and self._deps.motion is not None
            else None
        )
        if movement is not None:
            self._movements += 1
        log.info(
            "agent replied in %d chars feeling=%s movement=%s",
            len(text),
            answer.feeling,
            movement.value if movement is not None else "none",
        )
        return AgentTurn(speech=text, movement=movement, feeling=answer.feeling)

    def snapshot(self) -> dict[str, Any]:
        return {
            "runs": self._runs,
            "failures": self._failures,
            "tool_calls": self._tool_calls,
            "feelings_worn": self._feelings,
            "movements_chosen": self._movements,
            "tools_used": sorted(self._tools_used),
        }
