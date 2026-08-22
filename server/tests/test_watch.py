from __future__ import annotations

import pytest

from andy.effects import EmotionRequest
from andy.watch import BackendWatch


class Probe:
    """A backend whose health is whatever the test says it is."""

    def __init__(self, healthy: bool = True) -> None:
        self.healthy = healthy
        self.calls = 0

    async def health(self) -> bool:
        self.calls += 1
        return self.healthy


class Face:
    """Records what would have reached Andy, without a device."""

    def __init__(self, available: bool = True) -> None:
        self._available = available
        self.worn: list[EmotionRequest] = []
        self.resets = 0

    def available(self) -> bool:
        return self._available

    async def set_emotion(self, request: EmotionRequest) -> str:
        self.worn.append(request)
        return request.emotion

    def reset_emotion(self) -> str:
        self.resets += 1
        return "reset"


def build(asr: Probe, tts: Probe, face: Face | None) -> BackendWatch:
    return BackendWatch(asr=asr, tts=tts, effects=face)


@pytest.mark.asyncio
async def test_healthy_backends_leave_the_face_alone() -> None:
    face = Face()
    watch = build(Probe(True), Probe(True), face)

    assert await watch.check_once() is True
    assert await watch.check_once() is True

    assert watch.alarmed is False
    assert face.worn == []
    assert face.resets == 0


@pytest.mark.asyncio
async def test_a_single_failure_is_not_an_outage() -> None:
    """A restart or a model reload must not put a sick face on Andy."""
    asr = Probe(True)
    face = Face()
    watch = build(asr, Probe(True), face)

    asr.healthy = False
    assert await watch.check_once() is False
    assert watch.alarmed is False
    assert face.worn == []

    asr.healthy = True
    assert await watch.check_once() is True
    assert face.worn == []


@pytest.mark.asyncio
async def test_two_failures_put_the_outage_on_andys_face() -> None:
    tts = Probe(True)
    face = Face()
    watch = build(Probe(True), tts, face)

    tts.healthy = False
    await watch.check_once()
    await watch.check_once()

    assert watch.alarmed is True
    assert [request.emotion for request in face.worn] == ["unwell"]


@pytest.mark.asyncio
async def test_the_face_is_renewed_while_the_outage_lasts() -> None:
    """`unwell` is held for 60 s in firmware, so a long outage must re-assert."""
    asr = Probe(False)
    face = Face()
    watch = build(asr, Probe(True), face)

    for _ in range(4):
        await watch.check_once()

    # Two rounds to raise the alarm, then one renewal per round after it.
    assert len(face.worn) == 3
    assert watch.alarmed is True


@pytest.mark.asyncio
async def test_recovery_clears_the_face_once() -> None:
    asr = Probe(False)
    face = Face()
    watch = build(asr, Probe(True), face)

    await watch.check_once()
    await watch.check_once()
    assert watch.alarmed is True

    asr.healthy = True
    assert await watch.check_once() is True
    assert watch.alarmed is False
    assert face.resets == 1

    # Staying healthy must not keep pressing the reset button.
    await watch.check_once()
    assert face.resets == 1


@pytest.mark.asyncio
async def test_a_disconnected_andy_is_not_counted_as_warned() -> None:
    """The alarm must land on the next round once he is back, not be skipped."""
    face = Face(available=False)
    watch = build(Probe(False), Probe(True), face)

    await watch.check_once()
    await watch.check_once()
    assert watch.alarmed is False
    assert face.worn == []

    face._available = True
    await watch.check_once()
    assert watch.alarmed is True
    assert [request.emotion for request in face.worn] == ["unwell"]


@pytest.mark.asyncio
async def test_a_face_that_refuses_does_not_stop_the_watch() -> None:
    class Refusing(Face):
        async def set_emotion(self, request: EmotionRequest) -> str:
            raise RuntimeError("device exposes no emotion vocabulary")

    face = Refusing()
    watch = build(Probe(False), Probe(True), face)

    await watch.check_once()
    assert await watch.check_once() is False
    assert watch.alarmed is False


@pytest.mark.asyncio
async def test_without_effects_the_watch_still_reports() -> None:
    watch = build(Probe(False), Probe(True), None)

    assert await watch.check_once() is False
    assert await watch.check_once() is False
    assert watch.alarmed is False
    assert watch.snapshot()["failures"] == 2
