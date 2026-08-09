# Configuration reference

## Top-level fields

| Field | Required | Meaning |
|---|---:|---|
| `version` | yes | Schema version. Currently `1`. |
| `project` | yes | Study name and workspace. |
| `parameters` | yes | Ordered parameter definitions. |
| `parameter_constraints` | no | Boolean expressions evaluated before a run. |
| `search` | no | Grid/random strategy and safety limit. |
| `execution` | yes | Mock or shell backend. |
| `metric_constraints` | no | Boolean expressions evaluated after a successful run. |
| `objectives` | yes | Metrics to minimize or maximize. |

## Parameters

Explicit values preserve YAML type:

```yaml
parameters:
  WIDTH:
    values: [8, 16, 32]
  PIPELINED:
    values: [false, true]
  ARCHITECTURE:
    values: [serial, parallel]
```

Numeric ranges include the stop value by default:

```yaml
parameters:
  DEPTH:
    range:
      start: 16
      stop: 128
      step: 16
      inclusive: true
```

Parameter names must be valid identifiers because they are exposed directly to expressions and Jinja templates.

## Expressions

Supported syntax includes numeric and string constants, parameter or metric names, arithmetic, comparisons, `and`, `or`, `not`, and conditional expressions. Supported functions are `abs`, `min`, `max`, `round`, `int`, `float`, `bool`, `floor`, and `ceil`.

```yaml
parameter_constraints:
  - WIDTH * LANES <= 256
  - ARCHITECTURE != 'parallel' or LANES >= 2

metric_constraints:
  - wns_ns >= 0
  - lut <= 0.8 * device_lut_capacity
```

Attributes, indexing, imports, comprehensions, lambdas, dictionaries, sets, and arbitrary function calls are rejected.

## Search

```yaml
search:
  strategy: grid       # grid or random
  samples: 100         # required for random
  seed: 42
  max_designs: 10000   # hard guard unless intentionally raised
```

Random search is deterministic for a fixed parameter space, constraint set, sample count, and seed. It samples unique Cartesian-product indices rather than choosing each parameter independently, avoiding duplicate designs.

## Mock execution

```yaml
execution:
  adapter: mock
  jobs: 8
  mock_delay_ms: 5
  mock_metrics:
    lut: round(80 + WIDTH * LANES * 1.3)
    fmax_mhz: round(310 - WIDTH * 2 + PIPELINE * 45, 2)
```

Mock formulas may reference parameters and supported functions. They are deterministic and intended for testing workflows or demonstrating expected trends, not for predicting implementation results.

## Shell execution

```yaml
execution:
  adapter: shell
  jobs: 4
  timeout_seconds: 3600
  result_file: result.json
  fingerprint_files:
    - rtl/**/*.sv
    - scripts/**/*.py
  working_directory: "{{ run_dir }}"
  environment:
    FPGA_PART: xc7a100tcsg324-1
  command:
    - "{{ python_executable }}"
    - "{{ project_root }}/scripts/build.py"
    - "--width"
    - "{{ WIDTH }}"
    - "--output"
    - "{{ run_dir }}/result.json"
```

Command-list form is recommended because it avoids shell quoting. String commands require `shell: true` if shell features such as pipes or redirection are needed.

Available template values:

| Template | Value |
|---|---|
| `{{ params.WIDTH }}` / `{{ WIDTH }}` | Parameter value. |
| `{{ design_id }}` | Stable 12-character design ID. |
| `{{ project_root }}` | Directory containing the configuration. |
| `{{ workspace }}` | Absolute workspace path. |
| `{{ run_dir }}` | Absolute directory for this design. |
| `{{ python_executable }}` | Python interpreter running the CLI. |

Environment variables include `DSE_RUN_ID`, `DSE_RUN_DIR`, `DSE_PROJECT_ROOT`, `DSE_PARAMETERS_FILE`, and one `DSE_PARAM_<NAME>` variable per parameter.

### Source fingerprints and safe resumption

`execution.fingerprint_files` accepts project-relative file paths or glob patterns. Matching files are SHA-256 hashed and combined with the execution command and result-affecting settings. A successful run is resumed only when this study fingerprint still matches. Include all RTL, constraint, Tcl, Python, and other build inputs that can change synthesis results. Absolute paths and patterns containing `..` are rejected; `.git` and the configured workspace are excluded.

## Result file

Preferred form:

```json
{
  "metrics": {"lut": 1000, "fmax_mhz": 225.5},
  "metadata": {"part": "example", "tool_version": "example"}
}
```

A flat numeric object is accepted as shorthand, but cannot include metadata. Every metric must be a finite integer or float; booleans are rejected.

## Objectives

```yaml
objectives:
  - metric: fmax_mhz
    goal: maximize
    weight: 0.5
  - metric: lut
    goal: minimize
    weight: 0.3
  - metric: power_w
    goal: minimize
    weight: 0.2
```

Weights must be positive. Pareto membership does not depend on weights. Weights only produce the optional normalized recommendation.
