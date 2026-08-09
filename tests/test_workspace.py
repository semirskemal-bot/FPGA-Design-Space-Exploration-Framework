from __future__ import annotations

from pathlib import Path

import pytest

from fpga_dse.models import RunRecord
from fpga_dse.workspace import Workspace, WorkspaceError


def test_workspace_roundtrip_and_corruption(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "work")
    workspace.initialize(
        project="p",
        config_path=tmp_path / "dse.yml",
        study_fingerprint="a" * 64,
    )
    record = RunRecord(
        design_id="abc",
        project="p",
        status="success",
        parameters={"WIDTH": 8},
        metrics={"area": 10},
    )
    workspace.write_record(record)
    assert workspace.read_record("abc") == record
    assert workspace.read_record("missing") is None

    workspace.record_path("abc").write_text("{broken", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="cannot read"):
        workspace.read_record("abc")
    with pytest.raises(WorkspaceError, match="invalid run record"):
        workspace.all_records()
