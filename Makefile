.PHONY: install lint type test check demo clean

install:
	python -m pip install -e ".[dev]"

lint:
	ruff check .

type:
	mypy src

test:
	pytest --cov=fpga_dse --cov-report=term-missing

check: lint type test

demo:
	fpga-dse run examples/mock-fir/dse.yml

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov dist build
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
