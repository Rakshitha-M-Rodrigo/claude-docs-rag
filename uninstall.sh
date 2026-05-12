#!/usr/bin/env bash
# uninstall.sh — remove claude-docs-rag MCP registration, venv, and skill.
# The persisted index at ~/.claude-docs-rag is preserved unless --purge is passed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PURGE_INDEX=0
for arg in "$@"; do
  case "$arg" in
    --purge) PURGE_INDEX=1 ;;
    *) echo "Unknown arg: $arg"; exit 2 ;;
  esac
done

echo "==> Removing MCP registration (user scope)"
claude mcp remove docs-rag -s user 2>/dev/null || echo "    (was not registered)"

echo "==> Removing skill"
rm -rf "$HOME/.claude/skills/docs-search"

echo "==> Removing local .venv"
rm -rf .venv

if [[ $PURGE_INDEX == 1 ]]; then
  DOCS_RAG_DIR="${DOCS_RAG_DIR:-$HOME/.claude-docs-rag}"
  echo "==> Purging index at $DOCS_RAG_DIR"
  rm -rf "$DOCS_RAG_DIR"
else
  echo "    (index at ~/.claude-docs-rag preserved; pass --purge to delete)"
fi

echo "✓ Uninstalled."
