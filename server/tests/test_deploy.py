from __future__ import annotations

import importlib.util
from pathlib import Path
import stat
from types import ModuleType

import pytest


def _load_renderer() -> ModuleType:
    path = Path(__file__).parents[1] / "deploy" / "render_environment.py"
    spec = importlib.util.spec_from_file_location("render_environment", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


renderer = _load_renderer()
template_path = (
    Path(__file__).parents[1] / "deploy" / "production.env.example"
)


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_renderer_combines_current_contract_without_exposing_or_losing_values(
    tmp_path: Path,
) -> None:
    operator = _write(
        tmp_path / "operator.env",
        "ANDY_LLM_API_KEY=model==key\n"
        "ANDY_SYSTEM_PROMPT=Answer with context=a=b.\n",
    )
    included = _write(
        tmp_path / "firmware-values.yaml",
        'api_encryption_key: "device==key"\n',
    )
    firmware = _write(
        tmp_path / "secrets.yaml",
        f"!include {included.name}\n",
    )
    output = tmp_path / "production.env"

    renderer.render_environment(
        template_path=template_path,
        operator_path=operator,
        firmware_secrets_path=firmware,
        output_path=output,
    )

    values = renderer.read_environment(output)
    assert tuple(values) == renderer.EXPECTED_KEYS
    assert values["ANDY_DEVICE_KEY"] == "device==key"
    assert values["ANDY_LLM_API_KEY"] == "model==key"
    assert values["ANDY_SYSTEM_PROMPT"] == "Answer with context=a=b."
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("operator_text", "error"),
    [
        (
            "ANDY_LLM_API_KEY=model-key\nUNSUPPORTED=value\n",
            "unsupported keys: UNSUPPORTED",
        ),
        (
            "ANDY_LLM_API_KEY=first\nANDY_LLM_API_KEY=second\n",
            "duplicate environment key ANDY_LLM_API_KEY",
        ),
        (
            "ANDY_LLM_API_KEY=model-key\nANDY_DEVICE_KEY=wrong-source\n",
            "ANDY_DEVICE_KEY must come from firmware/secrets.yaml",
        ),
    ],
)
def test_renderer_rejects_ambiguous_operator_environment(
    tmp_path: Path, operator_text: str, error: str
) -> None:
    operator = _write(tmp_path / "operator.env", operator_text)
    firmware = _write(
        tmp_path / "secrets.yaml",
        "api_encryption_key: device-key\n",
    )

    with pytest.raises(ValueError, match=error):
        renderer.render_environment(
            template_path=template_path,
            operator_path=operator,
            firmware_secrets_path=firmware,
            output_path=tmp_path / "production.env",
        )


@pytest.mark.parametrize(
    ("firmware_text", "error"),
    [
        ("wifi_ssid: network\n", "empty keys: ANDY_DEVICE_KEY"),
        (
            "api_encryption_key: CHANGE_ME\n",
            "placeholder keys: ANDY_DEVICE_KEY",
        ),
    ],
)
def test_renderer_requires_a_real_firmware_api_key(
    tmp_path: Path, firmware_text: str, error: str
) -> None:
    operator = _write(
        tmp_path / "operator.env",
        "ANDY_LLM_API_KEY=model-key\n",
    )
    firmware = _write(tmp_path / "secrets.yaml", firmware_text)

    with pytest.raises(ValueError, match=error):
        renderer.render_environment(
            template_path=template_path,
            operator_path=operator,
            firmware_secrets_path=firmware,
            output_path=tmp_path / "production.env",
        )


def test_renderer_requires_the_exact_template_contract(tmp_path: Path) -> None:
    shortened_template = _write(
        tmp_path / "template.env",
        template_path.read_text(encoding="utf-8").replace(
            "ANDY_LLM_REASONING=none\n", ""
        ),
    )
    operator = _write(
        tmp_path / "operator.env",
        "ANDY_LLM_API_KEY=model-key\n",
    )
    firmware = _write(
        tmp_path / "secrets.yaml",
        "api_encryption_key: device-key\n",
    )

    with pytest.raises(ValueError, match="keys or order"):
        renderer.render_environment(
            template_path=shortened_template,
            operator_path=operator,
            firmware_secrets_path=firmware,
            output_path=tmp_path / "production.env",
        )
