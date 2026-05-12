SHELL := /bin/bash

.PHONY: install uninstall reinstall verify preload preload-append clean help eval eval-intent eval-retrieval

help:
	@echo "Targets:"
	@echo "  make install         Run install.sh (venv + deps + MCP register + skill)"
	@echo "  make uninstall       Remove MCP registration, venv, and skill"
	@echo "  make reinstall       uninstall + install (preserves index)"
	@echo "  make verify          Re-run MCP health check"
	@echo "  make preload         Ingest every docset in scripts/docsets.yaml (rebuilds)"
	@echo "  make preload-append  Same, but append to existing docset chunks"
	@echo "  make eval            Run intent + retrieval evals (auto-preloads missing docsets)"
	@echo "  make eval-intent     Run only the intent eval"
	@echo "  make eval-retrieval  Run only the retrieval eval"
	@echo "  make clean           Remove .venv and build artefacts (keeps MCP registration)"

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

preload:
	./.venv/bin/python scripts/preload.py

preload-append:
	./.venv/bin/python scripts/preload.py --append

eval:
	./.venv/bin/python -m evals.runners.run_all

eval-intent:
	./.venv/bin/python -m evals.runners.run_intent

eval-retrieval:
	./.venv/bin/python -m evals.runners.run_retrieval

clean:
	rm -rf .venv src/claude_docs_rag.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	find . -name '*.pyc' -delete
