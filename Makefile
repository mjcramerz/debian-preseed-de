PYTHON ?= python3

.PHONY: build check test audit validate
build:
	$(PYTHON) -B tools/build.py
check:
	$(PYTHON) -B tools/build.py --check
test:
	$(PYTHON) -B -m unittest discover -s d-i/forky/tests -p "test_*.py"
audit:
	$(PYTHON) -B d-i/forky/tests/audit_codebase.py --output validation/audit.json
validate:
	$(PYTHON) -B tools/validate.py
