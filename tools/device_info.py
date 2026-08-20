from __future__ import annotations

import argparse
import ast
import asyncio
import string
from pathlib import Path

from aioesphomeapi import (
    APIClient,
    BinarySensorInfo,
    BinarySensorState,
    SensorInfo,
    SensorState,
    TextSensorInfo,
    TextSensorState,
)


def _normalize_mac(value: str) -> str:
    normalized = value.translate(str.maketrans("", "", ":-.")).lower()
    if len(normalized) != 12 or any(
        character not in string.hexdigits for character in normalized
    ):
        raise ValueError(f"invalid MAC address: {value!r}")
    return normalized


def _load_secrets(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("!include "):
        included = text.removeprefix("!include ").strip()
        return _load_secrets((path.parent / included).resolve())

    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        value = raw_value.strip()
        if value[:1] in {'"', "'"}:
            parsed_value = ast.literal_eval(value)
            if not isinstance(parsed_value, str):
                raise ValueError(f"secret {key.strip()!r} must be a string")
            value = parsed_value
        values[key.strip()] = value
    return values


def _state_value(state: object) -> bool | float | str | None:
    if isinstance(state, BinarySensorState):
        return None if state.missing_state else state.state
    if isinstance(state, SensorState):
        return None if state.missing_state else state.state
    if isinstance(state, TextSensorState):
        return None if state.missing_state else state.state
    return None


async def _inspect(args: argparse.Namespace) -> None:
    secrets = _load_secrets(args.secrets)
    client = APIClient(
        args.host,
        args.port,
        None,
        client_info="andy-firmware-deploy/0.5.0",
        noise_psk=secrets["api_encryption_key"],
        expected_mac=_normalize_mac(args.expected_mac),
    )
    try:
        await client.connect(login=True)
        info = await client.device_info()
        if info.name != args.expected_name:
            raise RuntimeError(
                f"expected device name {args.expected_name!r}, got {info.name!r}"
            )
        if info.project_name != args.expected_project:
            raise RuntimeError(
                "expected ESPHome project "
                f"{args.expected_project!r}, got {info.project_name!r}"
            )
        print(f"name={info.name}")
        print(f"friendly_name={info.friendly_name}")
        print(f"mac={info.mac_address}")
        print(f"esphome={info.esphome_version}")
        print(f"project={info.project_name}")
        print(f"project_version={info.project_version}")
        if args.state or args.list_entities:
            entities, _ = await client.list_entities_services()
            if args.list_entities:
                for entity in sorted(entities, key=lambda item: item.object_id):
                    print(
                        f"entity={type(entity).__name__}:{entity.object_id}"
                    )
            requested = set(args.state)
            state_entities = {
                (entity.key, entity.device_id): entity
                for entity in entities
                if isinstance(
                    entity,
                    (BinarySensorInfo, SensorInfo, TextSensorInfo),
                )
                and entity.object_id in requested
            }
            latest: dict[str, bool | float | str] = {}

            def on_state(state: object) -> None:
                entity = state_entities.get(
                    (getattr(state, "key", None), getattr(state, "device_id", None))
                )
                value = _state_value(state)
                if entity is not None and value is not None:
                    latest[entity.object_id] = value

            client.subscribe_states(on_state)
            await asyncio.sleep(args.state_timeout)
            for object_id in args.state:
                print(f"state_{object_id}={latest.get(object_id, 'unavailable')}")
    finally:
        await client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=6053)
    parser.add_argument("--expected-mac", required=True)
    parser.add_argument("--expected-name", required=True)
    parser.add_argument("--expected-project", required=True)
    parser.add_argument("--state", action="append", default=[])
    parser.add_argument("--state-timeout", type=float, default=1.0)
    parser.add_argument("--list-entities", action="store_true")
    parser.add_argument(
        "--secrets",
        type=Path,
        default=Path("firmware/secrets.yaml"),
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65_535:
        parser.error("--port must be between 1 and 65535")
    if args.state_timeout <= 0:
        parser.error("--state-timeout must be positive")
    asyncio.run(_inspect(args))


if __name__ == "__main__":
    main()
