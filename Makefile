PYTHON ?= python3
.DEFAULT_GOAL := build

.PHONY: build inventory check test test-bootstrap test-debconf test-cuda audit validate themes test-isolation

# Check before unittest discovery, including newly added test modules.
test-isolation:
	$(PYTHON) -I -B tools/isolation.py

check test test-bootstrap test-debconf test-cuda audit validate: test-isolation
build:
	$(PYTHON) -B tools/build.py
inventory:
	$(PYTHON) -I -B tools/inventory.py
check:
	$(PYTHON) -B tools/check_build.py
	$(PYTHON) -B tools/check_shells.py
test:
	$(PYTHON) -B -m unittest discover -s d-i/forky/tests -p "test_*.py"
test-bootstrap:
	$(PYTHON) -B -m unittest discover -s d-i/forky/tests -p "test_bootstrap_portability.py" -v
test-debconf:
	$(PYTHON) -B -m unittest discover -s d-i/forky/tests -p "test_debconf_protocol.py" -v
test-cuda:
	$(PYTHON) -B -m unittest discover -s d-i/forky/tests -p "test_cuda_legacy_apt.py" -v
audit:
	$(PYTHON) -B d-i/forky/tests/audit_codebase.py --output .build/validation/audit.json
validate:
	$(PYTHON) -B tools/validate.py

themes:
	$(PYTHON) -I -B tools/themes.py
