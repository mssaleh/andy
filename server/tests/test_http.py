from __future__ import annotations

import socket
from typing import Any

from andy.http import (
    ROBOT_WIREGUARD_ADDRESS,
    SO_MAX_PACING_RATE,
    TCP_NOTSENT_LOWAT,
    WIREGUARD_NOTSENT_LOWAT_BYTES,
    WIREGUARD_PACING_BYTES_PER_SECOND,
    WIREGUARD_SEND_BUFFER_BYTES,
    WIREGUARD_WRITE_BUFFER_HIGH_BYTES,
    WIREGUARD_WRITE_BUFFER_LOW_BYTES,
    tune_wireguard_transport,
)


class Socket:
    def __init__(self) -> None:
        self.options: list[tuple[int, int, int]] = []

    def setsockopt(self, level: int, option: int, value: int) -> None:
        self.options.append((level, option, value))


class Transport:
    def __init__(self) -> None:
        self.socket = Socket()
        self.limits: tuple[int | None, int | None] | None = None

    def get_extra_info(self, name: str) -> Any:
        return self.socket if name == "socket" else None

    def set_write_buffer_limits(
        self,
        high: int | None = None,
        low: int | None = None,
    ) -> None:
        self.limits = high, low


def test_robot_wireguard_connection_receives_bounded_socket_settings() -> None:
    transport = Transport()

    tuned = tune_wireguard_transport(  # type: ignore[arg-type]
        transport,
        (ROBOT_WIREGUARD_ADDRESS, 49152),
    )

    assert tuned is True
    assert transport.socket.options == [
        (socket.SOL_SOCKET, socket.SO_SNDBUF, WIREGUARD_SEND_BUFFER_BYTES),
        (
            socket.IPPROTO_TCP,
            TCP_NOTSENT_LOWAT,
            WIREGUARD_NOTSENT_LOWAT_BYTES,
        ),
        (
            socket.SOL_SOCKET,
            SO_MAX_PACING_RATE,
            WIREGUARD_PACING_BYTES_PER_SECOND,
        ),
    ]
    assert transport.limits == (
        WIREGUARD_WRITE_BUFFER_HIGH_BYTES,
        WIREGUARD_WRITE_BUFFER_LOW_BYTES,
    )


def test_non_robot_connection_is_not_modified() -> None:
    transport = Transport()

    tuned = tune_wireguard_transport(  # type: ignore[arg-type]
        transport,
        ("127.0.0.1", 49152),
    )

    assert tuned is False
    assert transport.socket.options == []
    assert transport.limits is None
