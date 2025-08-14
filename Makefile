PYTHON?=python3
PYTEST=$(PYTHON) -m pytest

.PHONY: tests unit e2e
unit:
	$(PYTEST) -m "not playwright" --cov=endpoint_pulse --cov-report=term-missing --cov-report=html 

e2e:
	$(PYTEST) -m playwright tests_e2e --no-cov
