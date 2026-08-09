# Contributing

## Local setup

```bash
python -m venv .venv
# Activate the virtual environment for your platform.
pip install -e ".[dev]"
```

Before opening a pull request, run:

```bash
ruff check .
mypy src
pytest --cov=fpga_dse --cov-report=term-missing
```

## Scope

Keep the orchestration core vendor-neutral. Tool-specific behavior should live in wrapper scripts or focused parser modules and must include a fixture-based test. New configuration fields require validation, documentation, and backward-compatible defaults when possible.

## Commits and pull requests

Use focused commits and describe the observable behavior, tests, and any configuration migration. Do not commit generated `.dse` workspaces or proprietary FPGA reports.
