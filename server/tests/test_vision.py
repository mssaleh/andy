from __future__ import annotations

import asyncio

import httpx
import pytest

from andy.vision import MAX_PHRASES, VisionProvider


class Camera:
    """A device that answers a single-image request, and counts them."""

    def __init__(self, frames: list[bytes] | None = None) -> None:
        self.requests = 0
        self._frames = frames or [b"\xff\xd8frame-one", b"\xff\xd8frame-two"]
        self._listener = None

    def subscribe_states(self, listener) -> None:
        self._listener = listener

    def request_single_image(self) -> None:
        self.requests += 1
        index = min(self.requests - 1, len(self._frames) - 1)
        frame = self._frames[index]

        class State:
            data = frame

        # The real client delivers on the event loop, not inline.
        asyncio.get_running_loop().call_soon(self._listener, State())


class _CameraState:
    def __init__(self, data: bytes) -> None:
        self.data = data


@pytest.fixture(autouse=True)
def _camera_state_is_recognised(monkeypatch: pytest.MonkeyPatch) -> None:
    import andy.vision as vision

    monkeypatch.setattr(vision, "CameraState", _CameraState)


class Camera2(Camera):
    def request_single_image(self) -> None:
        self.requests += 1
        index = min(self.requests - 1, len(self._frames) - 1)
        state = _CameraState(self._frames[index])
        asyncio.get_running_loop().call_soon(self._listener, state)


def _provider(camera, handler, *, detector: str = "") -> VisionProvider:
    provider = VisionProvider(
        camera,
        base_url="http://vlm.test",
        model="a-vlm",
        api_key="",
        detector_url=detector,
    )
    provider._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return provider


@pytest.mark.asyncio
async def test_two_questions_about_one_moment_take_one_photograph() -> None:
    """The frame is the expensive thing, so the frame is what is cached."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/detect"):
            return httpx.Response(200, json={"found": []})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "A desk."}}]},
        )

    camera = Camera2()
    provider = _provider(camera, handler, detector="http://owl.test")

    assert await provider.describe() == "A desk."
    assert await provider.find(["a person"]) == []

    assert camera.requests == 1
    assert provider.frames_taken == 1
    assert provider.frames_reused == 1
    await provider.aclose()


@pytest.mark.asyncio
async def test_finding_nothing_is_an_answer_not_a_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"found": []})

    provider = _provider(Camera2(), handler, detector="http://owl.test")
    assert await provider.find(["a dragon"]) == []
    await provider.aclose()


@pytest.mark.asyncio
async def test_without_a_detector_looking_for_a_thing_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("nothing should be requested")

    provider = _provider(Camera2(), handler)
    assert not provider.can_find
    with pytest.raises(RuntimeError, match="detector"):
        await provider.find(["a person"])
    await provider.aclose()


@pytest.mark.asyncio
async def test_a_question_with_nothing_in_it_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("nothing should be requested")

    provider = _provider(Camera2(), handler, detector="http://owl.test")
    with pytest.raises(ValueError):
        await provider.find(["   ", ""])
    await provider.aclose()


@pytest.mark.asyncio
async def test_a_question_is_bounded_in_how_much_it_may_ask() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["phrases"] = json.loads(request.content)["phrases"]
        return httpx.Response(200, json={"found": []})

    provider = _provider(Camera2(), handler, detector="http://owl.test")
    await provider.find([f"thing number {n}" for n in range(50)])
    assert len(seen["phrases"]) == MAX_PHRASES

    await provider.find(["x" * 500])
    assert len(seen["phrases"][0]) <= 60
    await provider.aclose()


@pytest.mark.asyncio
async def test_a_camera_that_does_not_answer_does_not_hang_a_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import andy.vision as vision

    monkeypatch.setattr(vision, "FRAME_TIMEOUT", 0.05)

    class Silent(Camera2):
        def request_single_image(self) -> None:
            self.requests += 1

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no model should be asked about a missing frame")

    provider = _provider(Silent(), handler, detector="http://owl.test")
    assert "did not return a picture" in await provider.describe()
    with pytest.raises(RuntimeError, match="did not return a picture"):
        await provider.find(["a person"])
    await provider.aclose()
