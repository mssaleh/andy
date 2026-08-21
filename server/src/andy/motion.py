from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
import re

from .device import DeviceState

from .actions import CANONICAL_REQUESTS, MotionAction


class FixedPose(StrEnum):
    HOME = "home"
    LEFT_30 = "left_30"
    RIGHT_30 = "right_30"
    UP_30 = "up_30"
    DOWN_15 = "down_15"
    YAW_POSITIVE_10 = "yaw_positive_10"
    PITCH_POSITIVE_10 = "pitch_positive_10"


@dataclass(frozen=True, slots=True)
class MotionStep:
    pose: FixedPose
    hold_seconds: float = 0.2


POSE_BUTTONS = {
    FixedPose.HOME: "motion_home",
    FixedPose.LEFT_30: "motion_look_left_30_degrees",
    FixedPose.RIGHT_30: "motion_look_right_30_degrees",
    FixedPose.UP_30: "motion_look_up_30_degrees",
    FixedPose.DOWN_15: "motion_look_down_15_degrees",
    FixedPose.YAW_POSITIVE_10: "motion_yaw_positive_10_degrees",
    FixedPose.PITCH_POSITIVE_10: "motion_pitch_positive_10_degrees",
}
POSE_TARGETS = {
    FixedPose.HOME: (466, 620),
    FixedPose.LEFT_30: (381, 620),
    FixedPose.RIGHT_30: (552, 620),
    FixedPose.UP_30: (466, 705),
    FixedPose.DOWN_15: (466, 577),
    FixedPose.YAW_POSITIVE_10: (495, 620),
    FixedPose.PITCH_POSITIVE_10: (466, 648),
}


def _program(*poses: FixedPose) -> tuple[MotionStep, ...]:
    return tuple(MotionStep(pose) for pose in poses)


def _gaze_program(pose: FixedPose) -> tuple[MotionStep, ...]:
    return (MotionStep(pose, hold_seconds=1.0), MotionStep(FixedPose.HOME))


ACTION_PROGRAMS: dict[MotionAction, tuple[MotionStep, ...]] = {
    MotionAction.HOME: _program(FixedPose.HOME),
    MotionAction.LOOK_LEFT: _gaze_program(FixedPose.LEFT_30),
    MotionAction.LOOK_RIGHT: _gaze_program(FixedPose.RIGHT_30),
    MotionAction.LOOK_UP: _gaze_program(FixedPose.UP_30),
    MotionAction.NOD_YES: _program(
        FixedPose.DOWN_15,
        FixedPose.UP_30,
        FixedPose.DOWN_15,
        FixedPose.HOME,
    ),
    MotionAction.SHAKE_NO: _program(
        FixedPose.LEFT_30,
        FixedPose.RIGHT_30,
        FixedPose.LEFT_30,
        FixedPose.HOME,
    ),
    MotionAction.BOW: _program(FixedPose.DOWN_15, FixedPose.HOME),
    MotionAction.GREET: _program(
        FixedPose.UP_30,
        FixedPose.LEFT_30,
        FixedPose.RIGHT_30,
        FixedPose.HOME,
    ),
    MotionAction.CELEBRATE: _program(
        FixedPose.UP_30,
        FixedPose.RIGHT_30,
        FixedPose.LEFT_30,
        FixedPose.UP_30,
        FixedPose.HOME,
    ),
    MotionAction.SCAN: _program(
        FixedPose.LEFT_30,
        FixedPose.HOME,
        FixedPose.RIGHT_30,
        FixedPose.HOME,
        FixedPose.UP_30,
        FixedPose.HOME,
    ),
    MotionAction.DANCE: _program(
        FixedPose.LEFT_30,
        FixedPose.RIGHT_30,
        FixedPose.UP_30,
        FixedPose.RIGHT_30,
        FixedPose.LEFT_30,
        FixedPose.DOWN_15,
        FixedPose.UP_30,
        FixedPose.HOME,
    ),
    MotionAction.YAW_POSITIVE_10: _program(FixedPose.YAW_POSITIVE_10),
    MotionAction.PITCH_POSITIVE_10: _program(FixedPose.PITCH_POSITIVE_10),
}


def catalog_snapshot() -> list[dict[str, object]]:
    return [
        {
            "name": action.value,
            "say": CANONICAL_REQUESTS[action],
            "steps": [
                {
                    "pose": step.pose.value,
                    "target": list(POSE_TARGETS[step.pose]),
                    "hold_seconds": step.hold_seconds,
                }
                for step in program
            ],
            "diagnostic": action
            in {
                MotionAction.YAW_POSITIVE_10,
                MotionAction.PITCH_POSITIVE_10,
            },
        }
        for action, program in ACTION_PROGRAMS.items()
    ]


#: What a firmware program leaves behind: torque released and the rail off.
_TERMINAL = re.compile(r"^idle: torque released; servo rail off\b")

_COMPLETE = re.compile(
    r"^complete: yaw=(?P<yaw_position>\d+)/(?P<yaw_target>\d+) "
    r"error=(?P<yaw_error>\d+) pitch=(?P<pitch_position>\d+)/"
    r"(?P<pitch_target>\d+) error=(?P<pitch_error>\d+) "
    r"torque=(?P<yaw_torque>\d+)/(?P<pitch_torque>\d+)\b"
)


class MotionController:
    """Named programs built only from verified fixed poses.

    Reads device state rather than owning the subscription, and knows nothing
    about the speaker. What it still owns is the safety contract: one program at
    a time, an exact expected target per pose, counter deltas that must move by
    exactly one, tracking inside tolerance, torque released, and an emergency
    stop on any interruption.
    """

    def __init__(
        self,
        device: DeviceState,
        *,
        idle_timeout: float = 45.0,
        motion_timeout: float = 20.0,
    ) -> None:
        if idle_timeout <= 0 or motion_timeout <= 0:
            raise ValueError("motion timeouts must be positive")
        self._device = device
        self._idle_timeout = idle_timeout
        self._motion_timeout = motion_timeout
        self._lock = asyncio.Lock()
        self._active_action: MotionAction | None = None
        self._program_step = 0
        self._program_steps = 0

    @property
    def ready(self) -> bool:
        return self._device.ready

    def _idle(self) -> bool:
        """Idle means the device is free, not merely between poses.

        `motion_program` is true while the firmware runs an emotion idiom of its
        own. Both authorities drive the same servos and the same counters, so
        starting a named program on top of one produces a completion the server
        cannot account for. Absent on older firmware, which reads as not busy.
        """
        device = self._device
        return (
            device.get("motion_active") is False
            and device.get("motion_inhibited") is False
            and device.get("motion_program") is not True
        )

    def assert_bound(self) -> None:
        """Motion keeps its own readiness assertion, separate from the device's."""
        missing = sorted(
            name for name in POSE_BUTTONS.values() if not self._device.has_button(name)
        )
        if missing:
            raise RuntimeError(
                "firmware is missing motion buttons: " + ", ".join(missing)
            )

    PROGRAM_SELECT = "motion_program_name"
    PROGRAM_BUTTON = "run_motion_program"

    async def execute(self, action: MotionAction) -> str:
        """Run a named program, preferring the firmware's own program path.

        Pressing a pose button per step makes the device power and settle the
        rail for every pose, which is why a server-driven dance took about
        twenty seconds of stop-start. The firmware can run the whole catalog as
        one program with the rail held throughout and the same guards on every
        frame. Older firmware without that path still works, one pose at a time.
        """
        if action.value in self._device.select_options(self.PROGRAM_SELECT):
            return await self._execute_firmware_program(action)
        return await self._execute_pose_by_pose(action)

    def _assert_not_inhibited(self) -> None:
        """Refuse at once when the firmware has latched a motion fault.

        The latch clears only when the `Clear motion inhibit` button is pressed
        or the device reconnects, and neither can happen while this coroutine
        holds the motion lock. Waiting for `_idle` therefore spends the whole
        idle timeout to arrive at a failure that was knowable on the first
        read, and it holds the lock against every request queued behind it.
        """
        if self._device.get("motion_inhibited") is True:
            raise RuntimeError(
                "motion is inhibited by a latched firmware fault: press "
                "'Clear motion inhibit' or reconnect the device"
            )

    async def _wait_for_idle(self) -> None:
        """Wait for the device to be free, and name what held it if it is not.

        `_idle` reads three flags and a bare timeout names none of them, yet
        they point at different places: a latched fault is a servo problem, a
        held program means the firmware is running choreography of its own,
        and a busy flag means a pose is still in flight. None of that is
        recoverable from the timeout after the fact.
        """
        device = self._device
        try:
            await device.wait_for(self._idle, self._idle_timeout, "motion idle")
        except TimeoutError as exc:
            raise TimeoutError(
                f"{exc}: motion_active={device.get('motion_active')!r} "
                f"motion_inhibited={device.get('motion_inhibited')!r} "
                f"motion_program={device.get('motion_program')!r} "
                f"motion_state={device.get('motion_state')!r}"
            ) from exc

    async def _execute_firmware_program(self, action: MotionAction) -> str:
        device = self._device
        async with self._lock:
            await device.wait_for(
                lambda: device.ready, self._idle_timeout, "initial motion state"
            )
            self._assert_not_inhibited()
            await self._wait_for_idle()
            self._active_action = action
            before_starts = device.counter("motion_starts")
            before_completions = device.counter("motion_completions")
            before_faults = device.counter("motion_faults")
            try:
                device.select_option(self.PROGRAM_SELECT, action.value)
                device.press(self.PROGRAM_BUTTON)
                # The device claims the mechanism before it settles the rail, so
                # this is the point at which the program is genuinely running.
                await device.wait_for(
                    lambda: device.get("motion_program") is True,
                    self._motion_timeout,
                    f"{action.value} program start",
                )
                # Wait for the terminal state too, not just for the busy flag
                # to drop. The device publishes its final state last, and it is
                # a tunnel round trip away, so reading the counters the moment
                # the flag clears reads the *previous* run's values and reports
                # a fault that never happened.
                #
                # A fault is also an ending. The firmware abandons a faulted
                # program without ever publishing the completion this waits
                # for, so watching only for success spent the whole timeout on
                # a failure the counter had already reported, and Andy stood
                # still for forty-five seconds after saying he would move.
                await device.wait_for(
                    lambda: device.counter("motion_faults") != before_faults
                    or (
                        device.get("motion_program") is not True
                        and device.get("motion_active") is False
                        and _TERMINAL.match(str(device.get("motion_state") or ""))
                        is not None
                    ),
                    self._idle_timeout,
                    f"{action.value} program completion",
                )
            except BaseException:
                if device.connected:
                    device.press("motion_emergency_stop")
                raise
            finally:
                self._active_action = None
                self._program_step = 0
                self._program_steps = 0

            starts = device.counter("motion_starts")
            completions = device.counter("motion_completions")
            faults = device.counter("motion_faults")
            status = str(device.get("motion_state"))
            ran = starts - before_starts
            finished = completions - before_completions
            # The firmware owns the choreography, so the server does not assert
            # a frame count it would only be guessing at. What it asserts is the
            # part that matters: something moved, everything that started also
            # completed, and nothing faulted.
            if faults != before_faults:
                raise RuntimeError(
                    f"motion fault during {action.value}: {status}"
                )
            if ran < 1:
                raise RuntimeError(f"{action.value} moved nothing")
            if finished != ran:
                raise RuntimeError(
                    f"{action.value} started {ran} poses but completed {finished}"
                )
            self._program_steps = ran
            # A firmware program ends on `end_motion_program`, which publishes
            # its terminal state only after it has verified torque release and
            # cut the rail. That is the completion evidence here; the per-pose
            # target and tracking checks already happened on the device, and any
            # failure would have moved the fault counter checked above.
            if not _TERMINAL.match(status):
                raise RuntimeError(f"motion did not end safely: {status}")
            return status

    async def _execute_pose_by_pose(self, action: MotionAction) -> str:
        program = ACTION_PROGRAMS[action]
        device = self._device
        async with self._lock:
            await device.wait_for(
                lambda: device.ready, self._idle_timeout, "initial motion state"
            )
            self._assert_not_inhibited()
            await self._wait_for_idle()
            self._active_action = action
            self._program_steps = len(program)
            try:
                status = ""
                for index, step in enumerate(program, start=1):
                    self._program_step = index
                    status = await self._execute_pose(step.pose)
                    if index < len(program) and step.hold_seconds > 0:
                        await asyncio.sleep(step.hold_seconds)
                return status
            finally:
                self._active_action = None
                self._program_step = 0
                self._program_steps = 0

    async def start_follow_up(self) -> None:
        device = self._device
        async with self._lock:
            await device.wait_for(
                lambda: device.ready and self._idle(),
                self._idle_timeout,
                "idle before conversational follow-up",
            )
            device.press("conversation_follow_up")

    async def stop_passive(self) -> None:
        async with self._lock:
            device = self._device
            if not device.connected:
                raise RuntimeError(
                    "device disconnected while stopping passive listening"
                )
            device.press("conversation_sleep")

    async def _execute_pose(self, pose: FixedPose) -> str:
        device = self._device
        await device.wait_for(
            self._idle,
            self._idle_timeout,
            f"idle before {pose.value}",
        )
        before_starts = device.counter("motion_starts")
        before_completions = device.counter("motion_completions")
        before_faults = device.counter("motion_faults")
        pressed = False
        try:
            device.press(POSE_BUTTONS[pose])
            pressed = True
            # Wait for *this* pose to start, not merely for the robot to become
            # busy. The firmware can be running an emotion idiom of its own on
            # the same servos and the same counters, and its activity would
            # otherwise satisfy a check for "something is moving" and then for
            # "something completed", leaving the server certain it moved when it
            # never did.
            await device.wait_for(
                lambda: device.counter("motion_starts") > before_starts,
                self._motion_timeout,
                f"{pose.value} start",
            )
            await device.wait_for(
                lambda: device.get("motion_active") is False
                and (
                    device.counter("motion_completions") > before_completions
                    or device.counter("motion_faults") > before_faults
                )
                and isinstance(device.get("motion_state"), str)
                and str(device.get("motion_state")).startswith(
                    ("complete:", "fault:")
                ),
                self._motion_timeout,
                f"{pose.value} completion",
            )
        except BaseException:
            if pressed and device.connected:
                device.press("motion_emergency_stop")
                try:
                    await device.wait_for(
                        lambda: device.get("motion_active") is False,
                        2.0,
                        "emergency stop",
                    )
                except Exception:
                    pass
            raise

        starts = device.counter("motion_starts")
        completions = device.counter("motion_completions")
        faults = device.counter("motion_faults")
        status = str(device.get("motion_state"))
        if starts != before_starts + 1:
            raise RuntimeError(
                f"motion start counter changed {before_starts}->{starts}"
            )
        if completions != before_completions + 1:
            raise RuntimeError(
                "motion completion counter changed "
                f"{before_completions}->{completions}"
            )
        if faults != before_faults:
            raise RuntimeError(
                f"motion fault counter changed {before_faults}->{faults}: {status}"
            )
        self._validate_completion(pose, status)
        return status

    @staticmethod
    def _validate_completion(pose: FixedPose, status: str) -> None:
        match = _COMPLETE.match(status)
        if match is None:
            raise RuntimeError(f"motion did not complete safely: {status}")
        fields = {name: int(value) for name, value in match.groupdict().items()}
        target = (fields["yaw_target"], fields["pitch_target"])
        if target != POSE_TARGETS[pose]:
            raise RuntimeError(
                f"motion reported target {target}, expected {POSE_TARGETS[pose]}"
            )
        if fields["yaw_error"] > 14 or fields["pitch_error"] > 14:
            raise RuntimeError(f"motion exceeded tracking tolerance: {status}")
        if fields["yaw_torque"] != 0 or fields["pitch_torque"] != 0:
            raise RuntimeError(f"motion left torque enabled: {status}")

    def snapshot(self) -> dict[str, object]:
        device = self._device
        return {
            "connected": device.connected,
            "ready": device.ready,
            "motion_active": device.get("motion_active"),
            "motion_inhibited": device.get("motion_inhibited"),
            "motion_starts": device.get("motion_starts"),
            "motion_completions": device.get("motion_completions"),
            "motion_faults": device.get("motion_faults"),
            "turn_starts": device.get("voice_turn_starts"),
            "speech_detections": device.get("speech_detections"),
            "turn_ends": device.get("voice_turn_ends"),
            "voice_errors": device.get("voice_errors"),
            "voice_state": device.get("voice_state"),
            "capture_pauses": device.get("capture_pauses"),
            "announcement_starts": device.get("announcement_starts"),
            "announcement_finishes": device.get("announcement_finishes"),
            "motion_state": device.get("motion_state"),
            "program": (
                self._active_action.value
                if self._active_action is not None
                else None
            ),
            "program_step": self._program_step,
            "program_steps": self._program_steps,
        }
