"""Exercise rule-aware field controls against the real local review workflow."""

from copy import deepcopy
from datetime import date
import json
from pathlib import Path

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from dq_agent.workflow import Workflow
from dq_agent.assistance import suggest_corrections


ROOT = Path(__file__).resolve().parents[1]
RULES = json.loads((ROOT / "samples/import_rules.json").read_text())
NEGATIVE = (ROOT / "samples/customers_negative.csv").read_bytes()
CONSENT = "Send this preview to Nebius to suggest replacement values."


def _button(screen, label):
    return next(item for item in screen.button if item.label == label)


def _input(screen, label):
    return next(item for item in screen.text_input if item.label == label)


def _checkbox(screen, label):
    return next(item for item in screen.checkbox if item.label == label)


def _select_field(screen, job, field):
    targets = screen.session_state[f"guided-corrections-{job}"]["targets"]
    key = next(key for key, value in targets.items() if value["field"] == field)
    next(item for item in screen.selectbox if item.label == "Choose a field to fix").set_value(key).run()
    assert not screen.exception


def _reason(screen, text="Checked the synthetic source record"):
    _input(screen, "Why is this correct?").set_value(text).run()


def _count(screen):
    return int(next(item for item in screen.metric if item.label == "Blocking issues after this proposal").value)


def _open():
    screen = AppTest.from_file(str(ROOT / "app.py"))
    screen.query_params["view"] = "workspace"
    screen.run(timeout=20)
    _button(screen, "Continue review").click().run(timeout=20)
    assert not screen.exception
    return screen


@pytest.fixture
def local_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("DQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DQ_PROVIDER", "offline")
    monkeypatch.setenv("DQ_LANGSMITH_TRACING", "false")

    def no_network(*args, **kwargs):
        raise AssertionError("Guided UI tests never contact a real provider")

    for module in ("reasoning", "assistance", "value_suggestions"):
        monkeypatch.setattr(f"dq_agent.{module}.make_model", no_network)


def test_negative_fields_calendar_categories_and_text_reach_both_approval_gates(tmp_path, local_environment):
    service = Workflow(tmp_path)
    job = service.create(NEGATIVE, RULES, name="Guided negative sample")
    before = service.snapshot(job)
    try:
        screen = _open()
        assert _count(screen) == 3
        _select_field(screen, job, "signup_date")
        assert screen.date_input[0].value is None
        assert screen.date_input[0].min == date.min
        assert screen.date_input[0].max == date.max
        assert _button(screen, "Add correction to draft").disabled
        screen.date_input[0].set_value(date(2026, 2, 28)).run()
        assert _button(screen, "Add correction to draft").disabled  # A reason is required.
        assert any(item.value == "2026-02-28" for item in screen.text)
        assert _button(screen, "Submit revised plan for review").disabled
        _reason(screen)
        _button(screen, "Add correction to draft").click().run()
        assert not screen.exception and _count(screen) == 2
        assert "in draft" in next(item for item in screen.selectbox if item.label == "Choose a field to fix").options[1]
        _select_field(screen, job, "country")
        choices = next(item for item in screen.selectbox if item.label == "New value")
        assert choices.value is None
        assert choices.options == RULES["categories"]["country"]["allowed"]
        choices.set_value("CA").run()
        _reason(screen)
        _button(screen, "Add correction to draft").click().run()
        assert _count(screen) == 1
        _select_field(screen, job, "customer_id")
        assert _input(screen, "New value").value == ""
        assert any("unique across" in item.value for item in screen.caption)
        _input(screen, "New value").set_value("00102").run()
        _reason(screen)
        _button(screen, "Add correction to draft").click().run()
        assert _count(screen) == 0
        assert service.snapshot(job) == before
        assert not (service.engine.job_dir(job) / "stage.json").exists()
        _button(screen, "Submit revised plan for review").click().run(timeout=20)
        assert not screen.exception
        snapshot = service.snapshot(job)
        assert snapshot["pending"]["kind"] == "repair_approval"
        assert all(item["user_supplied"] for item in snapshot["state"]["plan"])
        assert _button(screen, "Approve repairs and validate the copy").disabled
        _checkbox(screen, "I approve this exact plan and writing its changes to a staged copy.").check().run()
        _button(screen, "Approve repairs and validate the copy").click().run(timeout=20)
        assert service.snapshot(job)["pending"]["kind"] == "export_approval"
        assert _button(screen, "Approve export").disabled
        assert not (service.engine.job_dir(job) / "export.json").exists()
        _checkbox(screen, "I approve creating the final CSV, audit report, and validation summary.").check().run()
        _button(screen, "Approve export").click().run(timeout=20)
        assert service.snapshot(job)["state"]["status"] == "complete"
        assert service.engine.read_frame(job, staged=True).iloc[1]["customer_id"] == "00102"
        assert service.engine.read_frame(job).iloc[0]["signup_date"] == "02/30/2026"
    finally:
        service.close()


@pytest.mark.parametrize("selected", [date(1901, 1, 5), date(2200, 12, 31)])
def test_calendar_uses_arbitrary_field_rules_and_declared_output(tmp_path, local_environment, selected):
    service = Workflow(tmp_path)
    rules = {"required_columns": ["opened"], "date_formats": {"opened": {"input": "%Y-%m-%d", "output": "%d/%m/%Y"}}}
    job = service.create(b"opened\nnot-a-date\n", rules, name="Calendar output rule")
    try:
        screen = _open()
        assert screen.date_input[0].value is None
        screen.date_input[0].set_value(selected).run()
        expected = selected.strftime("%d/%m/%Y")
        assert any(item.value == expected for item in screen.text)
        _reason(screen)
        _button(screen, "Add correction to draft").click().run()
        assert not screen.exception and _count(screen) == 0
        assert screen.session_state[f"assisted-draft-{job}"]["rows"][0]["new_value"] == expected
    finally:
        service.close()


def test_unadded_values_survive_target_theme_and_workspace_navigation(tmp_path, local_environment):
    service = Workflow(tmp_path)
    job = service.create(NEGATIVE, RULES, name="Preserve unadded corrections")
    before = service.snapshot(job)
    try:
        screen = _open()
        _select_field(screen, job, "signup_date")
        screen.date_input[0].set_value(date(2026, 3, 2)).run()
        _reason(screen, "Verified on the form")
        _select_field(screen, job, "country")
        next(item for item in screen.selectbox if item.label == "New value").set_value("GB").run()
        screen.segmented_control[0].set_value("Light").run()
        _button(screen, "Back to workspace").click().run()
        _button(screen, "Continue review").click().run()
        assert not screen.exception
        assert next(item for item in screen.selectbox if item.label == "New value").value == "GB"
        assert _button(screen, "Submit revised plan for review").disabled
        assert _button(screen, "Prepare AI-assisted draft").disabled
        _select_field(screen, job, "signup_date")
        assert screen.date_input[0].value == date(2026, 3, 2)
        assert _input(screen, "Why is this correct?").value == "Verified on the form"
        _button(screen, "Add correction to draft").click().run()
        assert _count(screen) == 2
        assert _button(screen, "Submit revised plan for review").disabled  # Country still pending.
        _select_field(screen, job, "country")
        _button(screen, "Discard unadded changes").click().run()
        assert next(item for item in screen.selectbox if item.label == "New value").value is None
        assert not _button(screen, "Submit revised plan for review").disabled
        _button(screen, "Back to workspace").click().run()
        _button(screen, "Continue review").click().run()
        _select_field(screen, job, "signup_date")
        assert screen.date_input[0].value == date(2026, 3, 2)
        assert _count(screen) == 2
        assert service.snapshot(job) == before
    finally:
        service.close()


def test_remove_and_readd_reinitializes_controls_without_old_values(tmp_path, local_environment):
    service = Workflow(tmp_path)
    job = service.create(NEGATIVE, RULES, name="Remove guided correction")
    try:
        screen = _open()
        _select_field(screen, job, "signup_date")
        screen.date_input[0].set_value(date(2026, 2, 28)).run()
        _reason(screen)
        _button(screen, "Add correction to draft").click().run()
        assert screen.date_input[0].value == date(2026, 2, 28)
        _button(screen, "Remove draft correction").click().run()
        assert not screen.exception
        assert screen.date_input[0].value is None
        assert _input(screen, "Why is this correct?").value == ""
        assert _button(screen, "Add correction to draft").disabled
        assert _count(screen) == 3
        screen.date_input[0].set_value(date(2026, 3, 1)).run()
        _reason(screen, "New confirmed value")
        _button(screen, "Add correction to draft").click().run()
        assert screen.session_state[f"assisted-draft-{job}"]["rows"][0]["new_value"] == "2026-03-01"
    finally:
        service.close()


class FailedInvestigation:
    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        raise RuntimeError("Synthetic provider failure")


def test_ai_suggestions_edit_in_guided_form_and_dirty_input_invalidates_permission(tmp_path, monkeypatch, local_environment):
    service = Workflow(tmp_path, mode="nebius", model=FailedInvestigation())
    rules = {"required_columns": ["signup_date"], "date_formats": {"signup_date": {"input": "%m/%d/%Y", "output": "%Y-%m-%d"}}}
    job = service.create(b"signup_date\n02/30/2026\n", rules, name="Guided AI review")
    service.continue_manually(job)
    before = service.snapshot(job)
    calls = []

    def suggest(self, job_id, request, consent):
        calls.append(deepcopy(request))
        target = request["targets"][0]
        return {"source": "nebius", "fallback": False, "message": "Review this candidate.", "binding": request["binding"],
                "suggestions": [{**target, "disposition": "suggest", "value": "2026-02-28", "rationale": "A possible date, please verify.",
                                 "local_validation": "passed", "message": "Unverified candidate"}]}

    monkeypatch.setattr(Workflow, "suggest_values", suggest)
    monkeypatch.setattr(Workflow, "suggest_corrections", lambda self, job_id: suggest_corrections(
        self.engine, job_id, "offline", self.snapshot(job_id)["state"].get("plan", [])))
    try:
        screen = _open()
        _checkbox(screen, CONSENT).check().run()
        screen.date_input[0].set_value(date(2026, 3, 1)).run()
        assert not _checkbox(screen, CONSENT).value
        assert _button(screen, "Prepare AI-assisted draft").disabled
        _button(screen, "Discard unadded changes").click().run()
        assert not _checkbox(screen, CONSENT).value
        _checkbox(screen, CONSENT).check().run()
        _button(screen, "Prepare AI-assisted draft").click().run(timeout=20)
        assert len(calls) == 1
        screen.date_input[0].set_value(date(2026, 3, 2)).run()
        assert _button(screen, "Add available suggestions to draft").disabled
        _button(screen, "Discard unadded changes").click().run()
        _button(screen, "Add available suggestions to draft").click().run()
        assert not screen.exception
        assert screen.date_input[0].value == date(2026, 2, 28)
        assert _input(screen, "Why is this correct?").value.startswith("User accepted Nebius")
        screen.date_input[0].set_value(date(2026, 3, 1)).run()
        _reason(screen, "I checked the actual synthetic date")
        _button(screen, "Update correction in draft").click().run()
        assert screen.session_state[f"assisted-draft-{job}"]["rows"][0]["new_value"] == "2026-03-01"
        assert service.snapshot(job) == before and len(calls) == 1
    finally:
        service.close()


def test_optional_blank_is_explicit_and_unique_id_still_checked(tmp_path, local_environment):
    service = Workflow(tmp_path)
    rules = {"required_columns": ["id"], "unique_columns": ["id"], "categories": {"region": {"allowed": ["A", "B"]}}}
    job = service.create(b"id,region\n01,Z\n01,A\n", rules, name="Optional field corrections")
    try:
        screen = _open()
        _select_field(screen, job, "region")
        assert next(item for item in screen.selectbox if item.label == "New value").value is None
        _reason(screen)
        assert _button(screen, "Add correction to draft").disabled
        _checkbox(screen, "Leave this optional field blank").check().run()
        _button(screen, "Add correction to draft").click().run()
        assert screen.session_state[f"assisted-draft-{job}"]["rows"][0]["new_value"] == ""
        assert _count(screen) == 2  # Both duplicate IDs remain.
        _select_field(screen, job, "id")
        assert _input(screen, "New value").value == "01"
        assert not any(item.label == "Leave this optional field blank" for item in screen.checkbox)
        _input(screen, "New value").set_value("02").run()
        _reason(screen)
        _button(screen, "Add correction to draft").click().run()
        assert _count(screen) == 0
    finally:
        service.close()


def test_advanced_edits_survive_workspace_navigation(tmp_path, monkeypatch, local_environment):
    service = Workflow(tmp_path)
    job = service.create(NEGATIVE, RULES, name="Preserve advanced draft")
    original_editor = st.data_editor
    edit_once = {"enabled": False}

    def editor(data, *args, **kwargs):
        displayed = original_editor(data, *args, **kwargs)
        if edit_once["enabled"] and str(kwargs.get("key", "")).startswith(f"plan-{job}-"):
            edit_once["enabled"] = False
            return pd.DataFrame([{"record": 2, "action": "set", "field": "customer_id", "new_value": "00102",
                                  "reason": "Checked source", "_needs_input": False}])
        return displayed

    monkeypatch.setattr(st, "data_editor", editor)
    try:
        screen = _open()
        edit_once["enabled"] = True
        screen.run()
        assert _count(screen) == 2
        _button(screen, "Back to workspace").click().run()
        _button(screen, "Continue review").click().run()
        assert not screen.exception and _count(screen) == 2
        _select_field(screen, job, "customer_id")
        assert _input(screen, "New value").value == "00102"
        screen.segmented_control[0].set_value("Light").run()
        assert _count(screen) == 2
    finally:
        service.close()


def test_unadded_changes_block_already_consented_saved_plan_approval(tmp_path, local_environment):
    service = Workflow(tmp_path)
    rules = {"required_columns": ["id"], "unique_columns": ["id"]}
    job = service.create(b"id\n01\n01\n", rules, name="Guard pending form before approval")
    snapshot = service.snapshot(job)
    # Use an explicit human repair so this saved review has a valid field target.
    service.resume(job, {"action": "revise", "plan": [
        {"op": "set", "row": 1, "column": "id", "value": "02", "reason": "Confirmed source ID", "user_supplied": True},
    ]})
    try:
        screen = _open()
        _checkbox(screen, "I approve this exact plan and writing its changes to a staged copy.").check().run()
        assert not _button(screen, "Approve repairs and validate the copy").disabled
        _input(screen, "New value").set_value("003").run()
        assert _button(screen, "Approve repairs and validate the copy").disabled
        assert _checkbox(screen, "I approve this exact plan and writing its changes to a staged copy.").disabled
        assert not (service.engine.job_dir(job) / "stage.json").exists()
        _button(screen, "Discard unadded changes").click().run()
        assert not _button(screen, "Approve repairs and validate the copy").disabled
        assert not screen.exception
        assert service.snapshot(job)["pending"]["kind"] == "repair_approval"
    finally:
        service.close()


def test_same_target_advanced_change_preserves_unadded_input_until_discard(tmp_path, monkeypatch, local_environment):
    service = Workflow(tmp_path)
    job = service.create(NEGATIVE, RULES, name="Resolve competing draft edits")
    original_editor = st.data_editor
    inject = {"enabled": False}

    def editor(data, *args, **kwargs):
        displayed = original_editor(data, *args, **kwargs)
        if inject["enabled"] and str(kwargs.get("key", "")).startswith(f"plan-{job}-"):
            return pd.DataFrame([{"record": 1, "action": "set", "field": "signup_date", "new_value": "2026-03-03",
                                  "reason": "Advanced edit", "_needs_input": False}])
        return displayed

    monkeypatch.setattr(st, "data_editor", editor)
    try:
        screen = _open()
        _select_field(screen, job, "signup_date")
        screen.date_input[0].set_value(date(2026, 2, 28)).run()
        _reason(screen, "Unadded confirmed date")
        inject["enabled"] = True
        screen.run()
        assert screen.date_input[0].value == date(2026, 2, 28)
        assert any("changed elsewhere" in item.value for item in screen.warning)
        assert _button(screen, "Update correction in draft").disabled
        _button(screen, "Discard unadded changes").click().run()
        assert screen.date_input[0].value == date(2026, 3, 3)
        assert _input(screen, "Why is this correct?").value == "Advanced edit"
        assert not screen.exception
    finally:
        service.close()


def test_removed_ai_placeholder_stays_removed_after_navigation_and_reprepare(tmp_path, monkeypatch, local_environment):
    service = Workflow(tmp_path)
    job = service.create(NEGATIVE, RULES, name="Keep intentional draft deletion")
    original_editor = st.data_editor
    remove_once = {"enabled": False}

    def editor(data, *args, **kwargs):
        displayed = original_editor(data, *args, **kwargs)
        if remove_once["enabled"] and str(kwargs.get("key", "")).startswith(f"plan-{job}-"):
            remove_once["enabled"] = False
            return displayed[displayed["field"] != "signup_date"].reset_index(drop=True)
        return displayed

    monkeypatch.setattr(st, "data_editor", editor)
    try:
        screen = _open()
        _button(screen, "Prepare AI-assisted draft").click().run()
        assert len(screen.session_state[f"assisted-draft-{job}"]["rows"]) == 3
        remove_once["enabled"] = True
        screen.run()
        _button(screen, "Back to workspace").click().run()
        _button(screen, "Continue review").click().run()
        _button(screen, "Prepare AI-assisted draft").click().run()
        assert not screen.exception
        draft = screen.session_state[f"assisted-draft-{job}"]
        assert len(draft["rows"]) == 2
        assert all(row["field"] != "signup_date" for row in draft["rows"])
        assert any(row["field"] == "signup_date" for row in draft["dismissed"])
    finally:
        service.close()


def test_ai_placeholders_keep_progress_visible_and_submission_blocked(tmp_path, local_environment):
    service = Workflow(tmp_path)
    job = service.create(NEGATIVE, RULES, name="Preview completed guided fixes")
    before = service.snapshot(job)
    try:
        screen = _open()
        _button(screen, "Prepare AI-assisted draft").click().run()
        assert _count(screen) == 3
        assert _button(screen, "Submit revised plan for review").disabled
        _select_field(screen, job, "signup_date")
        screen.date_input[0].set_value(date(2026, 2, 28)).run()
        _reason(screen)
        _button(screen, "Update correction in draft").click().run()
        assert not screen.exception
        assert _count(screen) == 2
        assert _button(screen, "Submit revised plan for review").disabled
        assert any("completed draft corrections only" in item.value for item in screen.caption)
        assert service.snapshot(job) == before
    finally:
        service.close()
