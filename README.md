# FPGA Design-Space Exploration Framework

A reproducible Python framework for sweeping RTL and tool parameters, launching synthesis experiments in parallel, resuming interrupted studies, filtering infeasible implementations, and identifying Pareto-optimal FPGA designs.

The framework is useful before hardware is available: the deterministic mock adapter exercises the complete workflow without an FPGA board or vendor license. The shell adapter connects the same workflow to Yosys, Vivado, Quartus, or any script that can emit one small JSON result file.

## What it does

- Defines integer, float, boolean, and string parameters in YAML.
- Supports inclusive numeric ranges, explicit value lists, and safe arithmetic constraints.
- Runs exhaustive grid searches or deterministic random samples.
- Executes independent designs concurrently with per-run timeouts.
- Stores parameters, command lines, logs, metrics, errors, and timestamps for every design.
- Resumes successful designs only when both parameters and execution/source fingerprints match.
- Applies post-synthesis timing, area, power, or application constraints.
- Computes the multi-objective Pareto frontier.
- Produces a normalized weighted recommendation without hiding raw tradeoffs.
- Exports machine-readable JSON/CSV and human-readable Markdown/HTML reports.
- Includes a no-tool mock FIR study and a real Yosys/SystemVerilog dot-product study.

## Quick start

Python 3.11 or newer is required.

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate

pip install -e .
fpga-dse init my-study
fpga-dse validate my-study/dse.yml
fpga-dse plan my-study/dse.yml
fpga-dse run my-study/dse.yml
```

Open `my-study/.dse/reports/report.html`. The generated starter uses the deterministic mock backend and therefore runs on a normal laptop.

You can also run the checked-in example directly:

```bash
fpga-dse run examples/mock-fir/dse.yml
```

## Real synthesis with Yosys

Install Yosys and make sure the `yosys` executable is on `PATH`, then run:

```bash
fpga-dse doctor examples/yosys-dot-product/dse.yml
fpga-dse run examples/yosys-dot-product/dse.yml
```

The example changes `DATA_WIDTH`, `LANES`, and `PIPELINE`, synthesizes every legal SystemVerilog configuration, parses Yosys statistics, and trades off cell count against operations per cycle and latency.

## Configuration at a glance

```yaml
version: 1
project:
  name: fir-study
  workspace: .dse

parameters:
  DATA_WIDTH:
    values: [8, 12, 16]
  TAPS:
    range: {start: 4, stop: 16, step: 4}
  PIPELINED:
    values: [false, true]

parameter_constraints:
  - DATA_WIDTH * TAPS <= 256

search:
  strategy: grid
  max_designs: 1000

execution:
  adapter: shell
  jobs: 4
  timeout_seconds: 1800
  fingerprint_files:
    - rtl/**/*.sv
    - scripts/**/*.py
  command:
    - "{{ python_executable }}"
    - "{{ project_root }}/scripts/synthesize.py"
    - "--width"
    - "{{ DATA_WIDTH }}"
    - "--output"
    - "{{ run_dir }}/result.json"

metric_constraints:
  - fmax_mhz >= 200
  - lut <= 5000

objectives:
  - {metric: fmax_mhz, goal: maximize, weight: 0.5}
  - {metric: lut, goal: minimize, weight: 0.3}
  - {metric: power_w, goal: minimize, weight: 0.2}
```

Shell commands receive both Jinja variables and environment variables. For example, `{{ DATA_WIDTH }}` and `DSE_PARAM_DATA_WIDTH` contain the same parameter value. See [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) for the complete schema.

## Result contract

A synthesis wrapper only needs to create the configured `result_file` in its run directory:

```json
{
  "metrics": {
    "fmax_mhz": 247.3,
    "lut": 1820,
    "ff": 940,
    "dsp": 8,
    "power_w": 1.72
  },
  "metadata": {
    "part": "xc7a100tcsg324-1",
    "tool": "vivado"
  }
}
```

Metric values must be finite numbers. Metadata can contain any JSON-compatible diagnostic information.

## Commands

```text
fpga-dse init [DIRECTORY]       Create a runnable mock study
fpga-dse validate CONFIG        Validate YAML and print study dimensions
fpga-dse plan CONFIG            Preview stable design IDs and parameters
fpga-dse run CONFIG             Execute, resume, analyze, and report
fpga-dse status CONFIG          Summarize the workspace
fpga-dse analyze CONFIG         Rebuild reports without rerunning synthesis
fpga-dse doctor CONFIG          Check the configuration and external executable
```

Run `fpga-dse COMMAND --help` for overrides such as random sampling, worker count, workspace, and design limit.

## Workspace layout

```text
.dse/
├── study.json
├── results.jsonl
├── runs/
│   └── 5f0b6d4c8f34/
│       ├── parameters.json
│       ├── run.json
│       ├── command.txt
│       ├── stdout.log
│       ├── stderr.log
│       └── result.json
└── reports/
    ├── report.csv
    ├── report.html
    ├── report.json
    └── report.md
```

Every `run.json` is written atomically. A failed or timed-out design remains inspectable and is rerun on the next invocation. Successful designs are reused only when their execution fingerprint still matches; changing a configured HDL or wrapper file automatically invalidates stale cached results. `--no-resume` forces every design to run again.

## Design principles

The orchestration layer is vendor-neutral. Vendor tools stay behind small wrapper scripts, while the framework owns reproducibility, concurrency, persistence, analysis, and reporting. Constraints are evaluated with a restricted expression interpreter rather than unrestricted Python `eval`.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/CLI.md`](docs/CLI.md), and [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md).

## Development

```bash
pip install -e ".[dev]"
ruff check .
mypy src
pytest --cov=fpga_dse --cov-report=term-missing
```

The GitHub Actions workflow runs the same checks on Python 3.11 and 3.12.

## License

MIT
