from __future__ import annotations

import csv
import json
from pathlib import Path

from fpga_dse.analysis import analyze_records
from fpga_dse.config import load_config
from fpga_dse.models import RunRecord
from fpga_dse.reporting import write_reports


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "dse.yml"
    path.write_text(
        """version: 1
project: {name: analysis-test, workspace: .dse}
parameters:
  WIDTH: {values: [8, 16, 32]}
parameter_constraints: []
execution:
  adapter: mock
  mock_metrics: {area: WIDTH, speed: 1000 / WIDTH}
metric_constraints:
  - power <= 5
objectives:
  - {metric: speed, goal: maximize, weight: 2}
  - {metric: area, goal: minimize, weight: 1}
""",
        encoding="utf-8",
    )
    return path


def _record(identifier: str, width: int, area: int, speed: int, power: int) -> RunRecord:
    return RunRecord(
        design_id=identifier,
        project="analysis-test",
        status="success",
        parameters={"WIDTH": width},
        metrics={"area": area, "speed": speed, "power": power},
        duration_seconds=0.1,
    )


def test_pareto_feasibility_scores_and_reports(tmp_path: Path) -> None:
    config = load_config(_config(tmp_path))
    records = [
        _record("a", 8, 10, 100, 4),
        _record("b", 16, 20, 120, 3),
        _record("c", 32, 30, 80, 2),
        _record("d", 64, 5, 200, 9),
    ]
    result = analyze_records(config, records)
    assert len(result.feasible_designs) == 3
    assert {item.record.design_id for item in result.pareto_designs} == {"a", "b"}
    assert result.recommended is not None
    assert result.recommended.record.design_id == "b"
    infeasible = next(item for item in result.designs if item.record.design_id == "d")
    assert infeasible.violations == ("power <= 5",)

    paths = write_reports(result, tmp_path / "reports", top=3)
    assert all(path.is_file() for path in paths.values())
    payload = json.loads(paths["json"].read_text())
    assert payload["summary"]["pareto_designs"] == 2
    assert "Objective map" in paths["html"].read_text()
    with paths["csv"].open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 4
    assert "param.WIDTH" in rows[0]


def test_missing_objective_metric_is_infeasible(tmp_path: Path) -> None:
    config = load_config(_config(tmp_path))
    record = RunRecord(
        design_id="missing",
        project="analysis-test",
        status="success",
        parameters={"WIDTH": 8},
        metrics={"area": 10, "power": 2},
    )
    result = analyze_records(config, [record])
    assert result.recommended is None
    assert result.designs[0].violations == ("missing objective metric: speed",)
