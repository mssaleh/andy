from __future__ import annotations

import pytest

from andy.events import DeviceEvent, EventKind
from andy.transport import EVENT_MAP, NativeEventSink, make_client


class FakeClient:
    def __init__(self) -> None:
        self.sent: list[tuple[object, dict[str, str] | None]] = []

    def send_voice_assistant_event(
        self, event_type: object, data: dict[str, str] | None
    ) -> None:
        self.sent.append((event_type, data))


def test_native_event_map_covers_every_coordinator_event() -> None:
    assert set(EVENT_MAP) == set(EventKind)


def test_native_sink_sends_only_while_connected() -> None:
    client = FakeClient()
    sink = NativeEventSink(client)  # type: ignore[arg-type]

    sink.emit(DeviceEvent(EventKind.RUN_START))
    assert client.sent == []

    sink.connected = True
    sink.emit(DeviceEvent(EventKind.STT_END, {"text": "hello"}))
    assert client.sent == [(EVENT_MAP[EventKind.STT_END], {"text": "hello"})]


@pytest.mark.asyncio
async def test_client_requires_the_expected_device_identity() -> None:
    client = make_client(
        "192.0.2.1",
        6053,
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        expected_name="andy",
        expected_mac="7c4fadaf9f30",
    )
    assert client._params.expected_name == "andy"
    assert client._params.expected_mac == "7c4fadaf9f30"
    assert client._params.addresses == ["192.0.2.1"]
    await client.disconnect()
