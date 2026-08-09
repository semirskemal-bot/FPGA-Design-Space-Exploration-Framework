# Tool integration guide

The framework intentionally uses a small integration contract: the configured command exits with code zero and writes `result.json` into the run directory.

## Wrapper responsibilities

1. Read parameters from command-line arguments, `DSE_PARAMETERS_FILE`, or `DSE_PARAM_*` variables.
2. Create an isolated tool project under `DSE_RUN_DIR`.
3. Run synthesis, implementation, timing, and power steps as required.
4. Parse authoritative reports.
5. Write finite numeric metrics and optional metadata to `result.json`.
6. Exit nonzero when the tool fails or required reports are missing.

The framework handles parallelism, timeouts, source-aware resumption, logs, constraints, Pareto analysis, and reporting. List every result-affecting HDL, constraint, Tcl, and wrapper input under `execution.fingerprint_files` so source changes invalidate cached runs.

## Yosys

The checked-in example uses `tee -q -o stats.json stat -json` after generic synthesis, then converts module statistics to the result contract. Add nextpnr for device-specific placement, routing, utilization, and timing.

## Vivado

A typical batch wrapper creates a Tcl script that:

- reads RTL and constraints,
- sets generics or Verilog defines,
- calls `synth_design`, `opt_design`, `place_design`, and `route_design`,
- writes utilization, timing summary, and power reports,
- exits nonzero when implementation fails.

Parse stable report fields in the wrapper and emit metrics such as `lut`, `ff`, `bram`, `dsp`, `wns_ns`, `fmax_mhz`, and `power_w`. Keep the raw reports in the run directory for auditability.

## Quartus

A batch wrapper can generate a per-run QSF project, set HDL parameters, invoke `quartus_sh --flow compile`, parse the fitter and timing analyzer outputs, and write the same result schema. Preserve family, device, seed, and tool version in metadata.

## Reproducibility metadata

Recommended metadata fields include tool name/version, FPGA part, synthesis strategy, implementation seed, git commit, hostname or runner image, and source hash. Metadata is not used for ranking, but it makes results auditable.
