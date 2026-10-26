import copy
import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from dq_agent.workflow import Workflow


ROOT = Path(__file__).resolve().parents[1]
RULES = json.loads((ROOT / "samples/import_rules.json").read_text())
NEGATIVE = (ROOT / "samples/customers_negative.csv").read_bytes()


class ValueModel:
    def __init__(self, replies=None):
        self.replies = replies or []
        self.messages = []
        self.calls = 0
        self.bound = False
        self.investigation_calls = 0

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
        self.messages.append(copy.deepcopy(messages))
        reply = self.replies[min(self.calls - 1, len(self.replies) - 1)] if self.replies else AIMessage(content="{}")
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            return reply(messages)
        return reply


def make_job(tmp_path, data=NEGATIVE, rules=RULES, mode="nebius"):
    fake = ValueModel()
    workflow = Workflow(tmp_path, mode=mode, model=fake)
    job = workflow.create(data, rules)
    return workflow, job, fake


def answer(request, values):
    return AIMessage(content=json.dumps({"suggestions": [
        {"issue_id": target["issue_id"], "disposition": "suggest" if values.get(target["field"]) is not None else "abstain",
         "value": values.get(target["field"]),
         "rationale": "Possible correction for your review; confirm the intended fact." if values.get(target["field"]) is not None else "Insufficient evidence; confirm from your source."}
        for target in request["targets"]]}))


def job_files(workflow, job):
    return {p.name: p.read_bytes() for p in workflow.engine.job_dir(job).iterdir()}


def test_preview_is_local_and_only_discloses_selected_values_and_rules(tmp_path):
    workflow, job, fake = make_job(tmp_path)
    before, files = workflow.snapshot(job), job_files(workflow, job)
    empty = workflow.preview_value_request(job, [])
    assert empty["payload"] == {"issues": []}
    assert empty["available_fields"] == ["country", "customer_id", "signup_date"]
    request = workflow.preview_value_request(job, ["signup_date"])
    assert request["targets"] == [{"issue_id": 0, "record": 1, "field": "signup_date",
                                   "current_value": "02/30/2026", "issue_types": ["date_format"]}]
    payload = request["payload"]
    assert payload["issues"][0]["rules"] == {"required": True, "unique": False,
                                            "date_format": {"input": "%m/%d/%Y", "output": "%Y-%m-%d"}}
    sent = json.dumps(payload)
    for excluded in ("Iris", "Noah", "example.com", "ZZ", "customer_id", "country", "101", job, "source_hash"):
        assert excluded not in sent
    assert fake.calls == 0
    assert workflow.snapshot(job) == before and job_files(workflow, job) == files
    workflow.close()


@pytest.mark.parametrize("consent", [False, None, 0, 1, "yes"])
def test_network_requires_explicit_consent(tmp_path, consent):
    workflow, job, fake = make_job(tmp_path)
    request = workflow.preview_value_request(job, ["signup_date"])
    with pytest.raises(ValueError, match="explicitly consent"):
        workflow.suggest_values(job, request, consent)
    assert fake.calls == 0
    workflow.close()


@pytest.mark.parametrize("mutation", [
    lambda request: request["payload"]["issues"][0].update(current_value="INJECTED_PRIVATE_DATA"),
    lambda request: request["payload"].update(other_rows="PRIVATE_OTHER_ROWS"),
    lambda request: request["targets"][0].update(record=2),
    lambda request: request["binding"].update(request_hash="changed"),
    lambda request: request.update(omitted_count=999),
    lambda request: request.update(extra="unexpected"),
])
def test_modified_disclosure_cannot_be_sent(tmp_path, mutation):
    workflow, job, fake = make_job(tmp_path)
    request = workflow.preview_value_request(job, ["signup_date"])
    mutation(request)
    with pytest.raises(ValueError, match="stale"):
        workflow.suggest_values(job, request, True)
    assert fake.calls == 0
    workflow.close()


def test_negative_date_hypothesis_is_separate_and_missing_facts_stay_unresolved(tmp_path):
    workflow, job, fake = make_job(tmp_path)
    request = workflow.preview_value_request(job, ["signup_date", "country", "customer_id"])
    # Enforce evidence boundaries even if the provider proposes plausible-looking invented facts.
    fake.replies = [answer(request, {"signup_date": "2026-02-28", "country": "CA", "customer_id": "102"})]
    before, files = workflow.snapshot(job), job_files(workflow, job)
    result = workflow.suggest_values(job, request, True)
    suggestions = {item["field"]: item for item in result["suggestions"]}
    assert result["source"] == "nebius" and not result["fallback"]
    assert suggestions["signup_date"]["value"] == "2026-02-28"
    assert suggestions["signup_date"]["disposition"] == "suggest"
    assert suggestions["signup_date"]["local_validation"] == "passed"
    assert "Unverified" in suggestions["signup_date"]["message"]
    for field in ("country", "customer_id"):
        assert suggestions[field]["disposition"] == "abstain" and suggestions[field]["value"] is None
    assert "operations" not in result and "plan" not in result
    assert fake.calls == 1
    assert json.loads(fake.messages[0][1].content) == request["payload"]
    assert workflow.snapshot(job) == before and job_files(workflow, job) == files
    assert workflow.engine.validate(job)["blocking_count"] == 3
    workflow.close()


@pytest.mark.parametrize("country,value", [("U.S.A.", "US"), ("United Kingdom", "GB")])
def test_semantic_category_hypotheses_can_go_beyond_declared_aliases(tmp_path, country, value):
    data = f"customer_id,name,email,signup_date,country\n101,Iris,iris@example.com,2026-02-28,{country}\n".encode()
    workflow, job, fake = make_job(tmp_path, data)
    request = workflow.preview_value_request(job, ["country"])
    fake.replies = [answer(request, {"country": value})]
    result = workflow.suggest_values(job, request, True)
    assert result["suggestions"][0]["value"] == value
    assert result["suggestions"][0]["local_validation"] == "passed"
    assert not workflow.snapshot(job)["state"]["plan"]
    workflow.close()


@pytest.mark.parametrize("response", [
    "PRIVATE_PROVIDER_TEXT",
    '{}',
    '{"suggestions":[],"extra":"forbidden"}',
    '{"suggestions":[{"issue_id":0,"disposition":"suggest","value":102,"rationale":"numeric"}]}',
    '{"suggestions":[{"issue_id":true,"disposition":"suggest","value":"2026-02-28","rationale":"bool ID"}]}',
    '{"suggestions":[{"issue_id":0,"disposition":"abstain","value":"2026-02-28","rationale":"invalid abstention"}]}',
    '{"suggestions":[{"issue_id":0,"disposition":"suggest","value":"","rationale":"empty"}]}',
    '{"suggestions":[{"issue_id":9,"disposition":"suggest","value":"2026-02-28","rationale":"bad ID"}]}',
    '{"suggestions":[{"issue_id":0,"disposition":"suggest","value":"2026-02-28","rationale":"first"},{"issue_id":0,"disposition":"suggest","value":"2026-02-28","rationale":"repeat"}]}',
])
def test_malformed_output_is_bounded_and_keeps_manual_path(tmp_path, response):
    workflow, job, fake = make_job(tmp_path)
    request = workflow.preview_value_request(job, ["signup_date"])
    fake.replies = [AIMessage(content=response)]
    before = workflow.snapshot(job)
    result = workflow.suggest_values(job, request, True)
    assert fake.calls == 2 and result["fallback"]
    assert result["suggestions"][0]["value"] is None
    assert "PRIVATE_PROVIDER_TEXT" not in json.dumps(result)
    assert "PRIVATE_PROVIDER_TEXT" not in json.dumps([m.model_dump() for m in fake.messages[-1]])
    assert workflow.snapshot(job) == before
    workflow.close()


@pytest.mark.parametrize("value", ["2026-02-30", "02/28/2026", "=HYPERLINK(\"https://example.test\")", "02/30/2026"])
def test_invalid_unsafe_or_unchanged_values_are_not_actionable(tmp_path, value):
    workflow, job, fake = make_job(tmp_path)
    request = workflow.preview_value_request(job, ["signup_date"])
    fake.replies = [answer(request, {"signup_date": value})]
    result = workflow.suggest_values(job, request, True)
    suggestion = result["suggestions"][0]
    assert suggestion["disposition"] == "rejected" and suggestion["value"] is None
    assert suggestion["local_validation"] == "rejected"
    assert fake.calls == 1 and not result["fallback"]
    workflow.close()


def test_invalid_category_is_not_actionable(tmp_path):
    workflow, job, fake = make_job(tmp_path, NEGATIVE.replace(b"ZZ", b"U.S.A."))
    request = workflow.preview_value_request(job, ["country"])
    fake.replies = [answer(request, {"country": "XX"})]
    result = workflow.suggest_values(job, request, True)
    assert result["suggestions"][0]["disposition"] == "rejected"
    workflow.close()


def test_suggestion_cannot_exchange_target_error_for_new_duplicate_error(tmp_path):
    data = b"country\nU.S.A.\nUS\n"
    rules = {"required_columns": ["country"], "unique_columns": [], "date_formats": {},
             "categories": {"country": {"allowed": ["US", "CA"], "aliases": {}}}}
    workflow, job, fake = make_job(tmp_path, data, rules)
    request = workflow.preview_value_request(job, ["country"])
    fake.replies = [answer(request, {"country": "US"})]
    result = workflow.suggest_values(job, request, True)
    assert result["suggestions"][0]["disposition"] == "rejected"
    workflow.close()


def test_provider_failure_does_not_expose_error_or_change_draft(tmp_path):
    workflow, job, fake = make_job(tmp_path)
    request = workflow.preview_value_request(job, ["signup_date"])
    fake.replies = [RuntimeError("PRIVATE_API_ERROR")]
    before = workflow.snapshot(job)
    result = workflow.suggest_values(job, request, True)
    assert result["fallback"] and "PRIVATE_API_ERROR" not in json.dumps(result)
    assert workflow.snapshot(job) == before
    workflow.close()


def test_transient_provider_errors_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr("dq_agent.reasoning.time.sleep", lambda _: None)
    class Transient(Exception):
        status_code = 503
    workflow, job, fake = make_job(tmp_path)
    request = workflow.preview_value_request(job, ["signup_date"])
    fake.replies = [Transient("PRIVATE")]
    result = workflow.suggest_values(job, request, True)
    assert fake.calls == 3 and result["fallback"]
    workflow.close()


def test_tool_call_and_oversized_response_are_rejected(tmp_path):
    workflow, job, fake = make_job(tmp_path)
    request = workflow.preview_value_request(job, ["signup_date"])
    fake.replies = [AIMessage(content="", tool_calls=[{"name": "write_file", "args": {}, "id": "bad"}]),
                    AIMessage(content="x" * 65537)]
    result = workflow.suggest_values(job, request, True)
    assert fake.calls == 2 and result["fallback"]
    workflow.close()


def test_valid_second_response_is_used_without_echoing_the_first(tmp_path):
    workflow, job, fake = make_job(tmp_path)
    request = workflow.preview_value_request(job, ["signup_date"])
    fake.replies = [AIMessage(content="UNTRUSTED_FIRST_RESPONSE"), answer(request, {"signup_date": "2026-02-28"})]
    result = workflow.suggest_values(job, request, True)
    assert fake.calls == 2 and not result["fallback"]
    assert result["suggestions"][0]["value"] == "2026-02-28"
    assert "UNTRUSTED_FIRST_RESPONSE" not in json.dumps([m.model_dump() for m in fake.messages[1]])
    workflow.close()


def test_changed_saved_plan_requires_new_disclosure_and_consent(tmp_path):
    workflow, job, fake = make_job(tmp_path)
    request = workflow.preview_value_request(job, ["signup_date"])
    workflow.resume(job, {"action": "revise", "plan": []})
    with pytest.raises(ValueError, match="stale"):
        workflow.suggest_values(job, request, True)
    assert fake.calls == 0
    workflow.close()


def test_concurrent_revision_discards_returned_suggestion(tmp_path):
    workflow, job, fake = make_job(tmp_path)
    request = workflow.preview_value_request(job, ["signup_date"])
    def changed(_messages):
        workflow.resume(job, {"action": "revise", "plan": []})
        return answer(request, {"signup_date": "2026-02-28"})
    fake.replies = [changed]
    with pytest.raises(ValueError, match="saved review changed"):
        workflow.suggest_values(job, request, True)
    assert fake.calls == 1
    workflow.close()


@pytest.mark.parametrize("during", [False, True])
def test_tampered_source_is_rejected_before_or_after_provider(tmp_path, during):
    workflow, job, fake = make_job(tmp_path)
    request = workflow.preview_value_request(job, ["signup_date"])
    def tamper(_messages=None):
        (workflow.engine.job_dir(job) / "source.csv").write_bytes(NEGATIVE.replace(b"ZZ", b"US"))
        return answer(request, {"signup_date": "2026-02-28"})
    if during:
        fake.replies = [tamper]
    else:
        tamper()
    with pytest.raises(ValueError):
        workflow.suggest_values(job, request, True)
    assert fake.calls == int(during)
    workflow.close()


def test_offline_mode_and_empty_selection_never_call_model(tmp_path):
    workflow, job, fake = make_job(tmp_path, mode="offline")
    request = workflow.preview_value_request(job, ["signup_date"])
    result = workflow.suggest_values(job, request, True)
    assert result["source"] == "local" and "offline" in result["message"]
    with pytest.raises(ValueError, match="Select at least"):
        workflow.suggest_values(job, workflow.preview_value_request(job, []), True)
    assert fake.calls == 0
    workflow.close()


def test_selected_field_uses_saved_manual_value_without_sending_reason(tmp_path):
    workflow, job, fake = make_job(tmp_path)
    workflow.resume(job, {"action": "revise", "plan": [{"op": "set", "row": 0, "column": "signup_date",
                     "value": "02/29/2026", "reason": "PRIVATE_REASON", "user_supplied": True}]})
    request = workflow.preview_value_request(job, ["signup_date"])
    assert request["payload"]["issues"][0]["current_value"] == "02/29/2026"
    assert "PRIVATE_REASON" not in json.dumps(request)
    fake.replies = [answer(request, {"signup_date": "2026-02-28"})]
    result = workflow.suggest_values(job, request, True)
    assert result["suggestions"][0]["local_validation"] == "passed"
    assert workflow.snapshot(job)["state"]["plan"][0]["value"] == "02/29/2026"
    workflow.close()


def test_first_twenty_cell_limit_is_explicit_and_deterministic(tmp_path):
    data = ("country,name\n" + "".join(f"U.S.A.,row{i}\n" for i in range(23))).encode()
    rules = {"required_columns": [], "unique_columns": [], "date_formats": {},
             "categories": {"country": {"allowed": ["US"], "aliases": {}}}}
    workflow, job, fake = make_job(tmp_path, data, rules)
    request = workflow.preview_value_request(job, ["country"])
    assert request["selected_cell_count"] == 23 and request["omitted_count"] == 3
    assert len(request["targets"]) == len(request["payload"]["issues"]) == 20
    assert [t["record"] for t in request["targets"]] == list(range(1, 21))
    assert request == workflow.preview_value_request(job, ["country"])
    assert fake.calls == 0
    workflow.close()


def test_oversized_selected_rules_fail_before_any_model_request(tmp_path):
    rules = {"required_columns": [], "unique_columns": [], "date_formats": {},
             "categories": {"country": {"allowed": ["X" * 33000], "aliases": {}}}}
    workflow, job, fake = make_job(tmp_path, b"country\nU.S.A.\n", rules)
    with pytest.raises(ValueError, match="32 KiB"):
        workflow.preview_value_request(job, ["country"])
    assert fake.calls == 0
    workflow.close()


def test_closed_review_cannot_disclose_or_call_model(tmp_path):
    workflow, job, fake = make_job(tmp_path)
    request = workflow.preview_value_request(job, ["signup_date"])
    workflow.resume(job, {"action": "cancel"})
    with pytest.raises(ValueError, match="only while reviewing"):
        workflow.suggest_values(job, request, True)
    assert fake.calls == 0
    workflow.close()
