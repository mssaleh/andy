"""The device façade: one subscription, one snapshot, one place to command from.

Andy exposes far more than motion. Presence, ambient light, head touch, shake,
screen touch, battery, body power, infrared, emotion and a camera all arrive on
the same encrypted session, and every one of them is useful to the agent. This
module owns that session's state so the motion controller and the speaker can be
about motion and speech rather than about subscriptions.

Readiness is still asserted against a required set, but it is only a readiness
check. Nothing is discarded for not being on it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from datetime import datetime
import logging
from typing import Any

from aioesphomeapi import (
    APIClient,
    BinarySensorInfo,
    BinarySensorState,
    ButtonInfo,
    CameraInfo,
    EntityInfo,
    LightInfo,
    MediaPlayerCommand,
    MediaPlayerInfo,
    NumberInfo,
    SelectInfo,
    SensorInfo,
    SensorState,
    SwitchInfo,
    TextSensorInfo,
    TextSensorState,
)

log = logging.getLogger("andy.device")

StateValue = bool | float | str

#: Entities whose absence means the firmware is not the one this server drives.
#: Used only to answer "is the device ready", never to filter what is kept.
REQUIRED_STATES: frozenset[str] = frozenset(
    {
        "motion_active",
        "motion_inhibited",
        "motion_state",
        "motion_starts",
        "motion_completions",
        "motion_faults",
        "voice_turn_starts",
        "speech_detections",
        "voice_turn_ends",
        "voice_errors",
        "voice_state",
        "capture_pauses",
        "announcement_starts",
        "announcement_finishes",
    }
)

REQUIRED_BUTTONS: frozenset[str] = frozenset(
    {
        "conversation_follow_up",
        "pause_capture_for_response",
        "conversation_sleep",
        "motion_emergency_stop",
    }
)

MEDIA_PLAYER_ID = "andy_speaker"


def _state_value(state: object) -> StateValue | None:
    if isinstance(state, (BinarySensorState, SensorState, TextSensorState)):
        return None if state.missing_state else state.state
    return None


def _part_of_day(hour: int, elevation: float | None, daylight: bool | None) -> str:
    """Morning, afternoon, evening or night, decided by the sky where possible.

    The clock alone gets this wrong twice a year in opposite directions: eight
    in the evening is broad daylight in June and long dark in December. The
    robot carries its own position and works out where the sun is, so the sky
    is the authority and the hour only names which side of noon it is.
    """
    if elevation is not None:
        if elevation < -6.0:
            return "night"
        if elevation < 5.0:
            return "around sunrise" if hour < 12 else "around sunset"
    elif daylight is False:
        return "night"
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    return "evening"


def _touched_zones(left: str | None, centre: str | None, right: str | None) -> str | None:
    """Which part of Andy's head a hand is on, rather than three raw channels."""
    zones = [
        name
        for name, value in (("left", left), ("centre", centre), ("right", right))
        if value and value.strip().casefold() not in {"no touch", "none", ""}
    ]
    return ", ".join(zones) if zones else None


def _spoken_duration(seconds: float) -> str:
    """A length of time as someone would say it, not as a counter."""
    total = int(max(0.0, seconds))
    if total < 90:
        return f"{total} seconds"
    minutes = total // 60
    if minutes < 90:
        return f"{minutes} minutes"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} hours"
    return f"{hours // 24} days"


class DeviceState:
    """Subscribes once, keeps everything, and is the only way to command."""

    def __init__(self, client: APIClient) -> None:
        self._client = client
        self._states: dict[str, StateValue] = {}
        self._buttons: dict[str, ButtonInfo] = {}
        self._selects: dict[str, SelectInfo] = {}
        self._numbers: dict[str, NumberInfo] = {}
        self._switches: dict[str, SwitchInfo] = {}
        self._lights: dict[str, LightInfo] = {}
        self._cameras: dict[str, CameraInfo] = {}
        self._media_player: MediaPlayerInfo | None = None
        self._state_entities: dict[tuple[int, int], EntityInfo] = {}
        self._connected = False
        self._generation = 0
        self._changed = asyncio.Event()
        self._listeners: list[Callable[[str, StateValue], None]] = []

    # -- lifecycle ---------------------------------------------------------

    def bind(self, entities: Sequence[EntityInfo]) -> None:
        """Register the device's entities and start the single subscription."""
        buttons = {e.object_id: e for e in entities if isinstance(e, ButtonInfo)}
        missing_buttons = sorted(REQUIRED_BUTTONS - buttons.keys())
        if missing_buttons:
            raise RuntimeError(
                "firmware is missing required buttons: " + ", ".join(missing_buttons)
            )

        media_players = [
            e
            for e in entities
            if isinstance(e, MediaPlayerInfo) and e.object_id == MEDIA_PLAYER_ID
        ]
        if len(media_players) != 1:
            raise RuntimeError(
                f"firmware must expose exactly one {MEDIA_PLAYER_ID} media player"
            )

        state_entities = {
            (e.key, e.device_id): e
            for e in entities
            if isinstance(e, (BinarySensorInfo, SensorInfo, TextSensorInfo))
        }
        available = {e.object_id for e in state_entities.values()}
        missing_states = sorted(REQUIRED_STATES - available)
        if missing_states:
            raise RuntimeError(
                "firmware is missing required state: " + ", ".join(missing_states)
            )

        self._generation += 1
        generation = self._generation
        self._buttons = buttons
        self._selects = {e.object_id: e for e in entities if isinstance(e, SelectInfo)}
        self._numbers = {e.object_id: e for e in entities if isinstance(e, NumberInfo)}
        self._switches = {e.object_id: e for e in entities if isinstance(e, SwitchInfo)}
        self._lights = {e.object_id: e for e in entities if isinstance(e, LightInfo)}
        self._cameras = {e.object_id: e for e in entities if isinstance(e, CameraInfo)}
        self._media_player = media_players[0]
        self._state_entities = state_entities
        self._states.clear()
        self._connected = True
        self._changed.set()

        def on_state(state: object) -> None:
            if generation != self._generation:
                return
            entity = self._state_entities.get(
                (getattr(state, "key", None), getattr(state, "device_id", None))
            )
            if entity is None:
                return
            value = _state_value(state)
            if value is None:
                return
            previous = self._states.get(entity.object_id)
            self._states[entity.object_id] = value
            self._changed.set()
            if previous != value:
                for listener in self._listeners:
                    try:
                        listener(entity.object_id, value)
                    except Exception:
                        log.exception("device state listener failed")

        self._client.subscribe_states(on_state)
        log.info(
            "bound %d entities (%d stateful, %d buttons)",
            len(entities),
            len(state_entities),
            len(buttons),
        )

    def unbind(self) -> None:
        self._generation += 1
        self._connected = False
        self._buttons.clear()
        self._selects.clear()
        self._numbers.clear()
        self._switches.clear()
        self._lights.clear()
        self._cameras.clear()
        self._media_player = None
        self._state_entities.clear()
        self._states.clear()
        self._changed.set()

    # -- reading -----------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def ready(self) -> bool:
        return self._connected and REQUIRED_STATES.issubset(self._states)

    @property
    def states(self) -> dict[str, StateValue]:
        return dict(self._states)

    def get(self, object_id: str) -> StateValue | None:
        return self._states.get(object_id)

    def counter(self, object_id: str) -> int:
        value = self._states.get(object_id)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RuntimeError(f"missing or invalid {object_id}: {value!r}")
        rounded = int(value)
        if rounded != value:
            raise RuntimeError(f"non-integral {object_id}: {value!r}")
        return rounded

    def has_button(self, object_id: str) -> bool:
        return object_id in self._buttons

    def has_camera(self) -> bool:
        return bool(self._cameras)

    def subscribe(self, listener: Callable[[str, StateValue], None]) -> None:
        """Called for every state that actually changed value."""
        self._listeners.append(listener)

    async def wait_for(
        self, predicate: Callable[[], bool], timeout: float, phase: str
    ) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            if not self._connected:
                raise RuntimeError(f"device disconnected while waiting for {phase}")
            if predicate():
                return
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError(f"timed out waiting for {phase}")
            self._changed.clear()
            if predicate():
                continue
            await asyncio.wait_for(self._changed.wait(), timeout=remaining)

    # -- commanding --------------------------------------------------------

    def press(self, object_id: str) -> None:
        button = self._buttons.get(object_id)
        if button is None:
            raise RuntimeError(f"device has no button {object_id}")
        if not self._connected:
            raise RuntimeError(f"device disconnected while pressing {object_id}")
        self._client.button_command(button.key, button.device_id)

    def select_option(self, object_id: str, option: str) -> None:
        entity = self._selects.get(object_id)
        if entity is None:
            raise RuntimeError(f"device has no select {object_id}")
        if option not in entity.options:
            raise RuntimeError(f"{object_id} has no option {option!r}")
        if not self._connected:
            raise RuntimeError(f"device disconnected while setting {object_id}")
        self._client.select_command(entity.key, option, device_id=entity.device_id)

    def set_number(self, object_id: str, value: float) -> None:
        entity = self._numbers.get(object_id)
        if entity is None:
            raise RuntimeError(f"device has no number {object_id}")
        clamped = min(max(value, entity.min_value), entity.max_value)
        if not self._connected:
            raise RuntimeError(f"device disconnected while setting {object_id}")
        self._client.number_command(entity.key, clamped, device_id=entity.device_id)

    def select_options(self, object_id: str) -> tuple[str, ...]:
        entity = self._selects.get(object_id)
        return tuple(entity.options) if entity is not None else ()

    def play_media(self, url: str) -> None:
        if not self._connected or self._media_player is None:
            raise RuntimeError("device disconnected while starting announcement")
        self._client.media_player_command(
            self._media_player.key,
            media_url=url,
            announcement=True,
            device_id=self._media_player.device_id,
        )

    def stop_media(self) -> None:
        if not self._connected or self._media_player is None:
            return
        self._client.media_player_command(
            self._media_player.key,
            command=MediaPlayerCommand.STOP,
            announcement=True,
            device_id=self._media_player.device_id,
        )

    # -- reporting ---------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Everything, for observation."""
        return {
            "connected": self._connected,
            "ready": self.ready,
            "entities": {
                "buttons": sorted(self._buttons),
                "selects": sorted(self._selects),
                "numbers": sorted(self._numbers),
                "switches": sorted(self._switches),
                "lights": sorted(self._lights),
                "cameras": sorted(self._cameras),
                "media_player": (
                    self._media_player.object_id if self._media_player else None
                ),
            },
            "states": dict(sorted(self._states.items())),
        }

    def interpreted(self) -> dict[str, Any]:
        """Facts, for the agent prompt.

        The model is given what a person in the room could tell, never raw
        counters. Counters grow without bound and mean nothing to a language
        model; "someone is here" and "the battery is low" mean everything.

        Each fact is named for what its sensor can actually know. A fact named
        wider than its sensor is not a small inaccuracy: the model answers from
        it confidently, and Andy states something about the room that is false.
        """
        states = self._states

        def flag(object_id: str) -> bool | None:
            value = states.get(object_id)
            return value if isinstance(value, bool) else None

        def number(object_id: str) -> float | None:
            value = states.get(object_id)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None
            return round(float(value), 2)

        def text(object_id: str) -> str | None:
            value = states.get(object_id)
            return value if isinstance(value, str) else None

        ambient = number("ambient_light")
        voice = text("voice_state") or "unknown"
        emotion = text("emotion_state")

        # What time it is, because a desk robot that cannot answer that is not
        # a desk robot. The server's clock is the authoritative one: it is
        # network-synchronised, and the robot's own RTC exists to survive a
        # reboot rather than to be asked.
        now = datetime.now().astimezone()

        facts: dict[str, Any] = {
            "date_today": now.strftime("%A, %-d %B %Y"),
            "time_now": now.strftime("%-I:%M %p").lower(),
            # The robot withholds every sun reading until it knows where it
            # is, so an absent elevation here means "not located" and the hour
            # answers on its own.
            "part_of_day": _part_of_day(
                now.hour, number("sun_elevation"), flag("daylight")
            ),
            # The LTR-553 sits behind the front glass and triggers at roughly
            # arm's length, so this is "someone leaned in", not "someone is in
            # the room". Reported as presence it made Andy tell a person
            # sitting a metre away that he was by himself, which is worse than
            # saying nothing: the name has to carry the sensor's real reach.
            "someone_close_to_me": flag("presence"),
            "room_light": (
                None
                if ambient is None
                else "dark"
                if ambient < 15
                else "dim"
                if ambient < 80
                else "bright"
            ),
            "being_touched": flag("head_touched"),
            "last_touch_gesture": text("head_gesture"),
            "where_on_the_head": _touched_zones(
                text("head_touch_left"),
                text("head_touch_centre"),
                text("head_touch_right"),
            ),
            "recently_shaken": flag("shake_detected"),
            "screen_touched": flag("screen_touched"),
            "listening": voice not in {"muted", "server disconnected"},
            "speaking": voice == "announcing",
            "emotion": emotion,
            "moving": flag("motion_active"),
            "motion_blocked": flag("motion_inhibited"),
            "camera_available": self.has_camera(),
            "camera_in_use": flag("camera_in_use"),
        }

        outside = flag("daylight")
        if outside is not None:
            facts["daylight_outside"] = outside
        sunrise = text("next_sunrise")
        sunset = text("next_sunset")
        if sunrise and sunset:
            facts["sun_next"] = f"rises {sunrise}, sets {sunset}"
        where = text("where_andy_is")
        if where:
            facts["where_andy_is"] = where

        # What it is like outside, which the robot reads for itself from its own
        # position. Only present once it has an answer, so an absent reading
        # means "not known yet" rather than "fine".
        weather = text("weather_summary")
        if weather:
            facts["weather_outside"] = weather

        awake = number("uptime")
        if awake is not None:
            facts["awake_for"] = _spoken_duration(awake)

        # Where the head is actually pointing, in words rather than in steps.
        # `motion.yaml` calibrates home at 466, left at 381 and right at 552.
        yaw = number("motion_yaw_position")
        pitch = number("motion_pitch_position")
        if yaw is not None:
            side = (
                "straight ahead"
                if abs(yaw - 466) <= 20
                else "to its left"
                if yaw < 466
                else "to its right"
            )
            tilt = (
                ""
                if pitch is None or abs(pitch - 620) <= 20
                else ", tilted up"
                if pitch > 620
                else ", tilted down"
            )
            facts["head_pointing"] = f"{side}{tilt}"

        warmth = number("pmic_temperature")
        if warmth is not None:
            facts["how_warm_andy_is"] = (
                f"{int(warmth)} degrees, "
                + ("comfortable" if warmth < 55 else "hot" if warmth > 70 else "warm")
            )

        signal = number("wi-fi_signal")
        if signal is not None:
            facts["wifi"] = (
                "strong" if signal > -60 else "usable" if signal > -75 else "weak"
            )

        tunnel = flag("wireguard_status")
        if tunnel is not None:
            facts["connected_through_the_tunnel"] = tunnel

        restart = text("reset_reason")
        if restart:
            facts["why_andy_last_restarted"] = restart

        return {key: value for key, value in facts.items() if value is not None}

    def diagnostics(self) -> dict[str, Any]:
        """How Andy's own hardware is doing, for when someone asks.

        Kept out of `interpreted()` on purpose. Those facts describe the
        situation and are worth putting in front of the model on every single
        turn; these describe the machine, and a model given forty numbers every
        turn reads none of them. Someone asking "are you all right?" gets them,
        and nobody else pays for them.
        """
        states = self._states

        def flag(object_id: str) -> bool | None:
            value = states.get(object_id)
            return value if isinstance(value, bool) else None

        def number(object_id: str) -> float | None:
            value = states.get(object_id)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None
            return round(float(value), 2)

        def text(object_id: str) -> str | None:
            value = states.get(object_id)
            return value if isinstance(value, str) and value else None

        report: dict[str, Any] = {}

        yaw_temperature = number("motion_yaw_temperature")
        pitch_temperature = number("motion_pitch_temperature")
        temperatures = [
            value
            for value in (yaw_temperature, pitch_temperature)
            if value is not None
        ]
        if temperatures:
            hottest = max(temperatures)
            report["neck_motors"] = (
                f"{int(hottest)} degrees, "
                + ("fine" if hottest < 45 else "warm" if hottest < 60 else "too hot")
            )

        power = number("body_power")
        if power is not None:
            report["drawing_power"] = f"{power:.2f} watts"
        voltage = number("battery_voltage")
        if voltage is not None:
            report["battery_voltage"] = f"{voltage / 1000:.2f} volts"

        faults = number("motion_faults")
        errors = number("voice_errors")
        if faults is not None and errors is not None:
            report["anything_gone_wrong"] = (
                "no"
                if faults == 0 and errors == 0
                else f"{int(faults)} movement faults, {int(errors)} voice errors"
            )
        misses = [
            number("motion_yaw_feedback_misses"),
            number("motion_pitch_feedback_misses"),
        ]
        if all(value is not None for value in misses):
            report["servo_feedback_misses"] = int(sum(misses))  # type: ignore[arg-type]

        heap = number("heap_free")
        if heap is not None:
            report["free_memory"] = f"{int(heap / 1024)} kilobytes"
        loop = number("main_loop_time")
        if loop is not None:
            report["busiest_loop"] = f"{int(loop)} milliseconds"

        # Which way up Andy is. Gravity sits on one axis when he is upright on
        # a desk, so this answers "have I been tipped over" without the model
        # ever seeing three accelerations.
        vertical = number("acceleration_y")
        if vertical is not None:
            report["upright"] = vertical > 0.7

        outside = number("outside_temperature")
        if outside is not None:
            report["outside_temperature"] = f"{int(outside)} degrees"
        feels = number("outside_feels_like")
        if feels is not None:
            report["outside_feels_like"] = f"{int(feels)} degrees"
        damp = number("outside_humidity")
        if damp is not None:
            report["outside_humidity"] = f"{int(damp)} percent"

        card = flag("sd_card_present")
        if card is not None:
            report["memory_card_inserted"] = card
        address = text("wireguard_address")
        if address:
            report["tunnel_address"] = address
        handshake = number("wireguard_latest_handshake")
        if handshake:
            report["tunnel_last_agreed"] = _spoken_duration(
                max(0.0, datetime.now().timestamp() - handshake)
            ) + " ago"

        # Infrared is deliberately absent: the robot has a transmitter, the
        # server has no path to it, and reporting a capability nothing can use
        # is how a model comes to offer it.
        programs = self._motion_programs()
        if programs:
            report["movement_programs_on_the_robot"] = len(programs)
        return report

    def _motion_programs(self) -> tuple[str, ...]:
        """The named programs the firmware itself offers, read from the select."""
        select = self._selects.get("motion_program_name")
        options = getattr(select, "options", ()) if select is not None else ()
        return tuple(str(option) for option in options)
