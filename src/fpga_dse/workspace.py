from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from fpga_dse.models import RunRecord


class WorkspaceError(RuntimeError):
    """Raised when workspace data is missing or corrupted."""


class Workspace:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.runs_dir = self.root / "runs"
        self.reports_dir = self.root / "reports"
        self.metadata_file = self.root / "study.json"

    def initialize(self, *, project: str, config_path: Path, study_fingerprint: str) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        write_json_atomic(
            self.metadata_file,
            {
                "schema_version": 2,
                "project": project,
                "config_path": str(config_path),
                "study_fingerprint": study_fingerprint,
            },
        )

    def run_dir(self, design_id: str) -> Path:
        return self.runs_dir / design_id

    def record_path(self, design_id: str) -> Path:
        return self.run_dir(design_id) / "run.json"

    def write_record(self, record: RunRecord) -> None:
        directory = self.run_dir(record.design_id)
        directory.mkdir(parents=True, exist_ok=True)
        write_json_atomic(directory / "parameters.json", record.parameters)
        write_json_atomic(directory / "run.json", record.to_dict())

    def read_record(self, design_id: str) -> RunRecord | None:
        path = self.record_path(design_id)
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkspaceError(f"cannot read run record {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise WorkspaceError(f"run record is not a JSON object: {path}")
        try:
            return RunRecord.from_dict(raw)
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkspaceError(f"invalid run record {path}: {exc}") from exc

    def all_records(self) -> list[RunRecord]:
        if not self.runs_dir.exists():
            return []
        records: list[RunRecord] = []
        for path in sorted(self.runs_dir.glob("*/run.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise TypeError("record root is not an object")
                records.append(RunRecord.from_dict(raw))
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise WorkspaceError(f"invalid run record {path}: {exc}") from exc
        return records

    def export_jsonl(self, records: Iterable[RunRecord] | None = None) -> Path:
        output = self.root / "results.jsonl"
        selected = list(records) if records is not None else self.all_records()
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8", newline="\n") as handle:
            for record in sorted(selected, key=lambda item: item.design_id):
                handle.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")
        return output


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)
