import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from dq_agent.__main__ import HEADER, RULES, fixtures, run_case
from dq_agent.reasoning import InvestigationError, investigate
from dq_agent.workflow import Workflow


def approve(workflow, job):
    binding = workflow.snapshot(job)["pending"]["binding"]
    return workflow.resume(job, {"action": "approve", "binding": binding})


@pytest.mark.parametrize("case", fixtures(), ids=[c[0] for c in fixtures()])
def test_end_to_end_known_outputs(tmp_path, case):
    workflow = Workflow(tmp_path)
    try:
        assert run_case(workflow, case)["passed"]
    finally:
        workflow.close()


def test_restart_between_both_approvals(tmp_path):
    workflow = Workflow(tmp_path)
    job = workflow.create((HEADER + "001,Ada,10/01/2026,us\n").encode(), RULES)
    assert workflow.snapshot(job)["pending"]["kind"] == "repair_approval"
    assert not (workflow.engine.job_dir(job) / "stage.json").exists()
    workflow.close()
    resumed = Workflow(tmp_path)
    approve(resumed, job)
    assert resumed.snapshot(job)["pending"]["kind"] == "export_approval"
    assert not (resumed.engine.job_dir(job) / "export.json").exists()
    resumed.close()
    final = Workflow(tmp_path)
    approve(final, job)
    assert final.snapshot(job)["state"]["status"] == "complete"
    final.close()


def test_rejection_does_not_write(tmp_path):
    workflow = Workflow(tmp_path)
    job = workflow.create((HEADER + "001,Ada,10/01/2026,us\n").encode(), RULES)
    workflow.resume(job, {"action": "cancel"})
    assert workflow.snapshot(job)["state"]["status"] == "cancelled"
    assert not (workflow.engine.job_dir(job) / "stage.json").exists()
    workflow.close()


def test_deleted_job_cannot_resume(tmp_path):
    workflow = Workflow(tmp_path)
    job = workflow.create((HEADER + "001,Ada,2026-10-01,US\n").encode(), RULES)
    assert job in workflow.list_jobs()
    workflow.delete(job)
    assert job not in workflow.list_jobs()
    assert not workflow.engine.job_dir(job).exists()
    assert not workflow.snapshot(job)["state"]
    workflow.close()


def test_failed_file_deletion_keeps_checkpoint_discoverable(tmp_path):
    workflow = Workflow(tmp_path)
    job = workflow.create((HEADER + "001,Ada,2026-10-01,US\n").encode(), RULES)
    (workflow.engine.job_dir(job) / "unexpected-folder").mkdir()
    with pytest.raises(ValueError):
        workflow.delete(job)
    assert job in workflow.list_jobs()
    assert workflow.snapshot(job)["pending"] is not None
    workflow.close()


class FakeModel:
    def __init__(self):
        self.calls, self.messages = 0, []

    def bind_tools(self, tools):
        self.tool_names = {t.name for t in tools}
        return self

    def invoke(self, messages):
        self.messages.extend(messages)
        self.calls += 1
        if self.calls == 1:
            return AIMessage(content="", tool_calls=[{"name": n, "args": {}, "id": n}
                                                      for n in ("validate_dataset", "preview_repairs")])
        return AIMessage(content='{"use_all_candidates": true}')


def test_langchain_tool_loop_receives_no_customer_values(tmp_path):
    fake = FakeModel()
    workflow = Workflow(tmp_path, mode="nebius", model=fake)
    secret_value = "PRIVATE_CUSTOMER_ZEBRA"
    job = workflow.create((HEADER + f"001,{secret_value},10/01/2026,us\n").encode(), RULES)
    assert workflow.snapshot(job)["pending"]["kind"] == "repair_approval"
    assert fake.calls == 2
    assert fake.tool_names == {"profile_dataset", "lookup_rules", "validate_dataset", "preview_repairs"}
    sent = json.dumps([m.model_dump() for m in fake.messages])
    assert secret_value not in sent
    assert "customer_id" not in sent
    assert "10/01/2026" not in sent
    assert "001" not in sent
    workflow.close()


def test_invalid_model_output_is_bounded(tmp_path):
    class Invalid(FakeModel):
        def invoke(self, messages):
            self.calls += 1
            return AIMessage(content="not JSON")
    fake = Invalid()
    workflow = Workflow(tmp_path, mode="nebius", model=fake)
    job = workflow.create((HEADER + "001,Ada,2026-10-01,US\n").encode(), RULES)
    assert workflow.snapshot(job)["state"]["status"] == "blocked"
    assert fake.calls == 2
    assert not (workflow.engine.job_dir(job) / "stage.json").exists()
    workflow.close()


def test_changed_source_cannot_use_old_approval(tmp_path):
    workflow = Workflow(tmp_path)
    job = workflow.create((HEADER + "001,Ada,10/01/2026,us\n").encode(), RULES)
    (workflow.engine.job_dir(job) / "source.csv").write_text(HEADER + "002,Bo,10/01/2026,us\n")
    approve(workflow, job)
    assert workflow.snapshot(job)["state"]["status"] == "blocked"
    assert not (workflow.engine.job_dir(job) / "stage.json").exists()
    workflow.close()


def test_staged_tamper_before_export_is_blocked(tmp_path):
    workflow = Workflow(tmp_path)
    job = workflow.create((HEADER + "001,Ada,2026-10-01,US\n").encode(), RULES)
    approve(workflow, job)
    staged = next(workflow.engine.job_dir(job).glob("staged-*.csv"))
    staged.write_text(HEADER + "001,Eve,2026-10-01,US\n")
    approve(workflow, job)
    assert workflow.snapshot(job)["state"]["status"] == "blocked"
    assert not (workflow.engine.job_dir(job) / "export.json").exists()
    workflow.close()


def test_transient_model_failure_retries_without_write(tmp_path, monkeypatch):
    monkeypatch.setattr("dq_agent.reasoning.time.sleep", lambda _: None)
    class Flaky(FakeModel):
        failed = False
        def invoke(self, messages):
            if not self.failed:
                self.failed = True
                raise TimeoutError("PRIVATE provider error")
            return super().invoke(messages)
    workflow = Workflow(tmp_path, mode="nebius", model=Flaky())
    job = workflow.create((HEADER + "001,Ada,10/01/2026,us\n").encode(), RULES)
    assert workflow.snapshot(job)["pending"]["kind"] == "repair_approval"
    assert not (workflow.engine.job_dir(job) / "stage.json").exists()
    workflow.close()


def test_tool_loop_is_bounded_at_twelve_calls(tmp_path):
    class Loop(FakeModel):
        def invoke(self, messages):
            self.calls += 1
            return AIMessage(content="", tool_calls=[{"name": "profile_dataset", "args": {}, "id": str(self.calls)}])
    fake = Loop()
    workflow = Workflow(tmp_path, mode="nebius", model=fake)
    job = workflow.create((HEADER + "001,Ada,2026-10-01,US\n").encode(), RULES)
    assert workflow.snapshot(job)["state"]["status"] == "blocked"
    assert fake.calls == 12
    workflow.retry(job)
    assert fake.calls == 12
    assert workflow.snapshot(job)["state"]["model_decisions"] == 12
    workflow.close()


def test_old_browser_binding_cannot_approve_revised_plan(tmp_path):
    workflow = Workflow(tmp_path)
    job = workflow.create((HEADER + "001,Ada,10/01/2026,us\n").encode(), RULES)
    snap = workflow.snapshot(job)
    old_binding = snap["pending"]["binding"]
    revised = snap["state"]["plan"] + [{"op": "set", "row": 0, "column": "name", "value": "Known correction", "user_supplied": True, "reason": "Verified by user"}]
    workflow.resume(job, {"action": "revise", "plan": revised})
    with pytest.raises(ValueError, match="does not match"):
        workflow.resume(job, {"action": "approve", "binding": old_binding})
    assert not (workflow.engine.job_dir(job) / "stage.json").exists()
    workflow.close()


def test_revised_plan_needs_new_approval(tmp_path):
    workflow = Workflow(tmp_path)
    job = workflow.create((HEADER + "001,Ada,10/01/2026,us\n").encode(), RULES)
    plan = workflow.snapshot(job)["state"]["plan"] + [{"op": "set", "row": 0, "column": "name", "value": "Known name", "user_supplied": True, "reason": "User correction"}]
    workflow.resume(job, {"action": "revise", "plan": plan})
    assert workflow.snapshot(job)["pending"]["kind"] == "repair_approval"
    assert not (workflow.engine.job_dir(job) / "stage.json").exists()
    workflow.close()
