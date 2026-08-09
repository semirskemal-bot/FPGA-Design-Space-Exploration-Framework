# CLI reference

## `init`

Creates `dse.yml`, `README.md`, and `.gitignore` for a deterministic mock study.

```bash
fpga-dse init studies/fir
fpga-dse init studies/fir --force
```

## `validate`

Parses the configuration, validates all static expression references, and prints the raw Cartesian size.

```bash
fpga-dse validate studies/fir/dse.yml
```

## `plan`

Generates feasible design IDs without executing synthesis.

```bash
fpga-dse plan dse.yml --preview 20
fpga-dse plan dse.yml --strategy random --samples 100 --seed 9
fpga-dse plan dse.yml --output plan.json
```

`--limit` is useful for smoke testing. It never bypasses `search.max_designs`.

## `run`

Plans, executes, persists, analyzes, and reports in one command.

```bash
fpga-dse run dse.yml
fpga-dse run dse.yml --jobs 8 --limit 10
fpga-dse run dse.yml --no-resume
fpga-dse run dse.yml --workspace scratch/study-01
```

A nonzero exit code indicates that at least one requested design failed or timed out. Reports still include every successful design.

## `status`

Reads manifests only; it does not run or analyze anything.

```bash
fpga-dse status dse.yml
```

## `analyze`

Recomputes feasibility, Pareto membership, scores, and all report formats from existing records. Use this after changing metric constraints, objective weights, or report row limits.

```bash
fpga-dse analyze dse.yml
fpga-dse analyze dse.yml --output exported-report --top 50
```

## `doctor`

Checks the configuration and verifies the first executable for command-list shell adapters.

```bash
fpga-dse doctor dse.yml
```

This is a preflight check, not proof that a licensed vendor flow will complete.
