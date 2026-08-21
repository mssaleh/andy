from __future__ import annotations

import asyncio

import pytest
from aioesphomeapi import (
    BinarySensorInfo,
    BinarySensorState,
    ButtonInfo,
    MediaPlayerCommand,
    MediaPlayerInfo,
    SensorInfo,
    SensorState,
    TextSensorInfo,
    TextSensorState,
)

from andy.actions import MotionAction
from andy.device import REQUIRED_STATES, DeviceState
from andy.speaker import SpeakerOutput
from andy.motion import (
    ACTION_PROGRAMS,
    MotionController,
    POSE_TARGETS,
    catalog_snapshot,
)


ENTITIES = [
    ButtonInfo(object_id="motion_home", key=1),
    ButtonInfo(object_id="motion_look_left_30_degrees", key=2),
    ButtonInfo(object_id="motion_look_right_30_degrees", key=3),
    ButtonInfo(object_id="motion_look_up_30_degrees", key=4),
    ButtonInfo(object_id="motion_look_down_15_degrees", key=5),
    ButtonInfo(object_id="motion_yaw_positive_10_degrees", key=6),
    ButtonInfo(object_id="motion_pitch_positive_10_degrees", key=7),
    ButtonInfo(object_id="motion_emergency_stop", key=8),
    ButtonInfo(object_id="conversation_follow_up", key=9),
    ButtonInfo(object_id="conversation_sleep", key=17),
    ButtonInfo(object_id="pause_capture_for_response", key=25),
    BinarySensorInfo(object_id="motion_active", key=10),
    BinarySensorInfo(object_id="motion_inhibited", key=11),
    TextSensorInfo(object_id="motion_state", key=12),
    SensorInfo(object_id="motion_starts", key=13),
    SensorInfo(object_id="motion_completions", key=14),
    SensorInfo(object_id="motion_faults", key=15),
    SensorInfo(object_id="announcement_starts", key=16),
    SensorInfo(object_id="announcement_finishes", key=18),
    MediaPlayerInfo(object_id="andy_speaker", key=19),
    SensorInfo(object_id="voice_turn_starts", key=20),
    SensorInfo(object_id="speech_detections", key=21),
    SensorInfo(object_id="voice_turn_ends", key=22),
    SensorInfo(object_id="voice_errors", key=23),
    TextSensorInfo(object_id="voice_state", key=24),
    SensorInfo(object_id="capture_pauses", key=26),
]


class Client:
    def __init__(self, *, finish_announcements: bool = True) -> None:
        self.callback = None
        self.finish_announcements = finish_announcements
        self.commands: list[int] = []
        self.starts = 0
        self.completions = 0
        self.faults = 0
        self.announcement_starts = 0
        self.announcement_finishes = 0
        self.capture_pauses = 0
        self.media_commands: list[dict[str, object]] = []

    def subscribe_states(self, callback) -> None:
        self.callback = callback

    def emit_initial(
        self, *, inhibited: bool = False, active: bool = False
    ) -> None:
        self.emit(BinarySensorState(key=10, state=active))
        self.emit(BinarySensorState(key=11, state=inhibited))
        self.emit(TextSensorState(key=12, state="idle: torque released; servo rail off"))
        self.emit(SensorState(key=13, state=float(self.starts)))
        self.emit(SensorState(key=14, state=float(self.completions)))
        self.emit(SensorState(key=15, state=float(self.faults)))
        self.emit(SensorState(key=16, state=float(self.announcement_starts)))
        self.emit(SensorState(key=18, state=float(self.announcement_finishes)))
        self.emit(SensorState(key=20, state=1.0))
        self.emit(SensorState(key=21, state=0.0))
        self.emit(SensorState(key=22, state=0.0))
        self.emit(SensorState(key=23, state=0.0))
        self.emit(TextSensorState(key=24, state="listening"))
        self.emit(SensorState(key=26, state=float(self.capture_pauses)))

    def emit(self, state: object) -> None:
        assert self.callback is not None
        self.callback(state)

    def button_command(self, key: int, device_id: int = 0) -> None:
        del device_id
        self.commands.append(key)
        if key == 8:
            self.emit(BinarySensorState(key=10, state=False))
            return
        if key == 9:
            return
        if key == 17:
            return
        if key == 25:
            self.capture_pauses += 1
            self.emit(SensorState(key=26, state=float(self.capture_pauses)))
            self.emit(TextSensorState(key=24, state="capture paused"))
            return
        targets = {
            1: (466, 620),
            2: (381, 620),
            3: (552, 620),
            4: (466, 705),
            5: (466, 577),
            6: (495, 620),
            7: (466, 648),
        }
        yaw, pitch = targets[key]
        self.starts += 1
        loop = asyncio.get_running_loop()
        loop.call_soon(self.emit, BinarySensorState(key=10, state=True))
        loop.call_soon(self.emit, SensorState(key=13, state=float(self.starts)))
        loop.call_later(0.001, self._complete, yaw, pitch)

    def media_player_command(
        self,
        key: int,
        *,
        command: MediaPlayerCommand | None = None,
        volume: float | None = None,
        media_url: str | None = None,
        announcement: bool | None = None,
        device_id: int = 0,
    ) -> None:
        del volume, device_id
        self.media_commands.append(
            {
                "key": key,
                "command": command,
                "media_url": media_url,
                "announcement": announcement,
            }
        )
        if media_url is not None:
            self.announcement_starts += 1
            loop = asyncio.get_running_loop()
            loop.call_soon(
                self.emit,
                SensorState(key=16, state=float(self.announcement_starts)),
            )
            if self.finish_announcements:
                self.announcement_finishes += 1
                loop.call_later(
                    0.001,
                    self.emit,
                    SensorState(key=18, state=float(self.announcement_finishes)),
                )

    def _complete(self, yaw: int, pitch: int) -> None:
        self.completions += 1
        self.emit(SensorState(key=14, state=float(self.completions)))
        self.emit(
            TextSensorState(
                key=12,
                state=(
                    f"complete: yaw={yaw}/{yaw} error=0 pitch={pitch}/{pitch} "
                    "error=0 torque=0/0 peak_load=0/0"
                ),
            )
        )
        self.emit(BinarySensorState(key=10, state=False))


def _stack(client, **kwargs):
    """Build the device stack the way the app does, from a fake client."""
    device = DeviceState(client)  # type: ignore[arg-type]
    device.bind(ENTITIES)
    return device, MotionController(device, **kwargs), SpeakerOutput(device)

@pytest.mark.asyncio
async def test_fixed_motion_waits_for_voice_idle_and_verifies_completion() -> None:
    client = Client()
    _device, controller, speaker = _stack(client, idle_timeout=0.1, motion_timeout=0.1)
    client.emit_initial(active=True)

    task = asyncio.create_task(controller.execute(MotionAction.YAW_POSITIVE_10))
    await asyncio.sleep(0)
    assert client.commands == []

    client.emit(BinarySensorState(key=10, state=False))
    status = await task

    assert status.startswith("complete: yaw=495/495")
    assert client.commands == [6]
    assert controller.snapshot()["motion_active"] is False


@pytest.mark.asyncio
async def test_named_program_executes_each_fixed_pose_and_returns_home() -> None:
    client = Client()
    _device, controller, speaker = _stack(client, idle_timeout=0.1, motion_timeout=0.1)
    client.emit_initial()

    status = await controller.execute(MotionAction.NOD_YES)

    assert status.startswith("complete: yaw=466/466")
    assert client.commands == [5, 4, 5, 1]
    assert client.starts == 4
    assert client.completions == 4
    assert controller.snapshot()["program"] is None


def test_catalog_exposes_every_action_as_calibrated_fixed_steps() -> None:
    catalog = catalog_snapshot()

    assert [item["name"] for item in catalog] == [
        action.value for action in MotionAction
    ]
    for item, (action, program) in zip(catalog, ACTION_PROGRAMS.items(), strict=True):
        assert item["say"]
        assert item["steps"] == [
            {
                "pose": step.pose.value,
                "target": list(POSE_TARGETS[step.pose]),
                "hold_seconds": step.hold_seconds,
            }
            for step in program
        ]
        assert item["diagnostic"] == (
            action
            in {
                MotionAction.YAW_POSITIVE_10,
                MotionAction.PITCH_POSITIVE_10,
            }
        )


def test_gaze_program_holds_the_visible_pose_then_returns_home() -> None:
    look_right = next(
        item for item in catalog_snapshot() if item["name"] == "look_right"
    )

    assert look_right["steps"] == [
        {
            "pose": "right_30",
            "target": [552, 620],
            "hold_seconds": 1.0,
        },
        {
            "pose": "home",
            "target": [466, 620],
            "hold_seconds": 0.2,
        },
    ]


@pytest.mark.asyncio
async def test_follow_up_button_opens_only_from_safe_idle() -> None:
    client = Client()
    _device, controller, speaker = _stack(client, idle_timeout=0.1, motion_timeout=0.1)
    client.emit_initial()

    await controller.start_follow_up()

    assert client.commands == [9]


@pytest.mark.asyncio
async def test_sleep_button_stops_passive_listening() -> None:
    client = Client()
    _device, controller, speaker = _stack(client, idle_timeout=0.1, motion_timeout=0.1)
    client.emit_initial(inhibited=True)

    await controller.stop_passive()

    assert client.commands == [17]


@pytest.mark.asyncio
async def test_announcement_output_waits_for_start_and_finish_counters() -> None:
    client = Client()
    _device, controller, speaker = _stack(client, idle_timeout=0.1, motion_timeout=0.1)
    client.emit_initial()

    await speaker.play_announcement("http://andy.test/tts/one.wav")
    await speaker.stop_announcement()

    assert client.media_commands == [
        {
            "key": 19,
            "command": None,
            "media_url": "http://andy.test/tts/one.wav",
            "announcement": True,
        },
        {
            "key": 19,
            "command": MediaPlayerCommand.STOP,
            "media_url": None,
            "announcement": True,
        },
    ]
    assert client.commands == [25]


@pytest.mark.asyncio
async def test_cancelled_announcement_stops_device_playback() -> None:
    client = Client(finish_announcements=False)
    _device, controller, speaker = _stack(client, idle_timeout=0.1, motion_timeout=0.1)
    client.emit_initial()

    task = asyncio.create_task(
        speaker.play_announcement("http://andy.test/tts/stalled.wav")
    )
    while not client.media_commands:
        await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert client.media_commands[-1] == {
        "key": 19,
        "command": MediaPlayerCommand.STOP,
        "media_url": None,
        "announcement": True,
    }


@pytest.mark.asyncio
async def test_disconnect_aborts_pending_motion_without_a_command() -> None:
    client = Client()
    _device, controller, speaker = _stack(client, idle_timeout=0.1, motion_timeout=0.1)
    client.emit_initial(active=True)

    task = asyncio.create_task(controller.execute(MotionAction.HOME))
    await asyncio.sleep(0)
    _device.unbind()

    with pytest.raises(RuntimeError, match="device disconnected"):
        await task
    assert client.commands == []


@pytest.mark.asyncio
async def test_latched_inhibit_refuses_immediately_without_holding_the_lock() -> None:
    """A latched fault is answered now, not after the idle timeout expires.

    The firmware clears `motion_inhibited` only on the `Clear motion inhibit`
    button or a reboot, so nothing that happens inside the wait can clear it.
    Waiting spends the whole idle timeout on a knowable refusal and holds the
    motion lock against every request queued behind it.
    """
    client = Client()
    _device, controller, speaker = _stack(client, idle_timeout=30.0, motion_timeout=30.0)
    client.emit_initial(inhibited=True)

    with pytest.raises(RuntimeError, match="inhibited by a latched firmware fault"):
        await asyncio.wait_for(controller.execute(MotionAction.HOME), timeout=1.0)
    assert client.commands == []

    # The lock is free, so the next request is answered just as promptly.
    with pytest.raises(RuntimeError, match="inhibited by a latched firmware fault"):
        await asyncio.wait_for(
            controller.execute(MotionAction.YAW_POSITIVE_10), timeout=1.0
        )
    assert client.commands == []

def test_combined_firmware_entities_are_mandatory() -> None:
    client = Client()
    device = DeviceState(client)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="motion_emergency_stop"):
        device.bind(
            [
                entity
                for entity in ENTITIES
                if entity.object_id != "motion_emergency_stop"
            ]
        )


def test_motion_asserts_its_own_pose_buttons() -> None:
    """Readiness is split: the device checks its needs, motion checks motion's."""
    client = Client()
    device = DeviceState(client)  # type: ignore[arg-type]
    device.bind(
        [e for e in ENTITIES if e.object_id != "motion_look_right_30_degrees"]
    )
    controller = MotionController(device)

    with pytest.raises(RuntimeError, match="motion_look_right_30_degrees"):
        controller.assert_bound()


def test_device_keeps_every_state_not_only_the_required_ones() -> None:
    """The old controller discarded anything outside REQUIRED_STATES."""
    client = Client()
    device = DeviceState(client)  # type: ignore[arg-type]
    device.bind(ENTITIES)
    client.emit_initial()

    assert device.ready
    # Nothing is filtered away any more.
    assert set(device.states) >= set(REQUIRED_STATES)
