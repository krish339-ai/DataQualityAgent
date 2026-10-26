"""Fresh, labeled Nebius evaluation. Live calls require --live --consent-synthetic.

Only the committed fictional corpus is allowed. Gold answers and full-source
qualifications are never passed to the model. This script does not operate on
the app's saved jobs. Scripted review/approval is restricted to these fixtures.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from dq_agent.engine import Engine
from dq_agent.reasoning import make_model
from dq_agent.value_suggestions import preview_request
from dq_agent.workflow import Workflow

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "evaluations/nebius_fresh_v1/cases.json"


def csv_bytes(columns, rows):
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(rows)
    return buf.getvalue().encode()


def rules_for(corpus, case):
    rules = copy.deepcopy(corpus["base_rules"])
    rules["date_formats"]["signup_date"]["input"] = case.get("date_input", "%m/%d/%Y")
    rules["categories"]["country"]["aliases"] = case.get("aliases", {})
    rules["categories"]["country"]["allowed"] = case.get("allowed", ["US", "CA", "GB"])
    return rules


def key(item):
    return item["record"], item["field"]


def issue_set(issues):
    return {(None if x.get("row") is None else x["row"] + 1, x.get("column"), x["kind"]) for x in issues}


def score_detection(expected, actual):
    gold, observed = set(map(tuple, expected)), issue_set(actual)
    return {"expected": len(gold), "detected": len(gold & observed),
            "missed": sorted(gold-observed, key=str), "false_positives": sorted(observed-gold, key=str)}


def score_suggestions(gold_cells, targets, raw_items, delivered):
    """Score raw and guarded output independently; failures are not refusals.

    Answerable means the disclosed evidence supports a single gold value.
    Ambiguous date hypotheses have a separate hidden-truth mismatch score.
    Any asserted value on must_abstain cells is unsupported, even if lucky.
    """
    gold = {key(x): x for x in gold_cells}
    raw = {x["issue_id"]: x for x in raw_items}
    visible = {x["issue_id"]: x for x in delivered}
    details = []
    for target in targets:
        label = gold[key(target)]
        row = {"record": target["record"], "field": target["field"],
               "evidence": label["evidence"], "gold_value": label["value"]}
        for phase, items in (("raw", raw), ("delivered", visible)):
            item = items.get(target["issue_id"])
            disposition = item.get("disposition") if item else "missing"
            value = item.get("value") if item else None
            suggested = disposition == "suggest" and value is not None
            answerable = label["evidence"] == "answerable"
            row[phase] = {"disposition": disposition, "value": value,
                "suggested": suggested,
                "incorrect": suggested and (label["evidence"] == "must_abstain" or
                    (answerable and value != label["value"])),
                "unnecessary_refusal": answerable and disposition == "abstain",
                "correct": suggested and answerable and value == label["value"],
                "hypothesis_truth_mismatch": suggested and label["evidence"] == "ambiguous_hypothesis" and value != label["value"]}
        details.append(row)
    return details


class RecordingModel:
    """Record model output and token counts, never credentials or HTTP headers."""
    requests_started = 0
    def __init__(self, client, calls, phase="values"):
        self.client, self.calls, self.phase = client, calls, phase

    def bind_tools(self, tools):
        return RecordingModel(self.client.bind_tools(tools), self.calls, "investigation")

    def invoke(self, messages):
        if RecordingModel.requests_started >= 75:
            raise RuntimeError("Evaluation reached its 75-request network budget")
        RecordingModel.requests_started += 1
        started = time.monotonic()
        entry = {"phase": self.phase}
        try:
            result = self.client.invoke(messages)
            entry.update(content=result.content, tool_calls=getattr(result, "tool_calls", []),
                         usage=getattr(result, "usage_metadata", None))
            return result
        except Exception as exc:
            # Provider exception strings may contain URLs or headers; do not persist them.
            entry["error_type"] = type(exc).__name__
            raise
        finally:
            entry["seconds"] = round(time.monotonic() - started, 3)
            self.calls.append(entry)


def last_raw_items(calls):
    for call in reversed(calls):
        if call["phase"] != "values":
            continue
        try:
            parsed = json.loads(call.get("content", ""))
            rows = parsed["suggestions"]
            if not isinstance(rows, list) or any(not isinstance(x, dict) for x in rows):
                return []
            ids = [x.get("issue_id") for x in rows]
            if any(type(x) is not int for x in ids) or len(ids) != len(set(ids)):
                return []
            return rows
        except (ValueError, KeyError, TypeError):
            return []
    return []


def review_and_finish(workflow, job, case, columns, initial, suggestions):
    """The benchmark oracle acts as the human reviewer, never as model context."""
    original = csv_bytes(columns, case["rows"])
    if case["expected_outcome"] == "hold":
        ready = (initial.get("pending") or {}).get("kind") in {"repair_approval", "export_approval"}
        return {"expected": "hold", "passed": not ready, "unsafe_ready_for_approval": ready,
                "exported": False, "approval_decisions": 0,
                "note": "Harness withheld approval; no real user action or export was performed."}
    gold_rows = copy.deepcopy(case["rows"])
    plan = []
    for cell in case["gold_cells"]:
        row, field, value = cell["record"]-1, cell["field"], cell["value"]
        ci = columns.index(field)
        gold_rows[row][ci] = value
        if case["rows"][row][ci] != value:
            plan.append({"op": "set", "row": row, "column": field, "value": value,
                         "reason": "Scripted reviewer confirms the predeclared fictional source ledger.", "user_supplied": True})
    snap = workflow.snapshot(job)
    if snap["pending"] and (plan or snap["state"].get("plan")):
        workflow.resume(job, {"action": "revise", "plan": plan})
    decisions = 0
    for _ in range(3):
        snap = workflow.snapshot(job)
        pending = snap["pending"]
        if not pending or pending["kind"] not in {"repair_approval", "export_approval"}:
            break
        workflow.resume(job, {"action": "approve", "binding": pending["binding"]})
        decisions += 1
    snap = workflow.snapshot(job)
    result = snap["state"]
    output = result.get("outputs", {}).get("csv_path")
    actual = Path(output).read_bytes() if output else None
    expected = csv_bytes(columns, gold_rows)
    preserved = workflow.engine.original_upload(job)["data"] == original
    return {"expected": "complete", "passed": result.get("status") == "complete" and actual == expected and preserved and decisions == 2,
            "exported": bool(output), "approval_decisions": decisions, "source_preserved": preserved,
            "exact_output_match": actual == expected,
            "note": "Known fixture facts and both approvals were scripted by the evaluator; this is not autonomous completion."}


def summarize(results):
    groups = {}
    for cohort in sorted({x["cohort"] for x in results}):
        cases = [x for x in results if x["cohort"] == cohort]
        cells = [c for x in cases for c in x.get("cell_scores", [])]
        summary = {"cases": len(cases), "expected_issues": sum(x["detection"]["expected"] for x in cases),
                   "missed_issues": sum(len(x["detection"]["missed"]) for x in cases),
                   "false_positive_issues": sum(len(x["detection"]["false_positives"]) for x in cases),
                   "value_targets": len(cells), "answerable_value_targets": sum(x["evidence"]=="answerable" for x in cells),
                   "value_fallback_cases": sum(bool(x.get("value_fallback")) for x in cases),
                   "investigation_failures": sum(bool(x.get("investigation_failed")) for x in cases),
                   "rule_backed_gold_changes": sum(x["rule_candidate_coverage"]["expected"] for x in cases),
                   "rule_backed_changes_selected": sum(x["rule_candidate_coverage"]["selected_correctly"] for x in cases),
                   "reviewed_outcomes_passed": sum(x["reviewed_outcome"]["passed"] for x in cases),
                   "unsafe_ready_for_approval": sum(x["reviewed_outcome"].get("unsafe_ready_for_approval",False) for x in cases)}
        for phase in ("raw", "delivered"):
            summary[phase] = {"suggestions": sum(x[phase]["suggested"] for x in cells),
                              "incorrect_suggestions": sum(x[phase]["incorrect"] for x in cells),
                              "unnecessary_refusals": sum(x[phase]["unnecessary_refusal"] for x in cells),
                              "correct_answerable_suggestions": sum(x[phase]["correct"] for x in cells),
                              "missing_items": sum(x[phase]["disposition"]=="missing" for x in cells),
                              "hypothesis_truth_mismatches": sum(x[phase]["hypothesis_truth_mismatch"] for x in cells)}
        groups[cohort] = summary
    return groups


def run_case(corpus, case, root):
    calls = []
    workflow = Workflow(root, mode="nebius", model=RecordingModel(make_model("nebius"), calls))
    started = time.monotonic()
    try:
        job = workflow.create(csv_bytes(corpus["columns"],case["rows"]), rules_for(corpus,case))
        first = workflow.snapshot(job)
        findings = workflow.engine.validate(job)
        failed = first["state"].get("failure_stage") == "investigation"
        if failed and workflow.can_continue_manually(job):
            workflow.continue_manually(job)
        initial = workflow.snapshot(job)
        plan = initial["state"].get("plan", [])
        gold = {key(x):x for x in case["gold_cells"]}
        deterministic = workflow.engine.propose(job)
        expected_ops = [(x["row"]+1,x.get("column"),x.get("value")) for x in deterministic]
        selected = {(x["row"]+1,x.get("column"),x.get("value")) for x in plan}
        # Corpus oracle validates every deterministic candidate before scoring selection.
        assert all((r,f) in gold and gold[(r,f)]["value"]==v for r,f,v in expected_ops)
        request, response, scores = None, None, []
        if initial["pending"]:
            fields = workflow.preview_value_request(job, [])["available_fields"]
            if fields:
                request = workflow.preview_value_request(job, fields)
                # Store each exact fictional request preview before the network call.
                (root / (case["id"]+"-payload-preview.json")).write_text(json.dumps(request["payload"],indent=2))
                response = workflow.suggest_values(job, request, True)
                raw = last_raw_items(calls)
                delivered = response["suggestions"] if not response["fallback"] else []
                scores = score_suggestions(case["gold_cells"], request["targets"], raw, delivered)
        reviewed = review_and_finish(workflow,job,case,corpus["columns"],initial,response)
        return {"id":case["id"], "cohort":case["cohort"],
                "detection":score_detection(case["expected_issues"],findings["issues"]),
                "observed_issues": [{"record":None if i["row"] is None else i["row"]+1,"field":i["column"],"kind":i["kind"]} for i in findings["issues"]],
                "investigation_failed":failed, "investigation_error":first["state"].get("error",""),
                "rule_candidate_coverage":{"expected":len(expected_ops),"selected_correctly":sum(x in selected for x in expected_ops)},
                "value_request": request["payload"] if request else None,
                "value_targets": request["targets"] if request else [],
                "value_fallback":response["fallback"] if response else None,
                "delivered_suggestions":response["suggestions"] if response else [],
                "cell_scores":scores,"reviewed_outcome":reviewed,"calls":calls,
                "seconds":round(time.monotonic()-started,3)}
    finally:
        workflow.close()


def preflight(corpus,root):
    engine = Engine(root)
    rows=[]
    for case in corpus["cases"]:
        job = engine.create_job(csv_bytes(corpus["columns"],case["rows"]), rules_for(corpus,case))
        detection=score_detection(case["expected_issues"],engine.validate(job)["issues"])
        if case["cohort"] != "source_coverage":
            assert not detection["missed"] and not detection["false_positives"], (case["id"], detection)
        request=preview_request(engine,job,[],[],mode="nebius",pending_kind="clarification",revisions=0)
        request=preview_request(engine,job,[],request["available_fields"],mode="nebius",pending_kind="clarification",revisions=0)
        assert not request["omitted_count"]
        rows.append({"id":case["id"],"cohort":case["cohort"],"detection":detection,"potential_disclosure":request["payload"]})
    (root/"preflight.json").write_text(json.dumps(rows,indent=2))
    print(json.dumps({"cases":len(rows),"expected_source_coverage_misses":sum(len(x["detection"]["missed"]) for x in rows),"preflight":"passed"}),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--consent-synthetic',action='store_true')
    parser.add_argument('--run-name',default=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    args=parser.parse_args()
    if not args.run_name.replace('-','').replace('_','').isalnum():
        parser.error('run-name must contain only letters, digits, hyphens and underscores')
    root=ROOT/'tmp'/'nebius-evaluation'/args.run_name
    root.mkdir(parents=True,exist_ok=False)
    corpus=json.loads(CORPUS.read_text())
    preflight(corpus,root/'preflight')
    if not args.live:
        return
    if not args.consent_synthetic:
        parser.error('Live calls require --consent-synthetic for the committed fictional payloads')
    load_dotenv(ROOT/'.env')
    os.environ['LANGSMITH_TRACING']='false'
    os.environ['LANGCHAIN_TRACING_V2']='false'
    os.environ['DQ_LANGSMITH_TRACING']='false'
    report={"suite":"nebius-fresh-v1","provider":"nebius","model":os.getenv('NEBIUS_MODEL'),
            "temperature":0,"started_at_utc":datetime.now(timezone.utc).isoformat(),
            "application_commit":subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            "corpus_sha256":hashlib.sha256(CORPUS.read_bytes()).hexdigest(),
            "runner_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "repeat_count":1,"network_request_budget":75,"fixture_type":"new fictional cases; oracle labels fixed before live calls",
            "review":"scripted oracle review and approvals on synthetic records only",
            "results":[]}
    for case in corpus['cases']:
        print('Running '+case['id'],flush=True)
        result=run_case(corpus,case,root/case['id'])
        report['results'].append(result)
        report['cohorts']=summarize(report['results'])
        (root/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps({'case':case['id'],'calls':len(result['calls']),'missed':len(result['detection']['missed']), 'reviewed_outcome_passed':result['reviewed_outcome']['passed']}),flush=True)
    report['finished_at_utc']=datetime.now(timezone.utc).isoformat()
    report['total_calls']=sum(len(x['calls']) for x in report['results'])
    report['total_tokens']=sum((c.get('usage') or {}).get('total_tokens',0) for x in report['results'] for c in x['calls'])
    (root/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Finished: '+str(root/'results.json'),flush=True)


if __name__=='__main__':
    main()
