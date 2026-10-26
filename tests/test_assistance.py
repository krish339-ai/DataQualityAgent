import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from dq_agent.assistance import suggest_corrections
from dq_agent.workflow import Workflow


ROOT = Path(__file__).resolve().parents[1]
RULES = json.loads((ROOT / "samples/import_rules.json").read_text())
NEGATIVE = (ROOT / "samples/customers_negative.csv").read_bytes()


class AssistantModel:
    def __init__(self, replies=None):
        self.replies = replies or [AIMessage(content='{"candidate_ids":[],"guidance":[]}')]
        self.messages = []
        self.calls = 0
        self.investigation_calls = 0
        self.bound = False

    def bind_tools(self, _tools):
        self.bound = True
        return self

    def invoke(self, messages):
        if self.bound:
            self.investigation_calls += 1
            if self.investigation_calls == 1:
                return AIMessage(content="", tool_calls=[{"name": name, "args": {}, "id": name}
                                  for name in ("validate_dataset", "preview_repairs")])
            self.bound = False
            return AIMessage(content='{"use_all_candidates":true}')
        self.calls += 1
        self.messages.append(messages.copy())
        reply = self.replies[min(self.calls - 1, len(self.replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return reply


def saved_files(workflow, job):
    return {p.name: p.read_bytes() for p in workflow.engine.job_dir(job).iterdir()}


def test_negative_assistance_keeps_missing_facts_blank_and_job_unchanged(tmp_path):
    fake = AssistantModel([AIMessage(content=json.dumps({"candidate_ids": [], "guidance": [
        {"issue_id": 0, "next_step": "confirm_value"},
        {"issue_id": 1, "next_step": "confirm_date"},
        {"issue_id": 2, "next_step": "choose_allowed_value"},
    ]}))])
    workflow = Workflow(tmp_path, mode="nebius", model=fake)
    job = workflow.create(NEGATIVE, RULES)
    before, files = workflow.snapshot(job), saved_files(workflow, job)
    result = workflow.suggest_corrections(job)
    assert result["source"] == "nebius" and result["fallback"] is False
    assert result["operations"] == [] and result["unresolved_count"] == 3
    assert {(row["record"], row["field"]) for row in result["rows"]} == {
        (1, "signup_date"), (1, "country"), (2, "customer_id")}
    assert all(row["new_value"] == row["reason"] == "" for row in result["rows"])
    assert all(row["action"] == "set" for row in result["rows"])
    assert any("%Y-%m-%d" in item["message"] for item in result["guidance"])
    assert any("US, CA, GB" in item["message"] for item in result["guidance"])
    assert workflow.snapshot(job) == before and saved_files(workflow, job) == files
    assert fake.calls == 1
    workflow.close()


def test_assistance_never_sends_private_names_values_rules_or_user_reasons(tmp_path):
    fake = AssistantModel()
    workflow = Workflow(tmp_path, mode="fireworks", model=fake)
    rules = {"required_columns": ["PRIVATE_COLUMN_ALPHA"], "unique_columns": [],
             "date_formats": {}, "categories": {"PRIVATE_COLUMN_BETA": {"allowed": ["PRIVATE_ALLOWED_VALUE"], "aliases": {}}}}
    job = workflow.create(b"PRIVATE_COLUMN_ALPHA,PRIVATE_COLUMN_BETA\n,PRIVATE_CELL_VALUE\n", rules)
    workflow.resume(job, {"action": "revise", "plan": [{"op": "set", "row": 0,
        "column": "PRIVATE_COLUMN_ALPHA", "value": "PRIVATE_REPLACEMENT", "reason": "PRIVATE_USER_REASON", "user_supplied": True}]})
    workflow.suggest_corrections(job)
    sent = json.dumps([[message.model_dump() for message in messages] for messages in fake.messages])
    for secret in ("PRIVATE_COLUMN_ALPHA", "PRIVATE_COLUMN_BETA", "PRIVATE_ALLOWED_VALUE", "PRIVATE_CELL_VALUE", "PRIVATE_REPLACEMENT", "PRIVATE_USER_REASON", job):
        assert secret not in sent
    assert "category" in sent
    workflow.close()


@pytest.mark.parametrize("response", [
    '{"candidate_ids":[0],"guidance":[]}',  # Negative sample has no candidates.
    '{"candidate_ids":[],"value":"102"}',
    '{"candidate_ids":[],"guidance":[{"issue_id":0,"next_step":"confirm_value","value":"102"}]}',
    '{"candidate_ids":[],"guidance":[{"issue_id":999,"next_step":"confirm_value"}]}',
    '{"candidate_ids":[],"guidance":[{"issue_id":0,"next_step":"confirm_date"}]}',
    '{"candidate_ids":[],"guidance":[]}',
    '{}',
    'provider-secret and not JSON',
])
def test_invalid_model_output_is_bounded_and_falls_back_without_values(tmp_path, response):
    fake = AssistantModel([AIMessage(content=response)])
    workflow = Workflow(tmp_path, mode="nebius", model=fake)
    job = workflow.create(NEGATIVE, RULES)
    result = workflow.suggest_corrections(job)
    assert fake.calls == 2
    assert result["source"] == "local" and result["fallback"] is True
    assert result["operations"] == [] and len(result["rows"]) == 3
    assert all(row["new_value"] == "" for row in result["rows"])
    assert "provider-secret" not in json.dumps(result)
    assert "provider-secret" not in json.dumps([m.model_dump() for m in fake.messages[-1]])
    workflow.close()


def test_provider_failure_keeps_manual_scaffold_and_hides_payload(tmp_path):
    fake = AssistantModel([ValueError("SECRET_PROVIDER_PAYLOAD")])
    workflow = Workflow(tmp_path, mode="nebius", model=fake)
    job = workflow.create(NEGATIVE, RULES)
    before = workflow.snapshot(job)
    result = workflow.suggest_corrections(job)
    assert result["fallback"] and len(result["rows"]) == 3
    assert "SECRET_PROVIDER_PAYLOAD" not in json.dumps(result)
    assert workflow.snapshot(job) == before
    workflow.close()


def test_transient_provider_failure_has_bounded_retries(tmp_path, monkeypatch):
    monkeypatch.setattr("dq_agent.reasoning.time.sleep", lambda _seconds: None)
    class ProviderError(Exception):
        status_code = 503
    fake = AssistantModel([ProviderError("PRIVATE_PROVIDER_RESPONSE")])
    workflow = Workflow(tmp_path, mode="nebius", model=fake)
    job = workflow.create(NEGATIVE, RULES)
    result = workflow.suggest_corrections(job)
    assert fake.calls == 3 and result["fallback"]
    assert "PRIVATE_PROVIDER_RESPONSE" not in json.dumps(result)
    workflow.close()


def test_valid_second_attempt_is_used_without_echoing_invalid_output(tmp_path):
    valid = {"candidate_ids": [], "guidance": [
        {"issue_id": 0, "next_step": "confirm_value"},
        {"issue_id": 1, "next_step": "confirm_date"},
        {"issue_id": 2, "next_step": "choose_allowed_value"},
    ]}
    fake = AssistantModel([AIMessage(content="UNTRUSTED_MODEL_CONTENT"), AIMessage(content=json.dumps(valid))])
    workflow = Workflow(tmp_path, mode="nebius", model=fake)
    job = workflow.create(NEGATIVE, RULES)
    result = workflow.suggest_corrections(job)
    assert fake.calls == 2 and result["source"] == "nebius" and not result["fallback"]
    assert "UNTRUSTED_MODEL_CONTENT" not in json.dumps([m.model_dump() for m in fake.messages[1]])
    workflow.close()


def test_local_assistance_does_not_call_model(tmp_path):
    fake = AssistantModel([RuntimeError("Must not be called")])
    workflow = Workflow(tmp_path, model=fake)
    job = workflow.create(NEGATIVE, RULES)
    result = workflow.suggest_corrections(job)
    assert result["source"] == "local" and result["fallback"] is False
    assert fake.calls == 0
    workflow.close()


def test_supported_values_keep_rule_provenance_and_saved_plan_wins(tmp_path):
    workflow = Workflow(tmp_path)
    data = b"customer_id,name,email,signup_date,country\n101,Iris,iris@example.com,02/28/2026,ca\n"
    job = workflow.create(data, RULES)
    manual = {"op": "set", "row": 0, "column": "country", "value": "GB", "reason": "Confirmed by source", "user_supplied": True}
    # Exercise the case where a rule-backed candidate was not included in the saved plan.
    workflow.resume(job, {"action": "revise", "plan": [manual]})
    before = workflow.snapshot(job)
    result = workflow.suggest_corrections(job)
    assert len(result["operations"]) == 1
    date = result["operations"][0]
    assert date["column"] == "signup_date" and date["value"] == "2026-02-28"
    assert date["rule_id"] == "date:signup_date" and date["user_supplied"] is False
    assert result["unresolved_count"] == 0
    assert workflow.snapshot(job) == before
    assert result["binding"]["plan_hash"] == workflow.engine.preview(job, [manual])["plan_hash"]
    workflow.close()


def test_ai_can_select_supported_values_without_seeing_them(tmp_path):
    workflow = Workflow(tmp_path)
    job = workflow.create(b"customer_id,name,email,signup_date,country\n101,Iris,iris@example.com,02/28/2026,ca\n", RULES)
    fake = AssistantModel([AIMessage(content='{"candidate_ids":[0,1],"guidance":[{"issue_id":0,"next_step":"confirm_date"},{"issue_id":1,"next_step":"choose_allowed_value"}]}')])
    result = suggest_corrections(workflow.engine, job, "nebius", [], model=fake)
    assert {op["value"] for op in result["operations"]} == {"2026-02-28", "CA"}
    sent = json.dumps([[m.model_dump() for m in messages] for messages in fake.messages])
    assert "signup_date" not in sent and "02/28/2026" not in sent and '"CA"' not in sent
    workflow.close()


def test_tampered_source_is_rejected_before_model_call(tmp_path):
    fake = AssistantModel()
    workflow = Workflow(tmp_path, mode="nebius", model=fake)
    job = workflow.create(NEGATIVE, RULES)
    (workflow.engine.job_dir(job) / "source.csv").write_bytes(NEGATIVE.replace(b"ZZ", b"US"))
    with pytest.raises(ValueError):
        workflow.suggest_corrections(job)
    assert fake.calls == 0
    workflow.close()


def test_concurrent_revision_discards_stale_suggestions(tmp_path):
    fake = AssistantModel()
    workflow = Workflow(tmp_path, mode="nebius", model=fake)
    job = workflow.create(NEGATIVE, RULES)
    class ChangesReview:
        def invoke(self, _messages):
            workflow.resume(job, {"action": "revise", "plan": []})
            return AIMessage(content='{"candidate_ids":[],"guidance":[]}')
    workflow.model = ChangesReview()
    with pytest.raises(ValueError, match="saved review changed"):
        workflow.suggest_corrections(job)
    workflow.close()


def test_assistance_is_unavailable_after_repair_approval(tmp_path):
    workflow = Workflow(tmp_path)
    job = workflow.create(b"customer_id,name,email,signup_date,country\n101,Iris,iris@example.com,2026-02-28,US\n", RULES)
    pending = workflow.snapshot(job)["pending"]
    workflow.resume(job, {"action": "approve", "binding": pending["binding"]})
    before = workflow.snapshot(job)
    with pytest.raises(ValueError, match="reviewing corrections"):
        workflow.suggest_corrections(job)
    assert workflow.snapshot(job) == before
    workflow.close()
