PYTHON?=python3
PYTEST=$(PYTHON) -m pytest

.PHONY: tests unit e2e

# Run unit/integration tests (skip playwright) with coverage
# Generates terminal coverage report and .coverage data file
	tests:
		$(PYTEST) -m "not playwright" --cov=main --cov-report=term-missing --cov-fail-under=99

# Explicit targets if needed
unit:
	$(PYTEST) -m "not playwright" --cov=main --cov-report=term-missing --cov-fail-under=99

e2e:
	$(PYTEST) -m playwright tests_e2e --no-cov
