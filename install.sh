#!/usr/bin/env bash
# install.sh — one-shot setup for claude-docs-rag
#
# Idempotent: safe to re-run. Leaves the index at ~/.claude-docs-rag untouched.
#
# Usage:
#   ./install.sh                 # default: user-scope MCP + skill at ~/.claude/skills
#   ./install.sh --no-skill      # MCP only, skip skill copy
#   PYTHON=python3.11 ./install.sh
#   DOCS_RAG_DIR=/custom/path ./install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PY="${PYTHON:-python3}"
INSTALL_SKILL=1
for arg in "$@"; do
  case "$arg" in
    --no-skill) INSTALL_SKILL=0 ;;
    *) echo "Unknown arg: $arg"; exit 2 ;;
  esac
done

echo "==> claude-docs-rag installer"
echo "    repo:        $SCRIPT_DIR"
echo "    python:      $PY"
echo "    venv:        $SCRIPT_DIR/.venv"
echo "    index dir:   ${DOCS_RAG_DIR:-$HOME/.claude-docs-rag}"
echo "    skill copy:  $([[ $INSTALL_SKILL == 1 ]] && echo yes || echo no)"
echo

# --- 1. Preflight ------------------------------------------------------------
command -v "$PY" >/dev/null || { echo "ERROR: $PY not found on PATH"; exit 1; }
command -v claude >/dev/null || {
  echo "ERROR: 'claude' CLI not found. Install Claude Code first:"
  echo "       https://docs.anthropic.com/en/docs/claude-code/quickstart"
  exit 1
}

PY_VER="$("$PY" -c 'import sys; print(".".join(str(x) for x in sys.version_info[:2]))')"
echo "==> Python version: $PY_VER"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || {
  echo "ERROR: Python 3.9+ required (found $PY_VER)"; exit 1;
}

# --- 2. Venv + package install ----------------------------------------------
if [[ ! -d .venv ]]; then
  echo "==> Creating .venv"
  "$PY" -m venv .venv
else
  echo "==> Reusing existing .venv"
fi

echo "==> Upgrading pip"
.venv/bin/pip install --quiet --upgrade pip

echo "==> Installing claude-docs-rag (editable) + dependencies"
.venv/bin/pip install --quiet -e .

# --- 3. Pre-cache embedding model -------------------------------------------
DOCS_RAG_MODEL="${DOCS_RAG_MODEL:-all-MiniLM-L6-v2}"
echo "==> Pre-caching embedding model: $DOCS_RAG_MODEL"
.venv/bin/python - <<PY
from sentence_transformers import SentenceTransformer
SentenceTransformer("$DOCS_RAG_MODEL")
print("    cached.")
PY

# --- 4. Index dir ------------------------------------------------------------
DOCS_RAG_DIR="${DOCS_RAG_DIR:-$HOME/.claude-docs-rag}"
mkdir -p "$DOCS_RAG_DIR"

# --- 5. Register MCP (idempotent) -------------------------------------------
echo "==> Registering docs-rag MCP server (user scope)"
claude mcp remove docs-rag -s user >/dev/null 2>&1 || true
claude mcp add docs-rag \
  --scope user \
  -e "DOCS_RAG_DIR=$DOCS_RAG_DIR" \
  -e "DOCS_RAG_MODEL=$DOCS_RAG_MODEL" \
  -- "$SCRIPT_DIR/.venv/bin/python" -m docs_rag.server >/dev/null

# --- 6. Health check ---------------------------------------------------------
echo "==> Health-checking MCP server"
STATUS_OUT="$(claude mcp get docs-rag 2>&1 || true)"
if echo "$STATUS_OUT" | grep -q "Connected"; then
  echo "    ✓ docs-rag MCP connected"
else
  echo "    ✗ MCP failed to connect"
  echo "$STATUS_OUT"
  echo
  echo "Reproduce the failure manually with:"
  echo "  DOCS_RAG_DIR=$DOCS_RAG_DIR $SCRIPT_DIR/.venv/bin/python -m docs_rag.server"
  exit 1
fi

# --- 7. Install skill --------------------------------------------------------
if [[ $INSTALL_SKILL == 1 ]]; then
  USER_SKILLS_DIR="$HOME/.claude/skills"
  mkdir -p "$USER_SKILLS_DIR"
  echo "==> Installing docs-search skill at $USER_SKILLS_DIR/docs-search"
  rm -rf "$USER_SKILLS_DIR/docs-search"
  cp -r skills/docs-search "$USER_SKILLS_DIR/docs-search"
fi

echo
echo "✓ Setup complete."
echo
echo "Next steps:"
echo "  1. Restart Claude Code so it picks up the new MCP server + skill."
echo "  2. Ask Claude to index a docset, e.g.:"
echo "       'index https://react.dev/reference/react/useEffect as react-hooks'"
echo "  3. Then ask any technical question — auto-trigger will retrieve relevant chunks."
echo
echo "To uninstall: ./uninstall.sh"
