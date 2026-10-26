"""A reset is a fresh run of the original input, never deletion of prior work."""
import hashlib
import uuid

import pytest
from langchain_core.messages import AIMessage

import dq_agent.workflow as workflow_module
from dq_agent.workflow import Workflow


RULES = {
    "required_columns": ["customer_id", "name", "email", "signup_date", "country"],
    "unique_columns": ["customer_id"],
    "date_formats": {"signup_date": {"input": "%m/%d/%Y", "output": "%Y-%m-%d"}},
    "categories": {"country": {"allowed": ["US", "CA"], "aliases": {"us": "US"}}},
}
HEADER = "customer_id,name,email,signup_date,country\n"
POSITIVE = (HEADER + "001,Ada,ada@example.test,10/24/2026,us\n" * 2).encode()
NEGATIVE = (HEADER + "101,Iris Demo,iris@example.test,02/30/2026,ZZ\n"
            ",Noah Demo,noah@example.test,2026-10-05,US\n").encode()


@pytest.fixture(autouse=True)
def local_only(monkeypatch):
    monkeypatch.setattr(workflow_module, "load_dotenv", lambda: False)
    monkeypatch.setattr(workflow_module, "record_summary", lambda *args: False)

    def prohibit_provider(*args, **kwargs):
        raise AssertionError("These tests must not construct a real model client")

    monkeypatch.setattr("dq_agent.reasoning.make_model", prohibit_provider)


@pytest.fixture
def workflow(tmp_path):
    instance = Workflow(tmp_path)
    yield instance
    instance.close()


def approve(workflow, job_id):
    binding = workflow.snapshot(job_id)["pending"]["binding"]
    return workflow.resume(job_id, {"action": "approve", "binding": binding})


def file_hashes(directory):
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in directory.iterdir() if path.is_file()}


def assert_fresh_run(workflow, original, rerun, source):
    assert rerun != original
    state = workflow.snapshot(rerun)["state"]
    assert state["rerun_of"] == original
    assert state["approval"] == {}
    assert state["export_approval"] == {}
    assert state["outputs"] == {}
    assert state["cycles"] == 0
    assert state["revisions"] == 0
    assert (workflow.engine.job_dir(rerun) / "source.csv").read_bytes() == source
    assert workflow.engine.load_rules(rerun) == workflow.engine.load_rules(original)
    assert not (workflow.engine.job_dir(rerun) / "stage.json").exists()
    assert not (workflow.engine.job_dir(rerun) / "export.json").exists()
    return state


def test_completed_positive_run_restarts_original_and_preserves_history(workflow):
    original = workflow.create(POSITIVE, RULES, name="Positive sample")
    original_repair_binding = workflow.snapshot(original)["pending"]["binding"]
    approve(workflow, original)
    approve(workflow, original)
    old_snapshot = workflow.snapshot(original)
    old_files = file_hashes(workflow.engine.job_dir(original))
    old_history = [dict(s.values) for s in workflow.graph.get_state_history(workflow._config(original))]
    assert len(workflow.engine.read_frame(original, staged=True)) == 1

    rerun = workflow.reset_job(original)
    new_state = assert_fresh_run(workflow, original, rerun, POSITIVE)
    assert workflow.job_name(rerun) == "Positive sample — rerun 1"
    assert new_state["status"] == "awaiting_repair_approval"
    assert new_state["model_decisions"] == 0
    assert len(workflow.engine.read_frame(rerun)) == 2
    assert new_state["findings"]["blocking_count"] > 0
    assert workflow.snapshot(original) == old_snapshot
    assert file_hashes(workflow.engine.job_dir(original)) == old_files
    assert [dict(s.values) for s in workflow.graph.get_state_history(workflow._config(original))] == old_history
    assert workflow.engine.verify_export(original) == old_snapshot["state"]["outputs"]
    with pytest.raises(ValueError, match="does not match"):
        workflow.resume(rerun, {"action": "approve", "binding": original_repair_binding})


def test_completed_negative_run_repeats_unresolved_original_facts(workflow):
    original = workflow.create(NEGATIVE, RULES, name="Negative sample")
    assert workflow.snapshot(original)["pending"]["kind"] == "clarification"
    repairs = [
        {"op": "set", "row": 0, "column": "signup_date", "value": "2026-02-28", "reason": "User checked original record", "user_supplied": True},
        {"op": "set", "row": 0, "column": "country", "value": "US", "reason": "User verified country", "user_supplied": True},
        {"op": "set", "row": 1, "column": "customer_id", "value": "102", "reason": "User supplied identifier", "user_supplied": True},
    ]
    workflow.resume(original, {"action": "revise", "plan": repairs})
    approve(workflow, original)
    approve(workflow, original)
    old_snapshot = workflow.snapshot(original)
    old_files = file_hashes(workflow.engine.job_dir(original))

    rerun = workflow.reset_job(original)
    state = assert_fresh_run(workflow, original, rerun, NEGATIVE)
    assert state["plan"] == []
    assert state["findings"]["blocking_count"] == 3
    assert workflow.snapshot(rerun)["pending"]["kind"] == "clarification"
    assert workflow.snapshot(original) == old_snapshot
    assert file_hashes(workflow.engine.job_dir(original)) == old_files


@pytest.mark.parametrize("cancel", [False, True])
def test_pending_or_cancelled_legacy_job_can_start_again(workflow, cancel):
    original = workflow.create(NEGATIVE, RULES)
    assert "demo" not in workflow.snapshot(original)["state"]
    if cancel:
        workflow.resume(original, {"action": "cancel"})
    before = workflow.snapshot(original)
    rerun = workflow.reset_job(original)
    assert_fresh_run(workflow, original, rerun, NEGATIVE)
    assert workflow.snapshot(rerun)["pending"]["kind"] == "clarification"
    assert workflow.snapshot(original) == before


def test_rerun_names_are_unique_case_insensitively_and_bounded(workflow):
    original = workflow.create(POSITIVE, RULES, name="A" * 80)
    suffix = " — rerun 1"
    collision_name = "A" * (80 - len(suffix)) + suffix
    workflow.create(POSITIVE, RULES, name=collision_name.lower())
    first = workflow.reset_job(original)
    second = workflow.reset_job(original)
    assert workflow.job_name(first).endswith(" — rerun 2")
    assert workflow.job_name(second).endswith(" — rerun 3")
    assert len(workflow.job_name(first)) <= 80
    assert len(workflow.job_name(second)) <= 80


@pytest.mark.parametrize("filename", ["source.csv", "rules.json"])
def test_tampered_originals_block_rerun_before_creating_any_job(workflow, filename):
    original = workflow.create(POSITIVE, RULES)
    before = workflow.snapshot(original)
    source = workflow.engine.job_dir(original) / filename
    source.write_bytes(source.read_bytes() + b" ")
    with pytest.raises(ValueError, match="changed after upload"):
        workflow.reset_job(original)
    assert workflow.list_jobs() == [original]
    assert len(workflow.engine.list_jobs()) == 1
    assert workflow.snapshot(original) == before


def test_rerun_never_reads_a_staged_or_exported_copy(workflow):
    original = workflow.create(POSITIVE, RULES)
    approve(workflow, original)
    approve(workflow, original)
    staged = next(workflow.engine.job_dir(original).glob("staged-*.csv"))
    exported = next(workflow.engine.job_dir(original).glob("validated-*.csv"))
    staged.write_bytes(b"unusable staged output")
    exported.write_bytes(b"unusable exported output")
    old_files = file_hashes(workflow.engine.job_dir(original))
    rerun = workflow.reset_job(original)
    assert_fresh_run(workflow, original, rerun, POSITIVE)
    assert file_hashes(workflow.engine.job_dir(original)) == old_files


class SuccessfulModel:
    def __init__(self):
        self.calls = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls += 1
        if self.calls % 2:
            return AIMessage(content="", tool_calls=[{"name": tool, "args": {}, "id": tool}
                                                     for tool in ("validate_dataset", "preview_repairs")])
        return AIMessage(content='{"use_all_candidates":true}')


def test_original_provider_mode_and_fresh_decision_budget_are_used(tmp_path):
    class EndlessModel(SuccessfulModel):
        def invoke(self, messages):
            self.calls += 1
            return AIMessage(content="", tool_calls=[{"name": "profile_dataset", "args": {}, "id": str(self.calls)}])

    workflow = Workflow(tmp_path, mode="nebius", model=EndlessModel())
    try:
        original = workflow.create(POSITIVE, RULES, name="Provider demo")
        assert workflow.snapshot(original)["state"]["model_decisions"] == 12
        assert workflow.snapshot(original)["state"]["status"] == "blocked"
        before = workflow.snapshot(original)
        workflow.mode = "offline"  # The current UI mode must not replace the saved run's mode.
        workflow.model = SuccessfulModel()
        rerun = workflow.reset_job(original)
        state = assert_fresh_run(workflow, original, rerun, POSITIVE)
        assert state["mode"] == "nebius"
        assert state["model_decisions"] == 2
        assert state["status"] == "awaiting_repair_approval"
        assert workflow.model.calls == 2
        assert workflow.snapshot(original) == before
    finally:
        workflow.close()


def test_rerun_survives_restart_without_touching_old_run(tmp_path):
    original_workflow = Workflow(tmp_path)
    original = original_workflow.create(POSITIVE, RULES, name="Saved sample")
    rerun = original_workflow.reset_job(original)
    before = original_workflow.snapshot(original)
    original_workflow.close()
    reopened = Workflow(tmp_path)
    try:
        assert reopened.resolve_job("Saved sample — rerun 1") == rerun
        assert reopened.snapshot(rerun)["pending"]["kind"] == "repair_approval"
        approve(reopened, rerun)
        approve(reopened, rerun)
        assert reopened.snapshot(rerun)["state"]["status"] == "complete"
        assert reopened.snapshot(original) == before
    finally:
        reopened.close()


@pytest.mark.parametrize("job_id", [str(uuid.uuid4()), "../outside"])
def test_missing_or_unsafe_job_identifier_is_rejected(workflow, job_id):
    with pytest.raises(ValueError, match="No saved job"):
        workflow.reset_job(job_id)
    assert workflow.engine.list_jobs() == []
