"""Manual recovery is explicit, local, and preserves both write approvals."""
import hashlib
import uuid

import pytest
from langchain_core.messages import AIMessage

import dq_agent.workflow as workflow_module
from dq_agent.workflow import Workflow


RULES = {"required_columns": ["customer_id", "name", "email", "signup_date", "country"],
         "unique_columns": ["customer_id"],
         "date_formats": {"signup_date": {"input": "%m/%d/%Y", "output": "%Y-%m-%d"}},
         "categories": {"country": {"allowed": ["US", "CA", "GB"], "aliases": {"us": "US"}}}}
HEADER = "customer_id,name,email,signup_date,country\n"
NEGATIVE = (HEADER + "101,Iris Demo,iris@example.com,02/30/2026,ZZ\n"
            ",Noah Demo,noah@example.com,2026-10-05,US\n").encode()
CLEAN = (HEADER + "101,Iris Demo,iris@example.com,2026-02-28,US\n").encode()
ERROR = "The model returned an invalid plan twice. No changes were made."
FIXES = [
    {"op": "set", "row": 0, "column": "signup_date", "value": "2026-02-28", "reason": "Fictional test correction", "user_supplied": True},
    {"op": "set", "row": 0, "column": "country", "value": "US", "reason": "Fictional test correction", "user_supplied": True},
    {"op": "set", "row": 1, "column": "customer_id", "value": "102", "reason": "Fictional test correction", "user_supplied": True},
]


@pytest.fixture(autouse=True)
def local_only(monkeypatch):
    monkeypatch.setattr(workflow_module, "load_dotenv", lambda: False)
    monkeypatch.setattr(workflow_module, "record_summary", lambda *args: False)
    def no_provider(*args, **kwargs):
        raise AssertionError("Recovery tests must never construct a real model")
    monkeypatch.setattr("dq_agent.reasoning.make_model", no_provider)


class MalformedModel:
    def __init__(self, reply="not JSON"):
        self.calls = 0
        self.reply = reply

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls += 1
        if self.calls % 3 == 1:
            return AIMessage(content="", tool_calls=[{"name": name, "args": {}, "id": name}
                                                     for name in ("validate_dataset", "preview_repairs")])
        return AIMessage(content=self.reply)


@pytest.fixture
def workflow(tmp_path):
    service = Workflow(tmp_path, mode="nebius", model=MalformedModel())
    yield service
    service.close()


def approve(workflow, job):
    pending = workflow.snapshot(job)["pending"]
    return workflow.resume(job, {"action": "approve", "binding": pending["binding"]})


def hashes(directory):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir() if p.is_file()}


def legacy_job(workflow, *, error=ERROR, **values):
    job = workflow._store_new_job(NEGATIVE, RULES, "Old stopped job")
    state = {"job_id": job, "mode": "nebius", "status": "blocked", "error": error,
             "model_decisions": 2, "cycles": 0, "revisions": 0, "approval": {}, "export_approval": {}, "outputs": {}}
    state.update(values)
    workflow.graph.update_state(workflow._config(job), state, as_node="investigate")
    return job


@pytest.mark.parametrize("reply", ["not JSON", '{"candidate_ids":[0]}', '{"invented_action":"repair"}'])
def test_failed_model_preserves_findings(workflow, reply):
    workflow.model.reply = reply
    job = workflow.create(NEGATIVE, RULES)
    snap = workflow.snapshot(job)
    state = snap["state"]
    assert state["status"] == "blocked"
    assert state["failure_stage"] == "investigation"
    assert state["findings"]["blocking_count"] == 3
    assert state["error"] == state["investigation_error"] == ERROR
    assert state["model_decisions"] == workflow.model.calls == 3
    assert state["plan"] == []
    assert state["preview"] == state["approval"] == state["export_approval"] == {}
    assert snap["pending"] is None
    assert workflow.can_continue_manually(job)


def test_same_job_recovery_requires_both_approvals(workflow):
    job = workflow.create(NEGATIVE, RULES, name="Negative recovery")
    before = workflow.snapshot(job)
    originals = hashes(workflow.engine.job_dir(job))
    assert workflow.can_continue_manually(job)
    assert workflow.snapshot(job) == before  # The eligibility query is read-only.
    snapshot = workflow.continue_manually(job)
    state = snapshot["state"]
    assert workflow.job_name(job) == "Negative recovery"
    assert workflow.list_jobs() == [job]
    assert state["mode"] == "nebius"
    assert state["model_decisions"] == workflow.model.calls == 3
    assert state["manual_recovery"] is True
    assert state["investigation_error"] == ERROR
    assert state["error"] == ""
    assert state["findings"]["blocking_count"] == state["preview"]["blocking_count"] == 3
    assert state["plan"] == []
    assert state["cycles"] == state["revisions"] == 0
    assert snapshot["pending"]["kind"] == "clarification"
    assert state["events"][-1]["event"] == "manual_recovery"
    assert not any(event["event"] == "decision_complete" for event in state["events"])
    assert hashes(workflow.engine.job_dir(job)) == originals
    assert not workflow.can_continue_manually(job)
    with pytest.raises(ValueError, match="stopped investigation"):
        workflow.continue_manually(job)

    revised = workflow.resume(job, {"action": "revise", "plan": FIXES})
    assert revised["pending"]["kind"] == "repair_approval"
    assert revised["state"]["preview"]["blocking_count"] == 0
    assert revised["state"]["revisions"] == 1
    assert hashes(workflow.engine.job_dir(job)) == originals
    with pytest.raises(ValueError, match="Explicit approval"):
        workflow.engine.apply(job, FIXES, {})
    first = approve(workflow, job)
    assert first["pending"]["kind"] == "export_approval"
    assert not (workflow.engine.job_dir(job) / "export.json").exists()
    with pytest.raises(ValueError, match="Explicit approval"):
        workflow.engine.export(job, {})
    final = approve(workflow, job)
    assert final["state"]["status"] == "complete"
    assert workflow.model.calls == 3
    assert workflow.engine.validate(job, staged=True)["blocking_count"] == 0
    assert (workflow.engine.job_dir(job) / "source.csv").read_bytes() == NEGATIVE
    assert any(saved.values.get("error") == ERROR for saved in workflow.graph.get_state_history(workflow._config(job)))


def test_clean_input_still_needs_unchanged_copy_approval(workflow):
    job = workflow.create(CLEAN, RULES)
    recovered = workflow.continue_manually(job)
    assert recovered["pending"]["kind"] == "repair_approval"
    assert recovered["state"]["plan"] == []
    assert not (workflow.engine.job_dir(job) / "stage.json").exists()


def test_legacy_missing_findings_recovers_after_restart(tmp_path):
    first = Workflow(tmp_path)
    job = legacy_job(first)
    assert "findings" not in first.snapshot(job)["state"]
    first.close()
    reopened = Workflow(tmp_path, mode="offline")
    try:
        assert reopened.can_continue_manually(job)
        snap = reopened.continue_manually(job)
        assert snap["pending"]["kind"] == "clarification"
        assert snap["state"]["findings"]["blocking_count"] == 3
        assert snap["state"]["mode"] == "nebius"
        assert snap["state"]["model_decisions"] == 2
    finally:
        reopened.close()


def test_retry_preserves_budget_and_clears_stale_proposal(workflow):
    job = workflow.create(NEGATIVE, RULES)
    workflow.graph.update_state(workflow._config(job), {"plan": FIXES, "preview": {"blocking_count": 0},
                                                     "findings": {"blocking_count": 0}}, as_node="investigate")
    snap = workflow.retry(job)
    assert snap["state"]["model_decisions"] == workflow.model.calls == 6
    assert snap["state"]["findings"]["blocking_count"] == 3
    assert snap["state"]["plan"] == []
    assert snap["state"]["preview"] == {}
    recovered = workflow.continue_manually(job)
    assert recovered["state"]["model_decisions"] == workflow.model.calls == 6


def test_exhausted_model_budget_can_continue_manually(workflow):
    job = legacy_job(workflow, error="This job exhausted its 12-decision budget. Start a new job after resolving the cause.",
                     model_decisions=12, revisions=2)
    recovered = workflow.continue_manually(job)
    assert recovered["state"]["model_decisions"] == 12
    assert recovered["state"]["revisions"] == 2
    assert workflow.model.calls == 0


def test_provider_setup_failure_keeps_local_findings(workflow):
    class BrokenSetup:
        def bind_tools(self, tools):
            raise ValueError("PRIVATE provider configuration")
    workflow.model = BrokenSetup()
    job = workflow.create(NEGATIVE, RULES)
    state = workflow.snapshot(job)["state"]
    assert state["failure_stage"] == "investigation"
    assert state["findings"]["blocking_count"] == 3
    assert "PRIVATE" not in state["error"]
    assert workflow.can_continue_manually(job)


def test_input_change_during_investigation_is_not_recoverable(workflow, monkeypatch):
    def corrupt_then_fail(engine, job_id, *args, **kwargs):
        path = engine.job_dir(job_id) / "source.csv"
        path.write_bytes(path.read_bytes() + b" ")
        raise ValueError("Changed source")
    monkeypatch.setattr(workflow_module, "investigate", corrupt_then_fail)
    job = workflow.create(NEGATIVE, RULES)
    state = workflow.snapshot(job)["state"]
    assert state["failure_stage"] == "input_validation"
    assert state["findings"] == {}
    assert not workflow.can_continue_manually(job)


@pytest.mark.parametrize("filename", ["source.csv", "rules.json", "original.bin", "manifest.json"])
def test_tamper_refuses_without_checkpoint_mutation(workflow, filename):
    job = workflow.create_upload(NEGATIVE, "negative.csv", RULES)
    before = workflow.snapshot(job)
    path = workflow.engine.job_dir(job) / filename
    path.write_bytes(path.read_bytes() + b" ")
    assert not workflow.can_continue_manually(job)
    with pytest.raises(ValueError, match="changed"):
        workflow.continue_manually(job)
    assert workflow.snapshot(job) == before


@pytest.mark.parametrize("stage", ["input_validation", "preview", "apply", "revalidation", "export_approval", "export"])
def test_other_failure_stages_never_use_recovery(workflow, stage):
    job = legacy_job(workflow, failure_stage=stage)
    before = workflow.snapshot(job)
    assert not workflow.can_continue_manually(job)
    with pytest.raises(ValueError, match="stopped investigation"):
        workflow.continue_manually(job)
    assert workflow.snapshot(job) == before


@pytest.mark.parametrize("filename", ["stage.json", "export.json", "staged-orphan.csv", "changes-orphan.json"])
def test_any_write_artifact_refuses_recovery(workflow, filename):
    job = workflow.create(NEGATIVE, RULES)
    (workflow.engine.job_dir(job) / filename).write_text("untrusted or unfinished artifact")
    assert not workflow.can_continue_manually(job)
    with pytest.raises(ValueError, match="files"):
        workflow.continue_manually(job)


def test_prior_approval_cannot_be_erased_to_enable_recovery(workflow):
    job = legacy_job(workflow)
    workflow.graph.update_state(workflow._config(job), {"approval": {"approved": True}}, as_node="investigate")
    workflow.graph.update_state(workflow._config(job), {"approval": {}}, as_node="investigate")
    assert not workflow.can_continue_manually(job)
    with pytest.raises(ValueError, match="previously reached"):
        workflow.continue_manually(job)


@pytest.mark.parametrize("changes", [{"revisions": 12}, {"cycles": 1}, {"approval": {"approved": True}},
                                    {"error": "Repair was not committed: failed"}, {"status": "complete"}])
def test_ineligible_states_refuse_recovery(workflow, changes):
    job = legacy_job(workflow, **changes)
    assert not workflow.can_continue_manually(job)
    with pytest.raises(ValueError):
        workflow.continue_manually(job)


@pytest.mark.parametrize("job_id", ["../outside", str(uuid.uuid4())])
def test_invalid_or_missing_job_refused(workflow, job_id):
    assert not workflow.can_continue_manually(job_id)
    with pytest.raises(ValueError):
        workflow.continue_manually(job_id)
