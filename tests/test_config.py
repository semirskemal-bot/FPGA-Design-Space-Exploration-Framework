from __future__ import annotations

from pathlib import Path

import pytest

from fpga_dse.config import ConfigError, load_config


BASE = """version: 1
project:
  name: unit-study
  workspace: out
parameters:
  WIDTH:
    values: [8, 16]
  DEPTH:
    range: {start: 2, stop: 6, step: 2}
parameter_constraints:
  - WIDTH * DEPTH <= 96
search:
  strategy: grid
  max_designs: 100
execution:
  adapter: mock
  jobs: 2
  fingerprint_files: [rtl/top.sv, scripts/*.py]
  mock_metrics:
    area: WIDTH * DEPTH
    speed: 300 - WIDTH
metric_constraints:
  - speed >= 250
objectives:
  - {metric: speed, goal: maximize, weight: 2}
  - {metric: area, goal: minimize, weight: 1}
"""


def write_config(tmp_path: Path, text: str = BASE) -> Path:
    path = tmp_path / "dse.yml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_and_expands_config(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path))
    assert config.name == "unit-study"
    assert config.workspace == (tmp_path / "out").resolve()
    assert config.parameter_names == ("WIDTH", "DEPTH")
    assert config.parameters[1].values == (2, 4, 6)
    assert config.execution.jobs == 2
    assert config.execution.fingerprint_files == ("rtl/top.sv", "scripts/*.py")
    assert config.objectives[0].weight == 2.0


def test_float_range_can_be_exclusive(tmp_path: Path) -> None:
    text = BASE.replace(
        "range: {start: 2, stop: 6, step: 2}",
        "range: {start: 0.0, stop: 1.0, step: 0.25, inclusive: false}",
    )
    config = load_config(write_config(tmp_path, text))
    assert config.parameters[1].values == (0.0, 0.25, 0.5, 0.75)


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        (("version: 1", "version: 9"), "unsupported"),
        (("values: [8, 16]", "values: []"), "non-empty"),
        (("strategy: grid", "strategy: random"), "samples"),
        (("adapter: mock", "adapter: shell"), "command"),
        (("WIDTH * DEPTH <= 96", "UNKNOWN > 0"), "unknown names"),
        (("weight: 2", "weight: 0"), "positive"),
    ],
)
def test_rejects_invalid_config(
    tmp_path: Path,
    replacement: tuple[str, str],
    message: str,
) -> None:
    old, new = replacement
    with pytest.raises(ConfigError, match=message):
        load_config(write_config(tmp_path, BASE.replace(old, new)))


def test_shell_command_list_is_parsed(tmp_path: Path) -> None:
    text = BASE.replace(
        "adapter: mock\n  jobs: 2\n  fingerprint_files: [rtl/top.sv, scripts/*.py]\n  mock_metrics:\n    area: WIDTH * DEPTH\n    speed: 300 - WIDTH",
        "adapter: shell\n  jobs: 2\n  fingerprint_files: [rtl/top.sv, scripts/*.py]\n  command: [python, worker.py]",
    )
    config = load_config(write_config(tmp_path, text))
    assert config.execution.command == ("python", "worker.py")


def test_rejects_non_mapping_root_and_bad_yaml(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="root"):
        load_config(write_config(tmp_path, "- not\n- a\n- mapping\n"))
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(write_config(tmp_path, "version: [\n"))


def test_rejects_bad_fingerprint_file_list(tmp_path: Path) -> None:
    text = BASE.replace(
        "fingerprint_files: [rtl/top.sv, scripts/*.py]",
        "fingerprint_files: [rtl/top.sv, rtl/top.sv]",
    )
    with pytest.raises(ConfigError, match="duplicate"):
        load_config(write_config(tmp_path, text))


def test_rejects_unknown_and_duplicate_fields(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unknown field"):
        load_config(write_config(tmp_path, BASE.replace("version: 1", "version: 1\nverison: 1")))

    duplicate = BASE.replace("  name: unit-study", "  name: unit-study\n  name: duplicate")
    with pytest.raises(ConfigError, match="duplicate key"):
        load_config(write_config(tmp_path, duplicate))
