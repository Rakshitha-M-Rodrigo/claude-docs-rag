"""Structured tracing and logging for docs-rag decisions."""
import json
import time
import uuid
from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime


class DecisionTracer:
    """Traces every intent analysis, search, and retrieval decision."""

    def __init__(self, persist_dir: str):
        self.persist_dir = Path(persist_dir)
        self.log_dir = self.persist_dir / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / "decisions.jsonl"
        self.session_id = str(uuid.uuid4())[:8]

    def log(self, event_type: str, data: Dict[str, Any]) -> str:
        """Log a structured event. Returns the event ID."""
        event_id = f"{self.session_id}-{int(time.time()*1000)}"
        entry = {
            "event_id": event_id,
            "session_id": self.session_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event_type": event_type,
            "data": data,
        }
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return event_id

    def log_intent_analysis(self, query: str, result: Dict[str, Any]) -> str:
        return self.log("intent_analysis", {
            "query": query,
            "needs_docs": result.get("needs_docs"),
            "confidence": result.get("confidence"),
            "reasoning": result.get("reasoning"),
            "suggested_docsets": result.get("suggested_docsets"),
            "latency_ms": result.get("latency_ms"),
        })

    def log_search(self, query: str, docset_name: Optional[str], top_k: int,
                   results_count: int, results: List[Dict]) -> str:
        return self.log("search", {
            "query": query,
            "docset_name": docset_name,
            "top_k": top_k,
            "results_count": results_count,
            "citations": [r.get("citation") for r in results],
        })

    def log_tool_call(self, tool_name: str, arguments: Dict[str, Any], 
                      success: bool, error: Optional[str] = None) -> str:
        return self.log("tool_call", {
            "tool_name": tool_name,
            "arguments": arguments,
            "success": success,
            "error": error,
        })

    def get_recent(self, n: int = 20, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get the most recent N log entries, optionally filtered by type."""
        if not self.log_file.exists():
            return []
        
        entries = []
        with open(self.log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if event_type is None or entry.get("event_type") == event_type:
                        entries.append(entry)
                except json.JSONDecodeError:
                    continue
        
        return entries[-n:]

    def get_stats(self) -> Dict[str, Any]:
        """Get aggregate statistics from the log."""
        if not self.log_file.exists():
            return {"total_events": 0, "event_types": {}}
        
        counts = {}
        total = 0
        with open(self.log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    et = entry.get("event_type", "unknown")
                    counts[et] = counts.get(et, 0) + 1
                    total += 1
                except json.JSONDecodeError:
                    continue
        
        return {
            "total_events": total,
            "event_types": counts,
            "log_file": str(self.log_file),
            "session_id": self.session_id,
        }

    def export_session(self, output_path: Optional[str] = None) -> str:
        """Export current session logs to a file."""
        if output_path is None:
            output_path = self.log_dir / f"session-{self.session_id}.json"
        else:
            output_path = Path(output_path)
        
        entries = self.get_recent(n=10000)
        session_entries = [e for e in entries if e.get("session_id") == self.session_id]
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(session_entries, f, indent=2, ensure_ascii=False)
        
        return str(output_path)