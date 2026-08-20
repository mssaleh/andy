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
