PYTHON ?= python3

.PHONY: build check test test-bootstrap audit validate
build:
	$(PYTHON) -B tools/build.py
check:
	$(PYTHON) -B tools/build.py --check
	$(PYTHON) -B tools/check_shells.py
test:
	$(PYTHON) -B -m unittest discover -s d-i/forky/tests -p "test_*.py"
test-bootstrap:
	$(PYTHON) -B -m unittest discover -s d-i/forky/tests -p "test_bootstrap_portability.py" -v
audit:
	$(PYTHON) -B d-i/forky/tests/audit_codebase.py --output validation/audit.json
validate:
	$(PYTHON) -B tools/validate.py
