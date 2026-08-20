from __future__ import annotations

import pytest
from fastapi.responses import StreamingResponse

from andy.app import app, tts_media
from andy.media import AudioStore, MEDIA_CHUNK_BYTES


@pytest.mark.asyncio
async def test_tts_endpoint_streams_exact_bounded_content() -> None:
    data = bytes(range(256)) * 9
    store = AudioStore()
    key = store.put(data)
    app.state.media = store

    response = await tts_media(key)
    chunks = [chunk async for chunk in response.body_iterator]

    assert isinstance(response, StreamingResponse)
    assert response.headers["content-length"] == str(len(data))
    assert response.headers["cache-control"] == "no-store"
    assert response.media_type == "audio/wav"
    assert b"".join(chunks) == data
    assert all(len(chunk) <= MEDIA_CHUNK_BYTES for chunk in chunks)


@pytest.mark.asyncio
async def test_converse_reports_the_movement_it_chose_without_running_it() -> None:
    """The whole reasoning path, with the body opt-in.

    `/converse` is how the agent is exercised when the room is silent, so it
    has to survive the agent's answer changing shape. It once passed the whole
    answer object where a sentence was expected, which no test noticed.
    """
    from andy.actions import ActionDecision, MotionAction
    from andy.agent import AgentTurn
    from andy.app import ConverseRequest, converse

    class Conversation:
        async def reply(self, text: str, history: list) -> AgentTurn:
            return AgentTurn(
                speech="Looking left.", movement=MotionAction.LOOK_LEFT
            )

        def snapshot(self) -> dict:
            return {"runs": 1}

    class Actions:
        def __init__(self) -> None:
            self.executed: list[MotionAction] = []

        def authorize(self, decision: ActionDecision, transcript: str):
            return decision

        async def execute(self, action: MotionAction) -> str:
            self.executed.append(action)
            return "complete"

    actions = Actions()
    app.state.conversation = Conversation()
    app.state.actions = actions
    app.state.arbiter = None

    body = await converse(
        ConverseRequest(text="look left", speak=False, move=False)
    )

    assert body["reply"] == "Looking left."
    assert body["movement"] == "look_left"
    assert body["moved"] is False
    assert actions.executed == []

    moved = await converse(
        ConverseRequest(text="look left", speak=False, move=True)
    )
    assert moved["moved"] is True
    assert actions.executed == [MotionAction.LOOK_LEFT]


@pytest.mark.asyncio
async def test_converse_can_go_the_way_a_heard_sentence_goes() -> None:
    """The gate is reachable without a voice in the room.

    A direct call to the agent skips the router and the gate, which is the half
    of the system that answers for Andy on every turn it does not hand over --
    and the half that was found answering without knowing anything he can
    sense. It needs a way in from the control API or it stays untested.
    """
    from andy.actions import ActionDecision, DecisionKind, MotionAction
    from andy.agent import AgentTurn
    from andy.app import ConverseRequest, app, converse

    class Coordinator:
        def __init__(self, decision: ActionDecision) -> None:
            self._decision = decision
            self.considered: list[str] = []

        async def consider(self, text: str) -> ActionDecision:
            self.considered.append(text)
            return self._decision

    class Conversation:
        def __init__(self) -> None:
            self.runs = 0

        async def reply(self, text: str, history: list) -> AgentTurn:
            self.runs += 1
            return AgentTurn(speech="agent answer", movement=None)

        def snapshot(self) -> dict:
            return {"runs": self.runs}

    conversation = Conversation()
    app.state.conversation = conversation
    app.state.arbiter = None
    app.state.actions = None

    # A movement the gate keeps: the agent must not be run at all.
    app.state.coordinator = Coordinator(
        ActionDecision(
            kind=DecisionKind.MOTION,
            action=MotionAction.LOOK_LEFT,
            reply="Looking left.",
        )
    )
    body = await converse(
        ConverseRequest(
            text="look left", speak=False, move=False, via_gate=True
        )
    )
    assert body["gate"]["kind"] == "motion"
    assert body["movement"] == "look_left"
    assert body["reply"] == "Looking left."
    assert conversation.runs == 0, "the gate kept this turn"

    # A conversation the gate hands over: the agent answers, and the gate's
    # own decision is reported alongside so both halves are visible.
    app.state.coordinator = Coordinator(
        ActionDecision(kind=DecisionKind.CHAT, reply="gate fallback")
    )
    body = await converse(
        ConverseRequest(
            text="how are you", speak=False, move=False, via_gate=True
        )
    )
    assert body["gate"]["kind"] == "chat"
    assert body["reply"] == "agent answer"
    assert conversation.runs == 1


@pytest.mark.asyncio
async def test_converse_without_the_gate_still_calls_the_agent_directly() -> None:
    from andy.agent import AgentTurn
    from andy.app import ConverseRequest, app, converse

    class Conversation:
        async def reply(self, text: str, history: list) -> AgentTurn:
            return AgentTurn(speech="direct", movement=None)

        def snapshot(self) -> dict:
            return {}

    app.state.conversation = Conversation()
    app.state.arbiter = None
    app.state.actions = None
    app.state.coordinator = None

    body = await converse(
        ConverseRequest(text="hello", speak=False, move=False)
    )
    assert body["reply"] == "direct"
    assert body["gate"] is None
