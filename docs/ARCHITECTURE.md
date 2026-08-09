# Architecture

## Data flow

```text
YAML configuration
      │
      ▼
config validation ──► restricted expression validation
      │
      ▼
search strategy ──► stable candidate IDs
      │
      ▼
parallel runner ──► run directories, logs, atomic run manifests
      │
      ▼
result.json ingestion ──► results.jsonl
      │
      ▼
metric constraints ──► feasible set
      │
      ├──► Pareto dominance
      └──► normalized weighted score
               │
               ▼
      JSON / CSV / Markdown / HTML
```

## Modules

- `config.py` parses YAML into immutable dataclasses and rejects ambiguous settings.
- `expressions.py` evaluates a small arithmetic and boolean language without Python builtins.
- `space.py` produces grid or deterministic random candidates and hashes canonical parameters.
- `runner.py` executes mock formulas or shell commands, captures logs, enforces timeouts, and resumes successes.
- `workspace.py` owns the on-disk schema and atomic JSON writes.
- `analysis.py` applies implementation constraints, computes nondominated designs, and scores feasible designs.
- `reporting.py` exports machine-readable tables and a dependency-free HTML report.
- `cli.py` composes these modules into a stable command-line interface.

## Stable IDs and resumption

A design ID is the first 12 hexadecimal characters of SHA-256 over canonical, key-sorted JSON parameters. A separate full-length study fingerprint covers the execution command, relevant execution settings, mock formulas, and every file selected by `execution.fingerprint_files`. A cached run is reused only when both identities match. This keeps run directories readable while preventing changed RTL or build wrappers from silently reusing stale metrics. The complete parameters and study fingerprint remain in every run manifest.

## Failure model

Each design is isolated in its own directory. A command failure, malformed result, timeout, or missing metric does not erase other experiments. Failed and timed-out records are not analyzed and are retried by the next run. Unexpected worker exceptions are converted into failed records at the executor boundary.

## Analysis model

Only successful records enter analysis. Metric constraints define feasibility. A design is Pareto optimal when no feasible design is at least as good in every objective and strictly better in at least one. Weighted scores use min-max normalized desirability on the current feasible set; they are a convenience recommendation, not a substitute for inspecting the Pareto frontier.

## Trust boundary

Parameter and metric expressions are restricted. Shell commands are not sandboxed because invoking FPGA tools is the purpose of the adapter. A study configuration must therefore be treated as executable code.
