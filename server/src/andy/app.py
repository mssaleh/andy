from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from fastapi.responses import Response, StreamingResponse

from . import __version__
from .actions import DECISION_SCHEMA, ActionDecision, AgentActions, DecisionKind
from .config import Config
from .media import AudioStore, stream_audio
from .memory import MemoryStore
from .scheduler import Scheduler
from .agent import AgentConversation, AndyDeps, build_agent
from .arbiter import SpeechArbiter
from .bus import EventBus, Route
from .device import DeviceState
from .effects import EffectController
from .vision import VisionProvider
from .motion import MotionController, catalog_snapshot
from .speaker import SpeakerOutput
from .providers import KokoroTTS, OpenAIAudioASR, OpenAIChat, WhisperASR
from .transport import ESPHomeBridge, NativeEventSink, make_client
from .turns import TurnCoordinator
from .vad import (
    EnergyConfig,
    EnergyGate,
    SileroConfig,
    SileroModel,
    UtteranceDetector,
    VADConfig,
    VADEngine,
)

log = logging.getLogger("andy.app")
andy_log = logging.getLogger("andy")
andy_log.setLevel(logging.INFO)
if uvicorn_handlers := logging.getLogger("uvicorn").handlers:
    andy_log.handlers = list(uvicorn_handlers)
    andy_log.propagate = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = Config.from_env()
    media = AudioStore()
    asr = (
        OpenAIAudioASR(
            config.asr_url,
            model=config.asr_model,
            language=config.asr_language,
        )
        if config.asr_api == "openai"
        else WhisperASR(config.asr_url)
    )
    llm = OpenAIChat(
        config.llm_url,
        config.llm_model,
        config.llm_key,
        api=config.llm_api,
        reasoning_effort=config.llm_reasoning,
        json_schema=DECISION_SCHEMA,
    )
    tts = KokoroTTS(config.tts_url, voice=config.tts_voice)
    bridge: ESPHomeBridge | None = None
    actions: AgentActions | None = None
    device: DeviceState | None = None
    speaker: SpeakerOutput | None = None
    effects: EffectController | None = None
    arbiter: SpeechArbiter | None = None
    bus: EventBus | None = None
    conversation: AgentConversation | None = None
    vision: VisionProvider | None = None
    memory = MemoryStore(config.state_dir / "memories.json" if config.state_dir else None)
    scheduler: Scheduler | None = None
    if config.device_enabled:
        client = make_client(
            config.device_host,
            config.device_port,
            config.device_key,
            expected_name=config.device_name,
            expected_mac=config.device_mac,
        )
        sink = NativeEventSink(client)
        device = DeviceState(client)
        motion = MotionController(device)
        speaker = SpeakerOutput(device)
        effects = EffectController(device)
        actions = AgentActions(
            motion,
            enabled=config.motion_actions_enabled,
        )
        arbiter = SpeechArbiter(
            speaker, media, tts, media_base_url=config.media_base_url
        )
        scheduler = Scheduler(
            arbiter,
            config.state_dir / "timers.json" if config.state_dir else None,
        )
        if config.vision_enabled:
            vision = VisionProvider(
                client,
                base_url=config.vlm_url,
                model=config.vlm_model,
                api_key=config.llm_key,
                api=config.llm_api,
                detector_url=config.owl_url,
            )
        if config.agent_enabled:
            mcp = []
            if config.mcp_servers:
                # One client for every connector. The MCP client library reads
                # the same `mcpServers` shape the configuration is written in
                # and owns every transport -- stdio, HTTP, SSE -- so nothing
                # here has to know how a given connector is reached, and the
                # per-transport classes that used to do it are deprecated.
                from fastmcp.client import Client
                from pydantic_ai.mcp import MCPToolset

                mcp = [
                    MCPToolset(
                        Client(
                            {
                                "mcpServers": {
                                    spec.name: spec.as_config()
                                    for spec in config.mcp_servers
                                }
                            }
                        )
                    )
                ]
                for spec in config.mcp_servers:
                    # Never the headers: a connector's credential is a secret
                    # in exactly the way the device key and the model key are.
                    log.info("MCP connector attached: %s", spec.describe())
            conversation = AgentConversation(
                build_agent(
                    base_url=config.llm_url,
                    model_name=config.llm_model,
                    api_key=config.llm_key,
                    mcp_servers=mcp,
                ),
                AndyDeps(
                    device=device,
                    effects=effects,
                    motion=actions,
                    vision=vision,
                    memory=memory,
                    scheduler=scheduler,
                ),
            )
        bus = EventBus(device)
        # One gate for the whole session: the noise floor describes the room,
        # not the ten seconds of it that one capture window happened to hear.
        engine = VADEngine(config.vad_engine)
        vad_config = VADConfig(
            engine=engine,
            silero=SileroConfig(
                speech_threshold=config.vad_speech_threshold,
                keep_threshold=min(
                    config.vad_speech_threshold,
                    max(0.05, config.vad_speech_threshold - 0.15),
                ),
            ),
            energy=EnergyConfig(
                min_speech_rms=config.vad_min_speech_rms,
                noise_ratio=config.vad_noise_ratio,
            ),
        )
        energy_gate = EnergyGate(vad_config.energy)
        # Loaded once, before anything listens. A model that cannot be read is
        # a server that does not start, rather than a robot that has silently
        # stopped hearing anyone.
        silero_model = (
            SileroModel() if engine is VADEngine.SILERO else None
        )
        if silero_model is not None:
            log.info("voice activity detection: silero %s", silero_model.path.name)
        coordinator = TurnCoordinator(
            sink=sink,
            asr=asr,
            llm=llm,
            tts=tts,
            media=media,
            output=speaker,
            media_base_url=config.media_base_url,
            system_prompt=config.system_prompt,
            actions=actions,
            conversation=conversation,
            effects=effects,
            session_idle_seconds=config.session_idle_seconds,
            detector_factory=lambda: UtteranceDetector(
                vad_config, gate=energy_gate, silero_model=silero_model
            ),
        )
        bridge = ESPHomeBridge(
            client=client,
            sink=sink,
            coordinator=coordinator,
            device_name=config.device_name,
            device_project=config.device_project,
            device=device,
            motion=motion,
        )
    app.state.media = media
    app.state.asr = asr
    app.state.llm = llm
    app.state.tts = tts
    app.state.config = config
    app.state.bridge = bridge
    app.state.coordinator = coordinator if config.device_enabled else None
    app.state.actions = actions
    app.state.device = device
    app.state.speaker = speaker
    app.state.effects = effects
    app.state.arbiter = arbiter
    app.state.bus = bus
    app.state.conversation = conversation
    app.state.vision = vision
    app.state.memory = memory
    app.state.scheduler = scheduler
    if bridge is not None:
        await bridge.start()
    if bus is not None and arbiter is not None:
        _install_event_rules(bus, arbiter, conversation, device)
        bus.start()
    if scheduler is not None:
        scheduler.start()
    try:
        yield
    finally:
        if scheduler is not None:
            await scheduler.stop()
        if bus is not None:
            await bus.stop()
        if bridge is not None:
            await bridge.stop()
        closers = [asr.aclose(), llm.aclose(), tts.aclose()]
        if vision is not None:
            closers.append(vision.aclose())
        await asyncio.gather(*closers)


def _install_event_rules(
    bus: EventBus,
    arbiter: SpeechArbiter,
    conversation: AgentConversation | None,
    device: DeviceState | None,
) -> None:
    """What Andy does about an event, and what he thinks about first.

    A rule is a fixed response with no model call: the answer is already known
    and spending a language model on it would only add latency and variance.
    The agent is for events where what to say genuinely depends on the moment.
    """

    from .arbiter import Priority
    from .bus import EventKind

    async def fixed_rule(event) -> None:
        if event.kind is EventKind.BATTERY_LOW:
            await arbiter.say(
                "My battery is getting low. Could you plug me in?",
                Priority.ALERT,
            )
        elif event.kind is EventKind.MOTION_FAULTED:
            # Deliberately silent. A motion fault is already visible on the
            # face and the ring, and announcing it would interrupt whatever
            # the person was actually doing.
            log.warning("motion fault observed: %s", event.value)

    async def ask_the_agent(event) -> None:
        if conversation is None:
            return
        allowed, reason = arbiter.may_speak(Priority.PROACTIVE)
        if not allowed:
            log.info("not raising %s with the agent: %s", event.kind, reason)
            return
        prompts = {
            EventKind.PRESENCE_ARRIVED: (
                "Someone has just come close to you. Greet them briefly if it "
                "seems welcome, or say nothing at all."
            ),
            EventKind.HEAD_GESTURE: (
                "Someone just stroked the top of your head. React briefly."
            ),
            EventKind.SHAKEN: (
                "You were just picked up and shaken, and you stopped moving "
                "for safety. Say something brief about it."
            ),
        }
        prompt = prompts.get(event.kind)
        if prompt is None:
            return
        try:
            reply = await conversation.reply(prompt, [])
        except Exception:
            log.exception("agent failed on %s", event.kind)
            return
        if reply:
            await arbiter.say(reply, Priority.PROACTIVE)

    bus.on(Route.RULE, fixed_rule)
    bus.on(Route.AGENT, ask_the_agent)


app = FastAPI(title="Andy", version=__version__, lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, object]:
    asr_ok, tts_ok, llm_ok = await asyncio.gather(
        app.state.asr.health(),
        app.state.tts.health(),
        app.state.llm.health(),
    )
    device_enabled = app.state.config.device_enabled
    device_connected = (
        app.state.bridge is not None and app.state.bridge.connected
    )
    action_snapshot = (
        app.state.actions.snapshot() if app.state.actions is not None else None
    )
    motion_snapshot = (
        action_snapshot.get("device") if action_snapshot is not None else None
    )
    motion_ready = bool(
        isinstance(motion_snapshot, dict) and motion_snapshot.get("ready")
    )
    # Sight is reported but deliberately not part of `ok`. Andy without a
    # detector is a robot that cannot be asked whether the keys are on the
    # desk; Andy without a recogniser is a robot that cannot be spoken to.
    # Rolling a release back for the first would be the wrong trade.
    vision = app.state.vision
    detector_ready = (
        await vision.detector_ready() if vision is not None else False
    )
    return {
        "ok": (
            asr_ok
            and tts_ok
            and llm_ok
            and (device_connected or not device_enabled)
            and (
                motion_ready
                or not app.state.config.motion_actions_enabled
            )
        ),
        "version": __version__,
        "asr": asr_ok,
        "tts": tts_ok,
        "llm": llm_ok,
        "llm_model": app.state.config.llm_model,
        "media_base_url": app.state.config.media_base_url,
        "device_enabled": device_enabled,
        "device_connected": device_connected,
        "motion_actions_enabled": app.state.config.motion_actions_enabled,
        "motion_ready": motion_ready,
        "action_state": (
            action_snapshot["state"]
            if action_snapshot is not None
            else "unavailable"
        ),
        "vision_enabled": app.state.config.vision_enabled,
        "detector_ready": detector_ready,
        "vision": vision.snapshot() if vision is not None else None,
    }


@app.get("/actions")
async def action_status() -> dict[str, object]:
    if app.state.actions is None:
        return {
            "enabled": False,
            "state": "unavailable",
            "detail": "device bridge is disabled",
        }
    return {
        "enabled": app.state.config.motion_actions_enabled,
        **app.state.actions.snapshot(),
    }


@app.get("/state")
async def device_state() -> dict[str, object]:
    """Everything the device reports, plus the facts the agent is given."""
    device = app.state.device
    if device is None:
        return {"enabled": False, "detail": "device bridge is disabled"}
    return {
        "enabled": True,
        **device.snapshot(),
        "interpreted": device.interpreted(),
    }


@app.get("/agent")
async def agent_status() -> dict[str, object]:
    """What the agent, the effects and the speaker arbiter are doing."""
    conversation = app.state.conversation
    effects = app.state.effects
    arbiter = app.state.arbiter
    bus = app.state.bus
    return {
        "agent_enabled": app.state.config.agent_enabled,
        "vision_enabled": app.state.config.vision_enabled,
        "mcp_servers": [
            spec.describe() for spec in app.state.config.mcp_servers
        ],
        "agent": conversation.snapshot() if conversation else None,
        "effects": effects.snapshot() if effects else None,
        "speech": arbiter.snapshot() if arbiter else None,
        "events": bus.snapshot() if bus else None,
        "memory": app.state.memory.snapshot() if app.state.memory else None,
        "reminders": (
            app.state.scheduler.snapshot() if app.state.scheduler else None
        ),
    }


@app.get("/motions")
async def motion_catalog() -> dict[str, object]:
    return {"motions": catalog_snapshot()}


class SayRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    priority: str = Field("reply", pattern="^(reply|alert|proactive)$")


class EmotionRequestModel(BaseModel):
    emotion: str
    intensity: int | None = Field(None, ge=0, le=100)
    express: bool = False


class MotionRequestModel(BaseModel):
    action: str


class ConverseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1_000)
    speak: bool = True
    #: A turn that moves is a turn that has to be watched, so driving one from
    #: here is opt-in. With it off the whole reasoning path still runs and the
    #: movement the agent chose is reported without being performed.
    move: bool = True
    #: Go in the way a spoken sentence does: through the router and the gate
    #: first, and only then to the agent if the gate hands it over. Off, this
    #: calls the agent directly, which is the shorter path and skips the half
    #: of the system that answers for Andy when the agent is not run.
    via_gate: bool = False


@app.post("/say")
async def say(request: SayRequest) -> dict[str, object]:
    """Speak a given sentence, subject to the arbiter's rules."""
    from .arbiter import Priority

    arbiter = app.state.arbiter
    if arbiter is None:
        raise HTTPException(status_code=503, detail="device bridge is disabled")
    priority = {
        "reply": Priority.REPLY,
        "alert": Priority.ALERT,
        "proactive": Priority.PROACTIVE,
    }[request.priority]
    spoken = await arbiter.say(request.text, priority)
    return {"spoken": spoken, "detail": "" if spoken else arbiter.may_speak(priority)[1]}


@app.post("/emotion")
async def set_emotion(request: EmotionRequestModel) -> dict[str, object]:
    """Set Andy's mood directly, without going through the agent."""
    from .effects import EmotionRequest as Req

    effects = app.state.effects
    if effects is None:
        raise HTTPException(status_code=503, detail="device bridge is disabled")
    try:
        applied = await effects.set_emotion(
            Req(
                emotion=request.emotion,
                intensity=request.intensity,
                express=request.express,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"applied": applied, "emotions": list(effects.emotions)}


@app.post("/motion")
async def run_motion(request: MotionRequestModel) -> dict[str, object]:
    """Run one named motion program, through the same allowlist as the agent."""
    from .actions import MotionAction

    actions = app.state.actions
    if actions is None:
        raise HTTPException(status_code=503, detail="device bridge is disabled")
    try:
        action = MotionAction(request.action.strip().casefold())
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"unknown motion; choose one of {[a.value for a in MotionAction]}",
        ) from exc
    detail = await actions.execute(action)
    return {"action": action.value, "detail": detail}


@app.post("/converse")
async def converse(request: ConverseRequest) -> dict[str, object]:
    """Put a sentence to Andy as though it had been heard, and get his reply.

    With `via_gate` this goes the way a heard sentence goes: the calibrated
    router first, then the gate, and on to the agent only if the gate hands it
    over. Without it the agent is called directly, which is shorter but skips
    the half of the system that answers for Andy when the agent is not run --
    and that half was found answering blind, so it needs a way in from here.

    The reply is spoken and the movement performed unless asked otherwise, so
    the whole path can be exercised with no voice in the room, which is what
    integration testing and a silent room both need.
    """
    conversation = app.state.conversation
    if conversation is None:
        raise HTTPException(status_code=503, detail="the agent is disabled")

    gate: dict[str, object] | None = None
    if request.via_gate:
        coordinator = getattr(app.state, "coordinator", None)
        if coordinator is None:
            raise HTTPException(
                status_code=503, detail="the turn coordinator is not running"
            )
        decision = await coordinator.consider(request.text)
        gate = {
            "kind": decision.kind.value,
            "motion": (
                decision.action.value if decision.action is not None else None
            ),
            "reply": decision.reply,
        }
        if decision.kind is not DecisionKind.CHAT:
            # The gate keeps this one. That is the half of the system a direct
            # call to the agent never exercises, and the half that was found
            # answering for Andy without knowing anything he can sense.
            spoken = False
            reply = (decision.reply or "").strip()
            if request.speak and app.state.arbiter is not None and reply:
                from .arbiter import Priority

                spoken = await app.state.arbiter.say(reply, Priority.REPLY)
            moved = False
            if (
                decision.kind is DecisionKind.MOTION
                and decision.action is not None
                and request.move
                and app.state.actions is not None
            ):
                authorized = app.state.actions.authorize(decision, request.text)
                if authorized.kind is DecisionKind.MOTION:
                    await app.state.actions.execute(authorized.action)
                    moved = True
            return {
                "reply": reply,
                "spoken": spoken,
                "movement": gate["motion"],
                "moved": moved,
                "gate": gate,
                "agent": conversation.snapshot(),
            }

    turn = await conversation.reply(request.text, [])
    spoken = False
    if request.speak and app.state.arbiter is not None and turn.speech:
        from .arbiter import Priority

        spoken = await app.state.arbiter.say(turn.speech, Priority.REPLY)
    moved = False
    movement = turn.movement
    if movement is not None and request.move and app.state.actions is not None:
        # The same allowlist the spoken path uses, not a second route to the
        # servos: authorize first, and only run what comes back authorized.
        decision = app.state.actions.authorize(
            ActionDecision(kind=DecisionKind.MOTION, action=movement),
            request.text,
        )
        if decision.kind is DecisionKind.MOTION and decision.action is not None:
            await app.state.actions.execute(decision.action)
            moved = True
    return {
        "reply": turn.speech,
        "spoken": spoken,
        "movement": movement.value if movement is not None else None,
        "moved": moved,
        "gate": gate,
        "agent": conversation.snapshot(),
    }


@app.get("/tts/{key}.wav")
async def tts_media(key: str) -> Response:
    item = app.state.media.get(key)
    if item is None:
        raise HTTPException(status_code=404, detail="audio not found")
    return StreamingResponse(
        stream_audio(item),
        media_type=item.content_type,
        headers={
            "Content-Length": str(len(item.data)),
            "Cache-Control": "no-store",
        },
    )
