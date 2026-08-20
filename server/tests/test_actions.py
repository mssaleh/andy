from __future__ import annotations

import json

import pytest

from andy.actions import (
    ActionDecision,
    AgentActions,
    DecisionKind,
    MOTION_DESCRIPTIONS,
    MotionAction,
    motion_catalog_prompt,
    parse_agent_decision,
    resolve_calibrated_request,
)


@pytest.mark.parametrize("action", list(MotionAction))
def test_llm_motion_decisions_are_limited_to_calibrated_actions(
    action: MotionAction,
) -> None:
    decision = parse_agent_decision(
        json.dumps(
            {
                "kind": "motion",
                "reply": "Okay.",
                "motion": action.value,
            }
        )
    )

    assert decision == ActionDecision(
        kind=DecisionKind.MOTION,
        action=action,
        reply="Okay.",
    )


def test_unknown_llm_motion_is_rejected_without_reaching_a_servo() -> None:
    decision = parse_agent_decision(
        '{"kind":"motion","reply":"Moving.","motion":"spin_forever"}'
    )

    assert decision.kind is DecisionKind.REJECTED_MOTION
    assert decision.action is None
    assert decision.reply == (
        "I can't safely perform that motion. Please ask for one of my "
        "calibrated movements."
    )


@pytest.mark.parametrize(
    ("transcript", "action"),
    [
        (
            "Please turn your head to the right by 30 degrees.",
            MotionAction.LOOK_RIGHT,
        ),
        (
            "Please move your head 30 degrees right.",
            MotionAction.LOOK_RIGHT,
        ),
        ("Andy, could you look thirty degrees left?", MotionAction.LOOK_LEFT),
        ("Would you please look up by 30°?", MotionAction.LOOK_UP),
        ("Please nod your head yes.", MotionAction.NOD_YES),
        ("Please say yes with your head.", MotionAction.NOD_YES),
        ("Dance for me.", MotionAction.DANCE),
        ("Please show me a dance.", MotionAction.DANCE),
        (
            "Move yaw positive by ten degrees.",
            MotionAction.YAW_POSITIVE_10,
        ),
    ],
)
def test_unambiguous_calibrated_request_has_a_deterministic_route(
    transcript: str, action: MotionAction
) -> None:
    decision = resolve_calibrated_request(transcript)

    assert decision is not None
    assert decision.kind is DecisionKind.MOTION
    assert decision.action is action
    assert decision.reply


@pytest.mark.parametrize(
    ("transcript", "reply"),
    [
        (
            "Please turn your head to the right by thirty degrees.",
            "I'll look to my right.",
        ),
        ("Please say yes with your head.", "Yes, I'll nod."),
        ("Please show me a dance.", "Dance time!"),
    ],
)
def test_release_canary_has_stable_distinctive_spoken_replies(
    transcript: str, reply: str
) -> None:
    decision = resolve_calibrated_request(transcript)

    assert decision is not None
    assert decision.reply == reply


def test_incidental_motion_words_remain_for_semantic_classification() -> None:
    assert (
        resolve_calibrated_request(
            "The documentary said the dancer should look right."
        )
        is None
    )
    assert (
        resolve_calibrated_request(
            "Please move the camera right by 30 degrees."
        )
        is None
    )


@pytest.mark.parametrize(
    "transcript",
    [
        "Please turn your head right by 20 degrees.",
        "Look down by 15 degrees.",
    ],
)
def test_unsupported_angle_request_fails_closed(transcript: str) -> None:
    decision = resolve_calibrated_request(transcript)

    assert decision is not None
    assert decision.kind is DecisionKind.REJECTED_MOTION
    assert decision.action is None
    assert decision.reply


def test_agent_motion_catalog_describes_every_allowlisted_action() -> None:
    assert set(MOTION_DESCRIPTIONS) == set(MotionAction)
    prompt = motion_catalog_prompt()
    for action in MotionAction:
        assert f"- {action.value}:" in prompt
    assert "look exactly 30 degrees right" in prompt
    assert "eight-pose dance" in prompt


@pytest.mark.parametrize(
    ("raw", "kind", "reply"),
    [
        ('{"kind":"ignore","reply":null,"motion":null}', DecisionKind.IGNORE, None),
        ('{"kind":"wait","reply":null,"motion":null}', DecisionKind.WAIT, None),
        (
            '{"kind":"end_context","reply":null,"motion":null}',
            DecisionKind.CONTEXT_END,
            None,
        ),
        (
            '```json\n{"kind":"reply","reply":"Hello.","motion":null}\n```',
            DecisionKind.CHAT,
            "Hello.",
        ),
        (
            '{"kind":"sleep","reply":"Goodbye.","motion":null}',
            DecisionKind.SESSION_END,
            "Goodbye.",
        ),
    ],
)
def test_non_motion_agent_decisions(
    raw: str, kind: DecisionKind, reply: str | None
) -> None:
    decision = parse_agent_decision(raw)

    assert decision.kind is kind
    assert decision.action is None
    assert decision.reply == reply


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '{"kind":"reply","reply":"","motion":null}',
        '{"kind":"invented","reply":"hello","motion":null}',
        'prefix {"kind":"ignore","reply":null,"motion":null}',
        '{"kind":"ignore","reply":null,"motion":null,"angle":30}',
        '{"kind":"ignore","reply":"ignored","motion":null}',
        '{"kind":"motion","reply":"Moving.","motion":30}',
        '{"kind":"chat","reply":"Hello.","motion":null}',
        json.dumps({"kind": "reply", "reply": "x" * 501, "motion": None}),
    ],
)
def test_malformed_agent_decisions_fail_closed(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_agent_decision(raw)


class Executor:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[MotionAction] = []
        self.passive_stops = 0

    async def execute(self, action: MotionAction) -> str:
        self.calls.append(action)
        if self.failure is not None:
            raise self.failure
        return "complete: torque=0/0"

    async def stop_passive(self) -> None:
        self.passive_stops += 1

    def snapshot(self) -> dict[str, object]:
        return {"connected": True, "ready": True}


@pytest.mark.asyncio
async def test_agent_actions_reports_allowlisted_completion() -> None:
    executor = Executor()
    actions = AgentActions(executor)
    decision = actions.authorize(
        ActionDecision(
            kind=DecisionKind.MOTION,
            action=MotionAction.NOD_YES,
            reply="I'll nod.",
        ),
        "Please nod",
    )

    assert decision.action is MotionAction.NOD_YES
    await actions.execute(decision.action)
    await actions.stop_passive()

    assert executor.calls == [MotionAction.NOD_YES]
    assert executor.passive_stops == 1
    status = actions.snapshot()
    assert status["state"] == "completed"
    assert status["requests"] == 1
    assert status["rejections"] == 0
    assert status["completions"] == 1
    assert status["failures"] == 0
    assert status["last_action"] == "nod_yes"

    actions.authorize(ActionDecision(kind=DecisionKind.IGNORE), "room noise")
    status = actions.snapshot()
    assert status["state"] == "completed"
    assert status["decision_state"] == "ignore"
    assert status["last_action"] == "nod_yes"


def test_disabled_motion_is_rejected_after_llm_selection() -> None:
    actions = AgentActions(Executor(), enabled=False)

    decision = actions.authorize(
        ActionDecision(
            kind=DecisionKind.MOTION,
            action=MotionAction.DANCE,
            reply="Dance time.",
        ),
        "Dance",
    )

    assert decision.kind is DecisionKind.REJECTED_MOTION
    assert decision.action is None
    assert actions.snapshot()["rejections"] == 1


@pytest.mark.asyncio
async def test_agent_actions_reports_execution_failure() -> None:
    actions = AgentActions(Executor(failure=RuntimeError("device rejected action")))
    decision = actions.authorize(
        ActionDecision(
            kind=DecisionKind.MOTION,
            action=MotionAction.LOOK_UP,
            reply="I'll look up.",
        ),
        "Look up",
    )

    with pytest.raises(RuntimeError, match="device rejected action"):
        await actions.execute(decision.action)  # type: ignore[arg-type]

    status = actions.snapshot()
    assert status["state"] == "failed"
    assert status["failures"] == 1
    assert status["completions"] == 0


def test_a_reply_that_also_names_a_movement_still_speaks() -> None:
    """Muteness is the worse failure.

    The gate is asked to send a request that mixes a movement with anything
    else to the agent, and it often names the movement anyway. Rejecting the
    decision spends the one repair round and then says nothing at all, while
    discarding the field cannot cause a movement.
    """
    decision = parse_agent_decision(
        '{"kind":"reply","reply":"Noted, and nodding.","motion":"nod_yes"}'
    )
    assert decision.kind is DecisionKind.CHAT
    assert decision.reply == "Noted, and nodding."
    assert decision.action is None


def test_a_sleep_that_names_a_movement_still_sleeps() -> None:
    decision = parse_agent_decision(
        '{"kind":"sleep","reply":"Goodnight.","motion":"bow"}'
    )
    assert decision.kind is DecisionKind.SESSION_END
    assert decision.action is None


def test_a_movement_named_on_a_reply_is_never_executed() -> None:
    """The discarded field must not reach the motion layer by another route."""
    decision = parse_agent_decision(
        '{"kind":"reply","reply":"Sure.","motion":"dance"}'
    )
    assert decision.action is None
    assert decision.kind is not DecisionKind.MOTION
