from __future__ import annotations

from pathlib import Path

from fpga_dse.cli import main
from fpga_dse.scaffold import create_scaffold


def test_scaffold_and_cli_smoke(tmp_path: Path) -> None:
    study = tmp_path / "study"
    files = create_scaffold(study)
    assert (study / "dse.yml") in files
    assert main(["validate", str(study / "dse.yml")]) == 0
    assert main(["plan", str(study / "dse.yml"), "--limit", "3"]) == 0
    assert main(["run", str(study / "dse.yml"), "--limit", "3", "--jobs", "2"]) == 0
    assert (study / ".dse" / "reports" / "report.html").is_file()
    assert main(["status", str(study / "dse.yml")]) == 0
    assert main(["analyze", str(study / "dse.yml")]) == 0


def test_cli_returns_error_for_missing_config(tmp_path: Path) -> None:
    assert main(["validate", str(tmp_path / "missing.yml")]) == 2


def test_init_doctor_and_scaffold_conflict(tmp_path: Path) -> None:
    study = tmp_path / "created-by-cli"
    assert main(["init", str(study)]) == 0
    assert main(["doctor", str(study / "dse.yml")]) == 0
    assert main(["init", str(study)]) == 2
    assert main(["init", str(study), "--force"]) == 0
