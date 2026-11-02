INSTALL_DIR ?= $(HOME)/.claude/hooks/pii

.PHONY: test install desktop-bundle

test:
	python3 tests/test_pii.py
	python3 tests/test_desktop.py

install: test
	install -m 664 plugin/scripts/pii.py $(INSTALL_DIR)/
	install -m 775 plugin/scripts/hook.py plugin/scripts/cli.py $(INSTALL_DIR)/
	rm -f $(INSTALL_DIR)/test_pii.py

desktop-bundle:
	python3 desktop/build.py
