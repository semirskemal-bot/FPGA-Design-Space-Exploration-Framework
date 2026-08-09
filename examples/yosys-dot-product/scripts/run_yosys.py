#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Synthesize the dot-product example with Yosys")
    parser.add_argument("--source", required=True)
    parser.add_argument("--top", default="dot_product")
    parser.add_argument("--data-width", required=True, type=int)
    parser.add_argument("--lanes", required=True, type=int)
    parser.add_argument("--pipeline", required=True, type=int)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    yosys = shutil.which("yosys")
    if yosys is None:
        print("yosys executable was not found on PATH", file=sys.stderr)
        return 127

    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    stats_path = output.parent / "yosys-stat.json"
    script_path = output.parent / "synthesize.ys"

    script = "\n".join(
        [
            f'read_verilog -sv "{_yosys_path(source)}"',
            f"chparam -set DATA_WIDTH {args.data_width} {args.top}",
            f"chparam -set LANES {args.lanes} {args.top}",
            f"chparam -set PIPELINE {args.pipeline} {args.top}",
            f"hierarchy -check -top {args.top}",
            f"synth -top {args.top}",
            f'tee -q -o "{_yosys_path(stats_path)}" stat -json -top {args.top}',
            "check",
            "",
        ]
    )
    script_path.write_text(script, encoding="utf-8")

    completed = subprocess.run(
        [yosys, "-q", "-s", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    (output.parent / "yosys.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (output.parent / "yosys.stderr.log").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        print(completed.stderr or completed.stdout, file=sys.stderr)
        return completed.returncode

    try:
        statistics = json.loads(stats_path.read_text(encoding="utf-8"))
        module = _find_module(statistics, args.top)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"failed to parse Yosys statistics: {exc}", file=sys.stderr)
        return 2

    cells_by_type = module.get("num_cells_by_type", {})
    if not isinstance(cells_by_type, dict):
        cells_by_type = {}
    normalized = {str(name): int(count) for name, count in cells_by_type.items()}
    register_cells = sum(count for name, count in normalized.items() if "DFF" in name.upper())
    multiplier_cells = sum(count for name, count in normalized.items() if "MUL" in name.upper())
    adder_cells = sum(count for name, count in normalized.items() if "ADD" in name.upper())

    payload: dict[str, Any] = {
        "metrics": {
            "cells": int(module.get("num_cells", sum(normalized.values()))),
            "wire_bits": int(module.get("num_wire_bits", 0)),
            "register_cells": register_cells,
            "multiplier_cells": multiplier_cells,
            "adder_cells": adder_cells,
            "operations_per_cycle": args.lanes,
            "latency_cycles": max(1, args.pipeline),
        },
        "metadata": {
            "tool": "yosys",
            "creator": statistics.get("creator", "unknown"),
            "top": args.top,
            "cell_types": normalized,
        },
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


def _find_module(statistics: dict[str, Any], top: str) -> dict[str, Any]:
    modules = statistics.get("modules")
    if not isinstance(modules, dict) or not modules:
        raise ValueError("statistics contain no modules")
    for key in (top, f"\\{top}"):
        value = modules.get(key)
        if isinstance(value, dict):
            return value
    for name, value in modules.items():
        if str(name).lstrip("\\") == top and isinstance(value, dict):
            return value
    if len(modules) == 1:
        only = next(iter(modules.values()))
        if isinstance(only, dict):
            return only
    raise KeyError(f"top module {top!r} was not found")


def _yosys_path(path: Path) -> str:
    return path.as_posix().replace('"', '\\"')


if __name__ == "__main__":
    raise SystemExit(main())
