from __future__ import annotations

import logging

from aioesphomeapi import APIClient, ReconnectLogic
from aioesphomeapi.model import VoiceAssistantEventType as NativeEvent

from . import __version__
from .events import DeviceEvent, EventKind
from .device import DeviceState
from .motion import MotionController
from .turns import TurnCoordinator

log = logging.getLogger("andy.transport")


EVENT_MAP = {
    EventKind.RUN_START: NativeEvent.VOICE_ASSISTANT_RUN_START,
    EventKind.STT_START: NativeEvent.VOICE_ASSISTANT_STT_START,
    EventKind.STT_VAD_START: NativeEvent.VOICE_ASSISTANT_STT_VAD_START,
    EventKind.STT_VAD_END: NativeEvent.VOICE_ASSISTANT_STT_VAD_END,
    EventKind.STT_END: NativeEvent.VOICE_ASSISTANT_STT_END,
    EventKind.INTENT_START: NativeEvent.VOICE_ASSISTANT_INTENT_START,
    EventKind.INTENT_END: NativeEvent.VOICE_ASSISTANT_INTENT_END,
    EventKind.TTS_START: NativeEvent.VOICE_ASSISTANT_TTS_START,
    EventKind.TTS_END: NativeEvent.VOICE_ASSISTANT_TTS_END,
    EventKind.ERROR: NativeEvent.VOICE_ASSISTANT_ERROR,
    EventKind.RUN_END: NativeEvent.VOICE_ASSISTANT_RUN_END,
}


class NativeEventSink:
    def __init__(self, client: APIClient) -> None:
        self._client = client
        self.connected = False

    def emit(self, event: DeviceEvent) -> None:
        if not self.connected:
            return
        try:
            self._client.send_voice_assistant_event(
                EVENT_MAP[event.kind], event.data or None
            )
        except Exception:
            log.debug("native event send failed: %s", event.kind, exc_info=True)


class ESPHomeBridge:
    def __init__(
        self,
        *,
        client: APIClient,
        sink: NativeEventSink,
        coordinator: TurnCoordinator,
        device_name: str,
        device_project: str,
        device: DeviceState,
        motion: MotionController,
    ) -> None:
        self._client = client
        self._sink = sink
        self._coordinator = coordinator
        self._device_name = device_name
        self._device_project = device_project
        self._device = device
        self._motion = motion
        self._reconnect: ReconnectLogic | None = None
        self._unsubscribe = None

    @property
    def connected(self) -> bool:
        return self._sink.connected

    async def start(self) -> None:
        async def on_connect() -> None:
            try:
                info = await self._client.device_info()
                if info.project_name != self._device_project:
                    raise RuntimeError(
                        f"expected project {self._device_project!r}, got "
                        f"{info.project_name!r}"
                    )
                entities, _ = await self._client.list_entities_services()
                self._device.bind(entities)
                self._motion.assert_bound()
                self._sink.connected = True
                self._unsubscribe = self._client.subscribe_voice_assistant(
                    handle_start=self._handle_start,
                    handle_stop=self._coordinator.on_stop,
                    handle_audio=self._coordinator.on_audio,
                )
                log.info(
                    "connected to %s at %s (ESPHome %s)",
                    info.name,
                    self._client.address,
                    info.esphome_version,
                )
            except Exception:
                self._sink.connected = False
                self._device.unbind()
                log.exception("device initialization failed")
                raise

        async def on_disconnect(expected_disconnect: bool) -> None:
            self._sink.connected = False
            self._device.unbind()
            self._unsubscribe = None
            await self._coordinator.on_disconnect()
            log.warning(
                "device disconnected (expected=%s)", expected_disconnect
            )

        async def on_connect_error(error: Exception) -> None:
            log.warning("device connection attempt failed: %s", error)

        self._reconnect = ReconnectLogic(
            client=self._client,
            on_connect=on_connect,
            on_disconnect=on_disconnect,
            zeroconf_instance=None,
            name=self._device_name,
            on_connect_error=on_connect_error,
        )
        await self._reconnect.start()

    async def stop(self) -> None:
        self._sink.connected = False
        await self._coordinator.close()
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        if self._reconnect is not None:
            await self._reconnect.stop()
        self._device.unbind()
        await self._client.disconnect()

    async def _handle_start(
        self,
        conversation_id: str,
        flags: int,
        audio_settings,
        wake_word_phrase: str | None,
    ) -> int:
        del conversation_id, flags, audio_settings, wake_word_phrase
        log.info("continuous voice capture requested")
        return await self._coordinator.on_start()


def make_client(
    host: str,
    port: int,
    encryption_key: str,
    *,
    expected_name: str,
    expected_mac: str,
) -> APIClient:
    return APIClient(
        host,
        port,
        None,
        client_info=f"andy-server/{__version__}",
        noise_psk=encryption_key,
        expected_name=expected_name,
        expected_mac=expected_mac,
    )
