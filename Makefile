SHELL := /bin/bash

.PHONY: install uninstall reinstall verify clean help

help:
	@echo "Targets:"
	@echo "  make install     Run install.sh (venv + deps + MCP register + skill)"
	@echo "  make uninstall   Remove MCP registration, venv, and skill"
	@echo "  make reinstall   uninstall + install (preserves index)"
	@echo "  make verify      Re-run MCP health check"
	@echo "  make clean       Remove .venv and build artefacts (keeps MCP registration)"

install:
	./install.sh

uninstall:
	./uninstall.sh

reinstall: uninstall install

verify:
	@claude mcp get docs-rag 2>&1 | grep -E "Status|docs-rag:" || true
	@claude mcp get docs-rag 2>&1 | grep -q "Connected" \
		&& echo "✓ docs-rag MCP is Connected" \
		|| (echo "✗ docs-rag MCP is NOT connected" && exit 1)

clean:
	rm -rf .venv src/claude_docs_rag.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	find . -name '*.pyc' -delete
