# Mock FIR study

This study exercises the complete framework without an FPGA toolchain. Deterministic formulas model the expected direction of area, timing, power, and latency changes as data width, tap count, coefficient mode, and pipeline depth change.

```bash
fpga-dse validate dse.yml
fpga-dse plan dse.yml
fpga-dse run dse.yml
```

The formulas are educational surrogates, not hardware estimates. Replace the mock adapter with a synthesis wrapper before treating metrics as implementation data.
