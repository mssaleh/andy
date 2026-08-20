from __future__ import annotations

from pathlib import Path
import tomllib

from andy import __version__


def test_package_and_project_versions_match() -> None:
    pyproject = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert pyproject["project"]["version"] == __version__ == "0.5.0"
