from __future__ import annotations

import argparse
import ast
import os
from pathlib import Path
import re


EXPECTED_KEYS = (
    "ANDY_DEVICE_ENABLED",
    "ANDY_DEVICE_HOST",
    "ANDY_DEVICE_PORT",
    "ANDY_DEVICE_NAME",
    "ANDY_DEVICE_PROJECT",
    "ANDY_DEVICE_MAC",
    "ANDY_DEVICE_KEY",
    "ANDY_MOTION_ACTIONS_ENABLED",
    "ANDY_MEDIA_BASE_URL",
    "ANDY_ASR_URL",
    "ANDY_ASR_API",
    "ANDY_ASR_MODEL",
    "ANDY_ASR_LANGUAGE",
    "ANDY_TTS_URL",
    "ANDY_TTS_VOICE",
    "ANDY_LLM_API",
    "ANDY_LLM_URL",
    "ANDY_LLM_MODEL",
    "ANDY_LLM_API_KEY",
    "ANDY_LLM_REASONING",
    "ANDY_SYSTEM_PROMPT",
    "ANDY_AGENT_ENABLED",
    "ANDY_VISION_ENABLED",
    "ANDY_VLM_URL",
    "ANDY_VLM_MODEL",
    "ANDY_OWL_URL",
    "ANDY_MCP_SERVERS",
    "ANDY_VAD_ENGINE",
    "ANDY_VAD_SPEECH_THRESHOLD",
    "ANDY_VAD_MIN_SPEECH_RMS",
    "ANDY_VAD_NOISE_RATIO",
    "ANDY_SESSION_IDLE_SECONDS",
    "ANDY_STATE_DIR",
)

#: Keys that must be present but may legitimately carry no value. A list of MCP
#: servers is usually none, and the recogniser only names a model when it is
#: one that serves several; demanding a placeholder would be a lie.
OPTIONAL_KEYS = frozenset(
    {
        "ANDY_MCP_SERVERS",
        "ANDY_ASR_MODEL",
        "ANDY_OWL_URL",
    }
)
_KEY_PATTERN = re.compile(r"[A-Z][A-Z0-9_]*")
_PLACEHOLDERS = {"CHANGE_ME"}


def read_environment(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.removesuffix("\r")
        if not line or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}: line {line_number} is not KEY=value")
        key, value = line.split("=", 1)
        if _KEY_PATTERN.fullmatch(key) is None:
            raise ValueError(f"{path}: line {line_number} has an invalid key")
        if key in values:
            raise ValueError(f"{path}: duplicate environment key {key}")
        values[key] = value
    return values


def read_firmware_secrets(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    if stripped.startswith("!include ") and "\n" not in stripped:
        included = stripped.removeprefix("!include ").strip()
        return read_firmware_secrets((path.parent / included).resolve())

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"{path}: line {line_number} is not key: value")
        key, raw_value = line.split(":", 1)
        key = key.strip()
        if not key or key in values:
            raise ValueError(f"{path}: duplicate or invalid secret key {key!r}")
        value = raw_value.strip()
        if value[:1] in {'"', "'"}:
            try:
                parsed = ast.literal_eval(value)
            except (SyntaxError, ValueError) as exc:
                raise ValueError(
                    f"{path}: line {line_number} has an invalid quoted value"
                ) from exc
            if not isinstance(parsed, str):
                raise ValueError(f"{path}: secret {key} must be a string")
            value = parsed
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


def render_environment(
    *,
    template_path: Path,
    operator_path: Path,
    firmware_secrets_path: Path,
    output_path: Path,
) -> None:
    template = read_environment(template_path)
    if tuple(template) != EXPECTED_KEYS:
        raise ValueError(
            "production environment template keys or order do not match "
            "the current contract"
        )

    operator = read_environment(operator_path)
    unknown = sorted(set(operator) - set(EXPECTED_KEYS))
    if unknown:
        raise ValueError(
            "operator environment contains unsupported keys: " + ", ".join(unknown)
        )
    if "ANDY_DEVICE_KEY" in operator:
        raise ValueError(
            "ANDY_DEVICE_KEY must come from firmware/secrets.yaml"
        )

    firmware_secrets = read_firmware_secrets(firmware_secrets_path)
    device_key = firmware_secrets.get("api_encryption_key", "")
    values = {**template, **operator, "ANDY_DEVICE_KEY": device_key}

    missing = [
        key
        for key in EXPECTED_KEYS
        if key not in OPTIONAL_KEYS and not values[key].strip()
    ]
    if missing:
        raise ValueError(
            "rendered production environment has empty keys: " + ", ".join(missing)
        )
    placeholders = [
        key
        for key in EXPECTED_KEYS
        if key not in OPTIONAL_KEYS and values[key].strip().upper() in _PLACEHOLDERS
    ]
    if placeholders:
        raise ValueError(
            "rendered production environment has placeholder keys: "
            + ", ".join(placeholders)
        )

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(output_path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            for key in EXPECTED_KEYS:
                output.write(f"{key}={values[key]}\n")
    except BaseException:
        output_path.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render Andy's production environment without printing secrets."
    )
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--operator-env", type=Path, required=True)
    parser.add_argument("--firmware-secrets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        render_environment(
            template_path=args.template,
            operator_path=args.operator_env,
            firmware_secrets_path=args.firmware_secrets,
            output_path=args.output,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
