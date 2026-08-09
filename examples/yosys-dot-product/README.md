# Yosys dot-product study

This example performs real synthesis of a parameterized SystemVerilog dot-product datapath. It explores:

- operand `DATA_WIDTH`,
- parallel multiply `LANES`, and
- output `PIPELINE` depth.

The wrapper writes a Yosys script into each run directory, invokes Yosys, converts `stat -json` output into the framework result contract, and preserves both Yosys logs.

## Run

```bash
fpga-dse doctor dse.yml
fpga-dse plan dse.yml
fpga-dse run dse.yml
```

Yosys must be installed and available as `yosys` on `PATH`. This example uses generic synthesis statistics, not placement-and-routing timing. A production study should add nextpnr or a vendor implementation flow and report achieved clock frequency and power.
