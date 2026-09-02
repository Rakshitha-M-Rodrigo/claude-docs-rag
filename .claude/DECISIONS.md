# DECISIONS — docs-rag

ADR-style records: context → decision → consequences. Append; never rewrite history.

## D-0001 — `mcp` dependency gains an upper bound (`>=1.28,<2`)

- **Date:** 2026-09-02
- **Context:** `requirements.txt:1` and `setup.py` both declared `mcp>=1.0.0`. The `mcp` SDK
  released a 2.x major that removes the v1 low-level server API this code uses —
  `src/docs_rag/server.py` does `from mcp.server import Server` and decorates handlers with
  `@self.server.list_tools()`. A fresh install on a colleague's machine resolved `mcp==2.1.1`,
  and the server died at startup with
  `AttributeError: 'Server' object has no attribute 'list_tools'`, surfacing as
  `CONNECTION_CLOSED` in Claude Code. Machines with an existing venv (`mcp==1.28.1`) could not
  see the defect. Both declarations matter: the workspace bootstrap runs
  `pip install -r requirements.txt` and then `pip install -e .` when a `setup.py` is present.
- **Decision:** `mcp>=1.28,<2` in **both** `requirements.txt` and `setup.py`, each with an inline
  comment saying the upper bound is load-bearing and the two must stay in sync. Range form, not an
  exact pin, because every other dependency in this repo is a range. The `1.28` floor is the
  known-good baseline, not a tested minimum. Migrating to the mcp 2.x API is not done here.
- **Evidence:** clean throwaway venvs, Python 3.14.4, no existing `.venv/` modified.
  Negative — `pip install "mcp>=1.0.0"` resolved `mcp==2.1.1`, and
  `from mcp.server import Server; hasattr(Server('x'), 'list_tools')` returned `False`.
  Positive — `pip install "mcp>=1.28,<2"` resolved `mcp==1.29.1`;
  `from mcp.server import Server`, `from mcp.server.stdio import stdio_server` and
  `from mcp.types import TextContent, Tool` all imported, and `hasattr(..., 'list_tools')`
  returned `True`; a full install from the corrected `requirements.txt` into a throwaway venv
  resolved `mcp==1.29.1` and `python -m docs_rag.server` launched.
- **Consequences:** a fresh install can no longer pick up mcp 2.x. Adopting 2.x later becomes an
  explicit code migration. A machine that already holds 2.x needs its venv rebuilt, not a pull —
  see `MCP-RECOVERY.md` in the workspace root. Workspace decision: D-0006;
  `agent_system` counterpart: D-0025.
