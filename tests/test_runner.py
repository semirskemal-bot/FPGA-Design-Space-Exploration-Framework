from __future__ import annotations

import sys
from pathlib import Path

from fpga_dse.config import load_config
from fpga_dse.runner import run_study
from fpga_dse.space import materialize_candidates
from fpga_dse.workspace import Workspace


def _write_mock_config(tmp_path: Path) -> Path:
    path = tmp_path / "mock.yml"
    path.write_text(
        """version: 1
project: {name: runner-test, workspace: .dse}
parameters:
  WIDTH: {values: [8, 16]}
  PIPE: {values: [0, 1]}
parameter_constraints: []
search: {strategy: grid, max_designs: 20}
execution:
  adapter: mock
  jobs: 2
  mock_metrics:
    area: WIDTH * 10 + PIPE * 3
    fmax: 200 + PIPE * 50 - WIDTH
metric_constraints: []
objectives:
  - {metric: fmax, goal: maximize}
  - {metric: area, goal: minimize}
""",
        encoding="utf-8",
    )
    return path


def test_mock_runner_persists_and_resumes(tmp_path: Path) -> None:
    config = load_config(_write_mock_config(tmp_path))
    candidates = materialize_candidates(
        config.parameters,
        config.parameter_constraints,
        strategy="grid",
        max_designs=config.search.max_designs,
    )
    workspace = Workspace(config.workspace)
    records = run_study(config, candidates, workspace, jobs=2)
    assert len(records) == 4
    assert all(record.status == "success" for record in records)
    assert workspace.record_path(records[0].design_id).is_file()
    assert len((workspace.root / "results.jsonl").read_text().splitlines()) == 4

    original_started = {record.design_id: record.started_at for record in records}
    resumed = run_study(config, candidates, workspace, jobs=2, resume=True)
    assert {record.design_id: record.started_at for record in resumed} == original_started


def test_shell_runner_renders_command_and_reads_result(tmp_path: Path) -> None:
    worker = tmp_path / "worker.py"
    worker.write_text(
        """import json, sys
width = int(sys.argv[1])
output = sys.argv[2]
with open(output, 'w', encoding='utf-8') as handle:
    json.dump({'metrics': {'area': width * 2, 'fmax': 400 - width}, 'metadata': {'worker': True}}, handle)
""",
        encoding="utf-8",
    )
    config_path = tmp_path / "shell.yml"
    config_path.write_text(
        f"""version: 1
project: {{name: shell-test, workspace: .dse-shell}}
parameters:
  WIDTH: {{values: [8]}}
parameter_constraints: []
search: {{strategy: grid, max_designs: 10}}
execution:
  adapter: shell
  command:
    - "{{{{ python_executable }}}}"
    - "{worker.as_posix()}"
    - "{{{{ WIDTH }}}}"
    - "{{{{ run_dir }}}}/result.json"
metric_constraints: []
objectives:
  - {{metric: fmax, goal: maximize}}
  - {{metric: area, goal: minimize}}
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    candidates = materialize_candidates(
        config.parameters,
        (),
        strategy="grid",
        max_designs=10,
    )
    workspace = Workspace(config.workspace)
    record = run_study(config, candidates, workspace)[0]
    assert record.status == "success"
    assert record.metrics == {"area": 16, "fmax": 392}
    assert record.metadata["worker"] is True
    assert Path(workspace.run_dir(record.design_id), "command.txt").is_file()


def test_shell_failure_is_recorded(tmp_path: Path) -> None:
    config_path = tmp_path / "failure.yml"
    config_path.write_text(
        f"""version: 1
project: {{name: fail-test, workspace: .dse-fail}}
parameters:
  WIDTH: {{values: [8]}}
parameter_constraints: []
execution:
  adapter: shell
  command: ["{sys.executable}", "-c", "import sys; print('bad', file=sys.stderr); sys.exit(7)"]
objectives:
  - {{metric: area, goal: minimize}}
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    candidates = materialize_candidates(config.parameters, (), strategy="grid", max_designs=10)
    record = run_study(config, candidates, Workspace(config.workspace))[0]
    assert record.status == "failed"
    assert record.error is not None and "code 7" in record.error


def test_shell_timeout_is_recorded(tmp_path: Path) -> None:
    config_path = tmp_path / "timeout.yml"
    config_path.write_text(
        f"""version: 1
project: {{name: timeout-test, workspace: .dse-timeout}}
parameters:
  WIDTH: {{values: [8]}}
parameter_constraints: []
execution:
  adapter: shell
  timeout_seconds: 0.01
  command: ["{sys.executable}", "-c", "import time; time.sleep(1)"]
objectives:
  - {{metric: area, goal: minimize}}
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    candidates = materialize_candidates(config.parameters, (), strategy="grid", max_designs=10)
    workspace = Workspace(config.workspace)
    record = run_study(config, candidates, workspace)[0]
    assert record.status == "timeout"
    assert record.error is not None and "exceeded" in record.error
    assert (workspace.run_dir(record.design_id) / "stdout.log").is_file()


def test_source_fingerprint_invalidates_resume(tmp_path: Path) -> None:
    worker = tmp_path / "fingerprinted_worker.py"
    worker.write_text(
        """import json, os
width = int(os.environ['DSE_PARAM_WIDTH'])
with open(os.path.join(os.environ['DSE_RUN_DIR'], 'result.json'), 'w', encoding='utf-8') as handle:
    json.dump({'metrics': {'area': width * 2}}, handle)
""",
        encoding="utf-8",
    )
    config_path = tmp_path / "fingerprinted.yml"
    config_path.write_text(
        f"""version: 1
project: {{name: source-fingerprint, workspace: .dse-fingerprint}}
parameters:
  WIDTH: {{values: [8]}}
execution:
  adapter: shell
  fingerprint_files: [fingerprinted_worker.py]
  command: ["{sys.executable}", "{worker.as_posix()}"]
objectives:
  - {{metric: area, goal: minimize}}
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    candidates = materialize_candidates(config.parameters, (), strategy="grid", max_designs=10)
    workspace = Workspace(config.workspace)

    first = run_study(config, candidates, workspace)[0]
    resumed = run_study(config, candidates, workspace, resume=True)[0]
    assert resumed.started_at == first.started_at
    assert resumed.study_fingerprint == first.study_fingerprint

    worker.write_text(
        worker.read_text(encoding="utf-8").replace("width * 2", "width * 3"),
        encoding="utf-8",
    )
    refreshed = run_study(config, candidates, workspace, resume=True)[0]
    assert refreshed.metrics["area"] == 24
    assert refreshed.study_fingerprint != first.study_fingerprint
    assert refreshed.started_at != first.started_at
