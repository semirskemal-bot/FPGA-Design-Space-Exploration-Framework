# Repository Guidance

- Python package code lives in `src/fpga_dse` and supports Python 3.11+.
- Keep the core vendor-neutral; synthesis tools communicate through `result.json`.
- Never replace the restricted expression evaluator with unrestricted `eval`.
- Preserve stable design IDs: canonical parameter JSON hashed with SHA-256 and truncated to 12 characters.
- Run `ruff check .`, `mypy src`, and `pytest` before committing.
- Add tests and documentation for every configuration or result-schema change.
- Do not commit generated `.dse` workspaces, vendor databases, bitstreams, or licensed tool output.
