"""Scripted demonstrations use built-in synthetic data only, never user files."""
import argparse
import json
import time
from pathlib import Path

from .workflow import Workflow


RULES = {"required_columns": ["customer_id", "name", "signup_date", "country"],
         "unique_columns": ["customer_id"],
         "date_formats": {"signup_date": {"input": "%m/%d/%Y", "output": "%Y-%m-%d"}},
         "categories": {"country": {"allowed": ["US", "CA"], "aliases": {"us": "US", "ca": "CA"}}}}
HEADER = "customer_id,name,signup_date,country\n"


def fixtures():
    """Ten known repairable cases; synthetic identities, explicit expectations."""
    return [
        ("clean", "001,Ada,2026-10-01,US\n", "001,Ada,2026-10-01,US\n", []),
        ("duplicate_pair", "001,Ada,2026-10-01,US\n" * 2, "001,Ada,2026-10-01,US\n", []),
        ("duplicate_triple", "001,Ada,2026-10-01,US\n" * 3, "001,Ada,2026-10-01,US\n", []),
        ("category_us", "001,Ada,2026-10-01,us\n", "001,Ada,2026-10-01,US\n", []),
        ("category_ca", "002,Bo,2026-10-01,ca\n", "002,Bo,2026-10-01,CA\n", []),
        ("date_oct", "001,Ada,10/01/2026,US\n", "001,Ada,2026-10-01,US\n", []),
        ("date_feb", "001,Ada,02/28/2024,US\n", "001,Ada,2024-02-28,US\n", []),
        ("missing_id", ",Ada,2026-10-01,US\n", "003,Ada,2026-10-01,US\n",
         [{"op": "set", "row": 0, "column": "customer_id", "value": "003", "reason": "Synthetic user supplies known ID", "user_supplied": True}]),
        ("mixed", "001,Ada,10/01/2026,us\n" * 2, "001,Ada,2026-10-01,US\n", []),
        ("mixed_two_rows", "001,Ada,10/01/2026,us\n002,Bo,10/02/2026,ca\n",
         "001,Ada,2026-10-01,US\n002,Bo,2026-10-02,CA\n", []),
    ]


def run_case(workflow, case):
    name, data, expected, manual = case
    start = time.monotonic()
    job = workflow.create((HEADER + data).encode(), RULES)
    for _ in range(6):
        snap = workflow.snapshot(job)
        pending = snap["pending"]
        if not pending:
            break
        if pending["kind"] == "clarification":
            if not manual:
                break
            workflow.resume(job, {"action": "revise", "plan": snap["state"]["plan"] + manual})
        else:
            workflow.resume(job, {"action": "approve", "binding": pending["binding"]})
    snap = workflow.snapshot(job)
    state = snap["state"]
    actual = Path(state["outputs"]["csv_path"]).read_text(encoding="utf-8") if state.get("outputs") else ""
    elapsed = round(time.monotonic() - start, 3)
    return {"case": name, "job_id": job, "status": state.get("status"), "seconds": elapsed,
            "passed": state.get("status") == "complete" and actual == HEADER + expected and elapsed < 300,
            "outputs": state.get("outputs", {})}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["demo", "evaluate"])
    parser.add_argument("--root", type=Path, default=Path(".demo-data"))
    args = parser.parse_args()
    workflow = Workflow(args.root, mode="offline")
    try:
        cases = fixtures() if args.command == "evaluate" else [fixtures()[8]]
        results = [run_case(workflow, case) for case in cases]
        report = {"mode": "offline", "model_calls": 0, "human_decisions": "scripted for built-in synthetic fixtures only",
                  "passed": sum(r["passed"] for r in results), "total": len(results), "results": results}
        args.root.mkdir(parents=True, exist_ok=True)
        (args.root / "evaluation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0 if all(r["passed"] for r in results) else 1
    finally:
        workflow.close()


if __name__ == "__main__":
    raise SystemExit(main())
