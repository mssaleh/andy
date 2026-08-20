"""Turning device state changes into events worth acting on.

Andy now reports presence, touch, shake, screen taps, battery and infrared. Left
raw these are noise: proximity flickers, a counter ticks, a hand brushes the
head. This module decides which changes are events, debounces them, and routes
each to one of three destinations.

Routing is a fixed server-side policy, never the model's choice:

  * dropped     — below threshold, debounced, or uninteresting;
  * rule        — a deterministic response with no model call at all;
  * agent       — a structured prompt, which may still answer "ignore".

Without this, a robot that can see and feel will interrupt constantly. The
cheapest correct answer to most events is silence.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
import logging
import time as _time
from typing import Any

from .device import DeviceState, StateValue

log = logging.getLogger("andy.bus")


class EventKind(StrEnum):
    PRESENCE_ARRIVED = "presence_arrived"
    PRESENCE_LEFT = "presence_left"
    HEAD_TOUCHED = "head_touched"
    HEAD_GESTURE = "head_gesture"
    SHAKEN = "shaken"
    SCREEN_TAPPED = "screen_tapped"
    BATTERY_LOW = "battery_low"
    CHARGER_CONNECTED = "charger_connected"
    CHARGER_REMOVED = "charger_removed"
    MOTION_FAULTED = "motion_faulted"
    MUTED = "muted"
    UNMUTED = "unmuted"


class Route(StrEnum):
    DROP = "drop"
    RULE = "rule"
    AGENT = "agent"


@dataclass(frozen=True, slots=True)
class DeviceEvent:
    kind: EventKind
    value: Any = None
    at: float = field(default_factory=_time.monotonic)


#: How long the same event must wait before it counts again. Presence is slow on
#: purpose: someone leaning in and out of range should read as one arrival.
DEBOUNCE_SECONDS: dict[EventKind, float] = {
    EventKind.PRESENCE_ARRIVED: 60.0,
    EventKind.PRESENCE_LEFT: 60.0,
    EventKind.HEAD_TOUCHED: 8.0,
    EventKind.HEAD_GESTURE: 8.0,
    EventKind.SHAKEN: 15.0,
    EventKind.SCREEN_TAPPED: 3.0,
    EventKind.BATTERY_LOW: 900.0,
    EventKind.CHARGER_CONNECTED: 30.0,
    EventKind.CHARGER_REMOVED: 30.0,
    EventKind.MOTION_FAULTED: 30.0,
    EventKind.MUTED: 5.0,
    EventKind.UNMUTED: 5.0,
}

#: Where each event goes. Anything the firmware already answers for itself is a
#: rule or a drop: the robot has already blinked, glowed and moved by the time
#: the server hears about it.
ROUTES: dict[EventKind, Route] = {
    EventKind.PRESENCE_ARRIVED: Route.AGENT,
    EventKind.PRESENCE_LEFT: Route.DROP,
    EventKind.HEAD_TOUCHED: Route.DROP,
    EventKind.HEAD_GESTURE: Route.AGENT,
    EventKind.SHAKEN: Route.AGENT,
    EventKind.SCREEN_TAPPED: Route.DROP,
    EventKind.BATTERY_LOW: Route.RULE,
    EventKind.CHARGER_CONNECTED: Route.DROP,
    EventKind.CHARGER_REMOVED: Route.DROP,
    EventKind.MOTION_FAULTED: Route.RULE,
    EventKind.MUTED: Route.DROP,
    EventKind.UNMUTED: Route.DROP,
}

Handler = Callable[[DeviceEvent], Awaitable[None]]


class EventBus:
    """Derives events from state changes, debounces them, and routes them."""

    def __init__(
        self,
        device: DeviceState,
        *,
        battery_floor: int = 20,
        clock: Callable[[], float] = _time.monotonic,
    ) -> None:
        self._device = device
        self._battery_floor = battery_floor
        self._clock = clock
        self._last_seen: dict[EventKind, float] = {}
        self._handlers: dict[Route, Handler] = {}
        self._counts: dict[str, int] = {}
        self._queue: asyncio.Queue[DeviceEvent] = asyncio.Queue(maxsize=64)
        self._task: asyncio.Task[None] | None = None
        self._previous: dict[str, StateValue] = {}

    def on(self, route: Route, handler: Handler) -> None:
        self._handlers[route] = handler

    def start(self) -> None:
        self._device.subscribe(self._observe)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._drain(), name="andy-event-bus")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # -- derivation --------------------------------------------------------

    def _observe(self, object_id: str, value: StateValue) -> None:
        previous = self._previous.get(object_id)
        self._previous[object_id] = value
        kind: EventKind | None = None

        if object_id == "presence" and isinstance(value, bool):
            kind = EventKind.PRESENCE_ARRIVED if value else EventKind.PRESENCE_LEFT
        elif object_id == "head_touched" and value is True:
            kind = EventKind.HEAD_TOUCHED
        elif object_id == "head_gesture" and isinstance(value, str):
            if value.startswith("swipe"):
                kind = EventKind.HEAD_GESTURE
        elif object_id == "shake_detected" and value is True:
            kind = EventKind.SHAKEN
        elif object_id == "screen_touched" and value is True:
            kind = EventKind.SCREEN_TAPPED
        elif object_id == "battery_level" and isinstance(value, (int, float)):
            if value < self._battery_floor:
                kind = EventKind.BATTERY_LOW
        elif object_id == "battery_charging" and isinstance(value, bool):
            kind = (
                EventKind.CHARGER_CONNECTED if value else EventKind.CHARGER_REMOVED
            )
        elif object_id == "motion_faults" and isinstance(value, (int, float)):
            if previous is not None and value > previous:
                kind = EventKind.MOTION_FAULTED
        elif object_id == "voice_state" and isinstance(value, str):
            if value == "muted":
                kind = EventKind.MUTED
            elif previous == "muted":
                kind = EventKind.UNMUTED

        if kind is None:
            return
        self._emit(DeviceEvent(kind=kind, value=value, at=self._clock()))

    def _emit(self, event: DeviceEvent) -> None:
        window = DEBOUNCE_SECONDS.get(event.kind, 5.0)
        last = self._last_seen.get(event.kind)
        if last is not None and event.at - last < window:
            self._bump("debounced")
            return
        self._last_seen[event.kind] = event.at
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._bump("overflowed")
            log.warning("event queue full, dropped %s", event.kind)

    # -- dispatch ----------------------------------------------------------

    async def _drain(self) -> None:
        while True:
            event = await self._queue.get()
            route = ROUTES.get(event.kind, Route.DROP)
            self._bump(route.value)
            if route is Route.DROP:
                log.debug("dropped %s", event.kind)
                continue
            handler = self._handlers.get(route)
            if handler is None:
                continue
            try:
                await handler(event)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("event handler failed for %s", event.kind)

    def _bump(self, name: str) -> None:
        self._counts[name] = self._counts.get(name, 0) + 1

    def snapshot(self) -> dict[str, object]:
        return {
            "routes": {kind.value: route.value for kind, route in ROUTES.items()},
            "counts": dict(sorted(self._counts.items())),
            "queued": self._queue.qsize(),
            "running": self._task is not None and not self._task.done(),
        }
