from __future__ import annotations

from pathlib import Path

import pytest

from fpga_dse.config import load_config
from fpga_dse.fingerprint import FingerprintError, compute_study_fingerprint, fingerprinted_files


def _write_config(tmp_path: Path, pattern: str = "rtl/**/*.sv") -> Path:
    config = tmp_path / "dse.yml"
    config.write_text(
        f"""version: 1
project: {{name: fingerprint-test, workspace: .dse}}
parameters:
  WIDTH: {{values: [8]}}
parameter_constraints: []
execution:
  adapter: mock
  fingerprint_files: ["{pattern}"]
  mock_metrics:
    area: WIDTH * 2
objectives:
  - {{metric: area, goal: minimize}}
""",
        encoding="utf-8",
    )
    return config


def test_fingerprint_changes_when_source_changes(tmp_path: Path) -> None:
    source = tmp_path / "rtl" / "top.sv"
    source.parent.mkdir()
    source.write_text("module top; endmodule\n", encoding="utf-8")
    config = load_config(_write_config(tmp_path))

    first = compute_study_fingerprint(config)
    source.write_text("module top; wire changed; endmodule\n", encoding="utf-8")
    second = compute_study_fingerprint(config)

    assert first != second
    assert fingerprinted_files(config) == (source.resolve(),)


def test_fingerprint_rejects_missing_or_escaping_inputs(tmp_path: Path) -> None:
    with pytest.raises(FingerprintError, match="did not match"):
        compute_study_fingerprint(load_config(_write_config(tmp_path, "missing/*.sv")))

    config_path = _write_config(tmp_path, "../outside.sv")
    with pytest.raises(FingerprintError, match="project-relative"):
        compute_study_fingerprint(load_config(config_path))
