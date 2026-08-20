from __future__ import annotations

import asyncio
import logging
import os
import socket
from typing import Any

from uvicorn.protocols.http.httptools_impl import HttpToolsProtocol


log = logging.getLogger("andy.http")

# The robot reaches the media server over the same tunnel address the server
# dials it on, so one setting identifies it in both directions. A literal here
# would silently disable the tuning below on any other deployment.
ROBOT_WIREGUARD_ADDRESS = os.environ.get("ANDY_DEVICE_HOST", "10.0.0.2").strip()

# Linux socket option numbers from linux/tcp.h and asm-generic/socket.h. Python
# does not expose them on every build supported by this project.
TCP_NOTSENT_LOWAT = 25
SO_MAX_PACING_RATE = 47

WIREGUARD_SEND_BUFFER_BYTES = 4 * 1024
WIREGUARD_NOTSENT_LOWAT_BYTES = 1024
WIREGUARD_PACING_BYTES_PER_SECOND = 64 * 1024
WIREGUARD_WRITE_BUFFER_LOW_BYTES = 512
WIREGUARD_WRITE_BUFFER_HIGH_BYTES = 1024


def tune_wireguard_transport(
    transport: asyncio.Transport,
    client: tuple[str, int] | None,
) -> bool:
    """Bound queued TCP data for robot-facing media connections.

    The ESP32 WireGuard path has a long RTT and a small effective receive
    budget. Keeping only a few kilobytes below asyncio prevents Linux from
    releasing a large congestion-window flight after the first ACK.
    """
    if client is None or client[0] != ROBOT_WIREGUARD_ADDRESS:
        return False

    raw_socket: Any = transport.get_extra_info("socket")
    if raw_socket is None:
        raise RuntimeError("robot HTTP connection has no TCP socket")

    raw_socket.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_SNDBUF,
        WIREGUARD_SEND_BUFFER_BYTES,
    )
    raw_socket.setsockopt(
        socket.IPPROTO_TCP,
        TCP_NOTSENT_LOWAT,
        WIREGUARD_NOTSENT_LOWAT_BYTES,
    )
    raw_socket.setsockopt(
        socket.SOL_SOCKET,
        SO_MAX_PACING_RATE,
        WIREGUARD_PACING_BYTES_PER_SECOND,
    )
    transport.set_write_buffer_limits(
        high=WIREGUARD_WRITE_BUFFER_HIGH_BYTES,
        low=WIREGUARD_WRITE_BUFFER_LOW_BYTES,
    )
    return True


class WireGuardHTTPProtocol(HttpToolsProtocol):
    def connection_made(  # type: ignore[override]
        self,
        transport: asyncio.Transport,
    ) -> None:
        super().connection_made(transport)
        try:
            if tune_wireguard_transport(transport, self.client):
                log.info("bounded robot media TCP transport enabled")
        except OSError:
            log.exception("failed to configure robot media TCP transport")
            transport.close()

