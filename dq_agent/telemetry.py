"""Opt-in aggregate tracing, deliberately separate from raw graph state."""
import os
from datetime import datetime, timezone
from uuid import uuid4


def record_summary(mode: str, events: list[dict], issue_count: int) -> bool:
    if os.getenv("DQ_LANGSMITH_TRACING", "false").lower() != "true":
        return False
    try:
        from langsmith import Client
        client = Client(timeout_ms=3000)
        client.create_run(name="dq-investigation-summary", run_type="chain", id=uuid4(),
                          inputs={"mode": mode, "issue_count": issue_count},
                          outputs={"steps": len(events), "read_tool_calls": sum(e.get("event") == "read_tool" for e in events)},
                          start_time=datetime.now(timezone.utc), end_time=datetime.now(timezone.utc),
                          project_name=os.getenv("LANGSMITH_PROJECT", "data-quality-agent"))
        return True
    except Exception:
        return False
