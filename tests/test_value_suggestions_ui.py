"""One draft action prepares private guidance and optional unverified values."""

from copy import deepcopy
import json
from pathlib import Path

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import app as ui
from dq_agent.assistance import suggest_corrections as local_draft
from dq_agent.workflow import Workflow


ROOT = Path(__file__).resolve().parents[1]
RULES = json.loads((ROOT / "samples/import_rules.json").read_text())
NEGATIVE = (ROOT / "samples/customers_negative.csv").read_bytes()
DATE_DATA = b"signup_date\n02/30/2026\n"
DATE_RULES = {"date_formats": {"signup_date": {"input": "%m/%d/%Y", "output": "%Y-%m-%d"}}}
CONSENT = "Send this preview to Nebius to suggest replacement values."
PREPARE = "Prepare AI-assisted draft"


def _button(screen, label):
    return next(button for button in screen.button if button.label == label)


def _checkbox(screen, label):
    return next(box for box in screen.checkbox if box.label == label)


def _open_job():
    screen = AppTest.from_file(str(ROOT / "app.py"))
    screen.query_params["view"] = "workspace"
    screen.run(timeout=20)
    _button(screen, "Continue review").click().run(timeout=20)
    assert not screen.exception
    return screen


class FailedInvestigation:
    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        raise RuntimeError("Synthetic investigation failure; no network")


@pytest.fixture
def local_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("DQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DQ_PROVIDER", "offline")
    monkeypatch.setenv("DQ_LANGSMITH_TRACING", "false")

    def no_network(*args, **kwargs):
        raise AssertionError("This UI test must never call a real provider")

    monkeypatch.setattr("dq_agent.reasoning.make_model", no_network)
    monkeypatch.setattr("dq_agent.assistance.make_model", no_network)
    monkeypatch.setattr("dq_agent.value_suggestions.make_model", no_network)


def _live_review(tmp_path, *, date_only=False):
    service = Workflow(tmp_path, mode="nebius", model=FailedInvestigation())
    job = service.create(DATE_DATA if date_only else NEGATIVE, DATE_RULES if date_only else RULES,
                         name="Synthetic value review")
    assert service.snapshot(job)["state"]["status"] == "blocked"
    service.continue_manually(job)
    return service, job


def _suggestion(record=1, field="signup_date", issue_id=0):
    return {"issue_id": issue_id, "record": record, "field": field, "current_value": "02/30/2026",
            "disposition": "suggest", "value": "2026-02-28",
            "rationale": "A month-end correction is plausible; confirm the actual date.",
            "local_validation": "passed", "message": "Unverified candidate"}


class _RequestLog(list):
    def __init__(self):
        super().__init__()
        self.private_calls = []


def _stub_requests(monkeypatch, *, fail=False, rejected=False, private_failure=False):
    calls = _RequestLog()

    def prepare(self, job_id):
        calls.private_calls.append(job_id)
        if private_failure:
            raise RuntimeError("Do not display raw private provider details")
        pending = self.snapshot(job_id)["pending"]
        return local_draft(self.engine, job_id, "offline", pending["plan"])

    def suggest(self, job_id, request, consent):
        calls.append({"job_id": job_id, "request": deepcopy(request), "consent": consent})
        if fail:
            raise RuntimeError("Do not display raw provider details")
        suggestions = []
        for target in request["targets"]:
            suggestion = _suggestion(target["record"], target["field"], target["issue_id"])
            suggestion["current_value"] = target["current_value"]
            if target["field"] != "signup_date":
                suggestion.update(disposition="abstain", value=None, local_validation="not_applicable",
                                  rationale="The selected value and rules do not identify the customer's real fact.",
                                  message="Cannot infer this value from the shared information.")
            elif rejected:
                suggestion.update(disposition="rejected", value=None, local_validation="rejected",
                                  rationale="The candidate did not pass local checks.", message="Enter a correction manually.")
            suggestions.append(suggestion)
        return {"source": "nebius", "fallback": False, "message": "Review these unverified suggestions.",
                "binding": request["binding"], "suggestions": suggestions}

    monkeypatch.setattr(Workflow, "suggest_values", suggest)
    monkeypatch.setattr(Workflow, "suggest_corrections", prepare)
    return calls


def test_explicit_acceptance_creates_human_proposal_without_claiming_verified_fact():
    blank = {"record": 1, "action": "set", "field": "signup_date", "new_value": "", "reason": "", "_needs_input": True}
    current = [blank]
    rows = ui._accept_value_suggestion(current, current, [], _suggestion(), "Nebius", ui._editor_fingerprint(current))
    assert current[0]["new_value"] == ""  # Original draft was not mutated.
    operation = ui._edited_plan(rows, [])[0]
    assert operation["value"] == "2026-02-28"
    assert operation["user_supplied"] is True
    assert operation["reason"].startswith("User accepted Nebius AI suggestion:")
    assert "confirmed" not in operation["reason"].lower()
    assert "rule_id" not in operation


def test_acceptance_preserves_filled_edits_removed_rows_and_changed_editor():
    blank = {"record": 1, "action": "set", "field": "signup_date", "new_value": "", "reason": "", "_needs_input": True}
    filled = {**blank, "new_value": "2026-03-02", "reason": "Checked source"}
    with pytest.raises(ValueError, match="existing edit takes priority"):
        ui._accept_value_suggestion([filled], [blank], [], _suggestion(), "Nebius", ui._editor_fingerprint([filled]))
    with pytest.raises(ValueError, match="removed from your draft"):
        ui._accept_value_suggestion([], [blank], [], _suggestion(), "Nebius", ui._editor_fingerprint([]))
    with pytest.raises(ValueError, match="editor changed"):
        ui._accept_value_suggestion([filled], [blank], [], _suggestion(), "Nebius", ui._editor_fingerprint([blank]))
    with pytest.raises(ValueError, match="not available"):
        ui._accept_value_suggestion([], [], [], {**_suggestion(), "local_validation": "rejected"}, "Nebius", ui._editor_fingerprint([]))


def test_all_affected_fields_default_to_compact_table_with_fresh_permission(tmp_path, monkeypatch, local_environment):
    service, job_id = _live_review(tmp_path)
    calls = _stub_requests(monkeypatch)
    before = service.snapshot(job_id)
    try:
        screen = _open_job()
        assert not screen.multiselect
        assert calls == []
        assert calls.private_calls == []
        assert sum(button.label == PREPARE for button in screen.button) == 1
        assert not any(button.label == "Request replacement suggestions" for button in screen.button)
        assert not screen.exception
        assert not _checkbox(screen, CONSENT).value
        assert _button(screen, PREPARE).disabled
        assert calls == []
        _checkbox(screen, CONSENT).check().run()
        assert calls == []
        _button(screen, PREPARE).click().run(timeout=20)
        assert not screen.exception
        assert len(calls) == 1 and calls[0]["consent"] is True
        assert calls.private_calls == [job_id]
        assert not _checkbox(screen, CONSENT).value
        assert _button(screen, PREPARE).disabled
        sent = calls[0]["request"]["payload"]
        assert {issue["field"] for issue in sent["issues"]} == {"signup_date", "country", "customer_id"}
        assert "email" not in json.dumps(sent) and "name" not in json.dumps(sent)
        assert service.snapshot(job_id) == before
        table = next(item.value for item in screen.dataframe if "Proposed value" in item.value.columns)
        assert list(table["Field"]) == ["country", "signup_date", "customer_id"]
        assert list(table["Status"]) == ["Needs your input", "Unverified suggestion", "Needs your input"]
        assert table.loc[1, "Proposed value"] == "2026-02-28"
        assert "02/30/2026" in table["Current value"].tolist()
        assert all(row["new_value"] == "" for row in screen.session_state[f"assisted-draft-{job_id}"]["rows"])
        assert not any(item.label == "Advanced repair table" for item in screen.expander)
        draft = screen.session_state[f"assisted-draft-{job_id}"]
        value_session = screen.session_state[f"value-suggestions-{job_id}"]
        assert len(draft["rows"]) == 3
        assert value_session["expected_editor"] == ui._editor_fingerprint(draft["rows"])
        assert not _button(screen, "Add available suggestions to draft").disabled
        screen.run()
        screen.segmented_control[0].set_value("Light").run()
        assert len(calls) == 1
        assert calls.private_calls == [job_id]
        _checkbox(screen, CONSENT).check().run()
        _button(screen, PREPARE).click().run(timeout=20)
        assert len(calls) == 2 and not _checkbox(screen, CONSENT).value
        assert calls.private_calls == [job_id, job_id]
        assert service.snapshot(job_id) == before
    finally:
        service.close()


def test_accepted_suggestion_is_only_a_draft_until_submission_and_both_approvals(tmp_path, monkeypatch, local_environment):
    service, job_id = _live_review(tmp_path, date_only=True)
    calls = _stub_requests(monkeypatch)
    before = service.snapshot(job_id)
    try:
        screen = _open_job()
        _checkbox(screen, CONSENT).check().run()
        _button(screen, PREPARE).click().run(timeout=20)
        assert service.snapshot(job_id) == before
        _button(screen, "Add available suggestions to draft").click().run(timeout=20)
        assert not screen.exception
        assert len(calls) == 1
        assert service.snapshot(job_id) == before
        draft = screen.session_state[f"assisted-draft-{job_id}"]
        assert draft["rows"][0]["new_value"] == "2026-02-28"
        assert draft["rows"][0]["reason"].startswith("User accepted Nebius AI suggestion:")
        assert draft["operations"] == []
        assert not (service.engine.job_dir(job_id) / "stage.json").exists()
        _button(screen, "Submit revised plan for review").click().run(timeout=20)
        assert not screen.exception
        saved = service.snapshot(job_id)
        assert saved["pending"]["kind"] == "repair_approval"
        assert saved["state"]["plan"][0]["user_supplied"] is True
        assert _button(screen, "Approve repairs and validate the copy").disabled
        _checkbox(screen, "I approve this exact plan and writing its changes to a staged copy.").check().run()
        _button(screen, "Approve repairs and validate the copy").click().run(timeout=20)
        assert not screen.exception
        assert service.snapshot(job_id)["pending"]["kind"] == "export_approval"
        assert _button(screen, "Approve export").disabled
        assert not (service.engine.job_dir(job_id) / "export.json").exists()
        _checkbox(screen, "I approve creating the final CSV, audit report, and validation summary.").check().run()
        _button(screen, "Approve export").click().run(timeout=20)
        assert not screen.exception
        assert service.snapshot(job_id)["state"]["status"] == "complete"
        assert service.engine.read_frame(job_id)["signup_date"].iloc[0] == "02/30/2026"
    finally:
        service.close()


def test_all_fields_still_require_permission_and_manual_path_is_available(tmp_path, monkeypatch, local_environment):
    service, job_id = _live_review(tmp_path)
    calls = _stub_requests(monkeypatch)
    before = service.snapshot(job_id)
    try:
        screen = _open_job()
        assert _button(screen, PREPARE).disabled
        assert not _checkbox(screen, CONSENT).value
        assert not screen.multiselect
        assert any(item.value == "**Final corrections — editable draft**" for item in screen.markdown)
        assert _button(screen, "Add correction to draft")
        screen.run()
        assert calls.private_calls == [] and calls == []
        assert service.snapshot(job_id) == before
    finally:
        service.close()


def test_private_helper_failure_consumes_permission_and_keeps_manual_controls(tmp_path, monkeypatch, local_environment):
    service, job_id = _live_review(tmp_path)
    calls = _stub_requests(monkeypatch, private_failure=True)
    before = service.snapshot(job_id)
    try:
        screen = _open_job()
        _checkbox(screen, CONSENT).check().run()
        _button(screen, PREPARE).click().run(timeout=20)
        assert not screen.exception
        assert calls.private_calls == [job_id] and calls == []
        assert not _checkbox(screen, CONSENT).value
        assert _button(screen, PREPARE).disabled
        assert any("AI assistance did not finish" in item.value for item in screen.warning)
        assert not any("raw private provider" in item.value for item in screen.warning)
        field_picker = next(item for item in screen.selectbox if item.label == "Choose a field to fix")
        assert not field_picker.disabled
        assert _button(screen, "Add correction to draft")
        assert service.snapshot(job_id) == before
        assert not (service.engine.job_dir(job_id) / "stage.json").exists()
        screen.run()
        assert calls.private_calls == [job_id] and calls == []
    finally:
        service.close()


def test_rule_repairs_and_hypotheses_share_one_action_without_stale_editor_conflict(tmp_path, monkeypatch, local_environment):
    service = Workflow(tmp_path, mode="nebius", model=FailedInvestigation())
    source = b"signup_date,country\n02/30/2026,ca\n"
    rules = {**DATE_RULES, "categories": RULES["categories"]}
    job_id = service.create(source, rules, name="Mixed rule and suggested correction")
    service.continue_manually(job_id)
    before = service.snapshot(job_id)
    calls = _stub_requests(monkeypatch)
    try:
        screen = _open_job()
        _checkbox(screen, CONSENT).check().run()
        _button(screen, PREPARE).click().run(timeout=20)
        assert not screen.exception
        assert calls.private_calls == [job_id] and len(calls) == 1
        draft = screen.session_state[f"assisted-draft-{job_id}"]
        assert len(draft["operations"]) == 1
        assert draft["operations"][0]["value"] == "CA"
        assert draft["operations"][0]["rule_id"] == "category:country"
        session = screen.session_state[f"value-suggestions-{job_id}"]
        assert session["expected_editor"] == ui._editor_fingerprint(draft["rows"])
        assert not _button(screen, "Add available suggestions to draft").disabled
        _button(screen, "Add available suggestions to draft").click().run(timeout=20)
        assert not screen.exception
        draft = screen.session_state[f"assisted-draft-{job_id}"]
        plan = ui._edited_plan(draft["rows"], draft["operations"])
        date = next(operation for operation in plan if operation["column"] == "signup_date")
        category = next(operation for operation in plan if operation["column"] == "country")
        assert date["value"] == "2026-02-28" and date["user_supplied"] is True
        assert category["value"] == "CA" and category["user_supplied"] is False
        assert category["rule_id"] == "category:country"
        assert service.snapshot(job_id) == before
        assert not (service.engine.job_dir(job_id) / "stage.json").exists()
    finally:
        service.close()


def test_later_editor_change_disables_suggestion_without_overwriting_the_edit(tmp_path, monkeypatch, local_environment):
    service, job_id = _live_review(tmp_path, date_only=True)
    calls = _stub_requests(monkeypatch)
    original_editor = st.data_editor
    edit = {"enabled": False}

    def editor(data, *args, **kwargs):
        displayed = original_editor(data, *args, **kwargs)
        if edit["enabled"] and str(kwargs.get("key", "")).startswith(f"plan-{job_id}-"):
            return pd.DataFrame([{"record": 1, "action": "set", "field": "signup_date", "new_value": "2026-03-02",
                                  "reason": "Confirmed from synthetic source", "_needs_input": False}])
        return displayed

    monkeypatch.setattr(st, "data_editor", editor)
    try:
        screen = _open_job()
        _checkbox(screen, CONSENT).check().run()
        _button(screen, PREPARE).click().run(timeout=20)
        edit["enabled"] = True
        screen.run()
        assert not screen.exception
        assert _button(screen, "Add available suggestions to draft").disabled
        assert not _checkbox(screen, CONSENT).value
        assert any("editor changed" in item.value for item in screen.warning)
        assert len(calls) == 1
        _button(screen, "Submit revised plan for review").click().run(timeout=20)
        assert service.snapshot(job_id)["state"]["plan"][0]["value"] == "2026-03-02"
    finally:
        service.close()


@pytest.mark.parametrize("failure", ["exception", "rejected"])
def test_failure_or_rejected_value_keeps_manual_path_available(tmp_path, monkeypatch, local_environment, failure):
    service, job_id = _live_review(tmp_path, date_only=True)
    calls = _stub_requests(monkeypatch, fail=failure == "exception", rejected=failure == "rejected")
    try:
        screen = _open_job()
        _checkbox(screen, CONSENT).check().run()
        _button(screen, PREPARE).click().run(timeout=20)
        assert not screen.exception
        assert len(calls) == 1
        assert not _checkbox(screen, CONSENT).value
        assert not any(button.label == "Add available suggestions to draft" for button in screen.button)
        assert not any("Do not display raw provider" in item.value for item in screen.warning)
        assert _button(screen, "Submit revised plan for review")
        assert service.snapshot(job_id)["pending"]["kind"] == "clarification"
        assert not (service.engine.job_dir(job_id) / "stage.json").exists()
    finally:
        service.close()


def test_batch_adds_multiple_candidates_once_without_saving_the_plan(tmp_path, monkeypatch, local_environment):
    service = Workflow(tmp_path, mode='nebius', model=FailedInvestigation())
    job_id = service.create(b'signup_date\n02/30/2026\n02/31/2026\n', DATE_RULES, name='Two date corrections')
    service.continue_manually(job_id)
    calls = _stub_requests(monkeypatch)
    before = service.snapshot(job_id)
    try:
        screen = _open_job()
        _checkbox(screen, CONSENT).check().run()
        _button(screen, PREPARE).click().run(timeout=20)
        table = next(item.value for item in screen.dataframe if 'Proposed value' in item.value.columns)
        assert list(table['Record']) == [1, 2]
        assert list(table['Proposed value']) == ['2026-02-28', '2026-02-28']
        _button(screen, 'Add available suggestions to draft').click().run()
        assert not screen.exception
        rows = screen.session_state[f'assisted-draft-{job_id}']['rows']
        assert len(rows) == 2 and all(row['new_value'] == '2026-02-28' for row in rows)
        assert _button(screen, 'Add available suggestions to draft').disabled
        assert service.snapshot(job_id) == before
        assert len(calls) == 1
    finally:
        service.close()
