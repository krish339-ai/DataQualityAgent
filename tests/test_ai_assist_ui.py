"""Exercise assistance drafts without network calls or guessing customer facts."""

from copy import deepcopy
import json
from pathlib import Path

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import app as ui
from dq_agent.workflow import Workflow


ROOT = Path(__file__).resolve().parents[1]
RULES = json.loads((ROOT / "samples/import_rules.json").read_text())
NEGATIVE = (ROOT / "samples/customers_negative.csv").read_bytes()


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


@pytest.fixture
def local_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("DQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DQ_PROVIDER", "offline")
    monkeypatch.setenv("DQ_LANGSMITH_TRACING", "false")

    def no_network(*args, **kwargs):
        raise AssertionError("UI tests must never create a live provider client")

    monkeypatch.setattr("dq_agent.reasoning.make_model", no_network)
    monkeypatch.setattr("dq_agent.assistance.make_model", no_network)
    monkeypatch.setattr("dq_agent.value_suggestions.make_model", no_network)
    yield


def _operation(row=0, column="country", value="US"):
    return {"op": "set", "row": row, "column": column, "value": value,
            "reason": "Explicit category alias", "rule_id": "category:country", "user_supplied": False}


def _blank(record=2, field="customer_id"):
    return {"record": record, "action": "set", "field": field, "new_value": "", "reason": ""}


def test_merge_retains_unsaved_values_deletions_and_row_drop_conflicts():
    operation = _operation()
    incoming = {"operations": [operation], "rows": [*ui._plan_rows([operation]), _blank()]}
    current = [{"record": 1, "action": "set", "field": "country", "new_value": "CA", "reason": "Verified Canadian address"}]
    baseline = [*ui._plan_rows([operation]), _blank()]
    rows, accepted, dismissed = ui._merge_assisted_rows(current, baseline, incoming)
    assert rows == current  # A deleted prompt must not reappear.
    assert accepted == []
    assert dismissed == [_blank()]
    rows, accepted, _ = ui._merge_assisted_rows(rows, rows, incoming, dismissed)
    assert rows == current and accepted == []
    drop = {"record": 1, "action": "drop", "field": "", "new_value": "", "reason": "Confirmed obsolete record"}
    rows, accepted, _ = ui._merge_assisted_rows([drop], [], incoming)
    assert rows[0] == drop and accepted == []
    assert rows[1]["_needs_input"] is True
    incoming_drop = {"op": "drop", "row": 0, "reason": "Exact duplicate", "rule_id": "duplicate_row", "user_supplied": False}
    rows, accepted, _ = ui._merge_assisted_rows(current, [], {"operations": [incoming_drop], "rows": ui._plan_rows([incoming_drop])})
    assert rows == current and accepted == []


def test_verified_operations_keep_provenance_but_human_changes_do_not():
    operation = _operation()
    rows, accepted, _ = ui._merge_assisted_rows([], [], {"operations": [operation], "rows": ui._plan_rows([operation])})
    assert accepted == [operation]
    assert ui._edited_plan(rows, accepted) == [operation]
    rows[0]["new_value"] = "CA"
    rows[0]["reason"] = "Checked the source"
    edited = ui._edited_plan(rows, accepted)
    assert edited[0]["user_supplied"] is True
    assert "rule_id" not in edited[0]
    # A backend/model value without a verified deterministic operation is ignored.
    rows, accepted, _ = ui._merge_assisted_rows([], [], {"operations": [], "rows": ui._plan_rows([operation])})
    assert rows == accepted == []


@pytest.mark.parametrize("reason", ["", "I have not supplied the fact yet"])
def test_blank_assisted_value_cannot_be_submitted_as_a_clear(reason):
    row = {**_blank(), "reason": reason, "_needs_input": True}
    assert ui._incomplete_draft_rows([row])[0]["status"] == "Needs your input"
    with pytest.raises(ValueError, match="Blank draft values cannot clear data"):
        ui._edited_plan([row], [])
    row["new_value"] = "102"
    row["reason"] = "Confirmed synthetic source ID"
    assert ui._incomplete_draft_rows([row]) == []
    assert ui._edited_plan([row], [])[0]["user_supplied"] is True
    row.update(action="drop", new_value="", reason="Confirmed obsolete record")
    assert ui._edited_plan([row], [])[0]["op"] == "drop"
    assert ui._edited_plan([], []) == []


def test_missing_marker_does_not_change_existing_manual_blank_clear_behavior():
    row = {"record": 1, "action": "set", "field": "name", "new_value": "", "reason": "Explicitly remove optional name"}
    for marker in (None, float("nan"), pd.NA, False):
        assert ui._edited_plan([{**row, "_needs_input": marker}], [])[0]["value"] == ""


def test_merge_keeps_unfinished_manual_cells_empty_and_unsubmittable():
    manual = {"record": 1, "action": "set", "field": "name", "new_value": None, "reason": None}
    rows, _, _ = ui._merge_assisted_rows([manual], [], {"operations": [], "rows": [_blank()]})
    frame = ui._editor_frame(rows)
    assert frame.loc[0, "new_value"] == frame.loc[0, "reason"] == ""
    assert not frame.loc[0, "_needs_input"]
    assert frame.loc[1, "_needs_input"]
    with pytest.raises(ValueError, match="Explain why"):
        ui._edited_plan(frame.to_dict("records"), [])


def test_button_calls_once_keeps_job_unchanged_and_blanks_block_submission(tmp_path, monkeypatch, local_environment):
    service = Workflow(tmp_path)
    job_id = service.create(NEGATIVE, RULES, name="Assisted negative sample")
    before = service.snapshot(job_id)
    files = {p.name: p.read_bytes() for p in service.engine.job_dir(job_id).iterdir()}
    original = Workflow.suggest_corrections
    calls = []

    def counted(self, job):
        calls.append(job)
        return original(self, job)

    monkeypatch.setattr(Workflow, "suggest_corrections", counted)
    try:
        screen = _open_job()
        assert calls == []
        assert sum(button.label == "Prepare AI-assisted draft" for button in screen.button) == 1
        assert not any(button.label == "Request replacement suggestions" for button in screen.button)
        _button(screen, "Prepare AI-assisted draft").click().run(timeout=20)
        assert not screen.exception
        assert calls == [job_id]
        draft = screen.session_state[f"assisted-draft-{job_id}"]
        assert len(draft["rows"]) == 3
        assert all(row["new_value"] == row["reason"] == "" for row in draft["rows"])
        assert all(row["_needs_input"] for row in draft["rows"])
        assert _button(screen, "Submit revised plan for review").disabled
        table = next(item.value for item in screen.dataframe if "new_value" in item.value.columns)
        assert set(table["field"]) == {"signup_date", "country", "customer_id"}
        assert all(value == "" for value in table["new_value"])
        assert any("Fill the blank New value" in item.value for item in screen.caption)
        screen.segmented_control[0].set_value("Light").run()
        screen.run()
        assert not screen.exception and calls == [job_id]
        assert service.snapshot(job_id) == before
        assert {p.name: p.read_bytes() for p in service.engine.job_dir(job_id).iterdir()} == files
        assert not any(button.label == "Approve repairs and validate the copy" for button in screen.button)
    finally:
        service.close()


def test_editor_edits_survive_assistance_and_both_approvals_remain_explicit(tmp_path, monkeypatch, local_environment):
    """AppTest lacks cell editing; substitute only the editor's returned live data."""
    service = Workflow(tmp_path)
    job_id = service.create(NEGATIVE, RULES, name="Complete assisted review")
    original_editor = st.data_editor
    edits = {"fill": False}

    def editor(data, *args, **kwargs):
        displayed = original_editor(data, *args, **kwargs)
        if not str(kwargs.get("key", "")).startswith(f"plan-{job_id}-"):
            return displayed
        result = displayed.copy()
        if result.empty:
            # This is an unsaved human correction before assistance is requested.
            result = pd.DataFrame([{"record": 1, "action": "set", "field": "signup_date", "new_value": "2026-02-28",
                                    "reason": "Verified synthetic date", "_needs_input": False}])
        if edits["fill"]:
            for index, row in result.iterrows():
                if ui._needs_input(row):
                    result.at[index, "new_value"] = {"country": "US", "customer_id": "102"}[row["field"]]
                    result.at[index, "reason"] = "Verified synthetic source fact"
        return result

    monkeypatch.setattr(st, "data_editor", editor)
    try:
        screen = _open_job()
        _button(screen, "Prepare AI-assisted draft").click().run(timeout=20)
        assert not screen.exception
        draft = screen.session_state[f"assisted-draft-{job_id}"]
        assert len(draft["rows"]) == 3
        retained = next(row for row in draft["rows"] if row["field"] == "signup_date")
        assert retained["new_value"] == "2026-02-28"
        assert retained["reason"] == "Verified synthetic date"
        assert _button(screen, "Submit revised plan for review").disabled
        edits["fill"] = True
        screen.run()
        assert not _button(screen, "Submit revised plan for review").disabled
        assert service.snapshot(job_id)["state"]["plan"] == []
        assert not (service.engine.job_dir(job_id) / "stage.json").exists()
        _button(screen, "Submit revised plan for review").click().run(timeout=20)
        assert not screen.exception
        saved = service.snapshot(job_id)
        assert saved["pending"]["kind"] == "repair_approval"
        assert len(saved["state"]["plan"]) == 3
        assert all(operation["user_supplied"] for operation in saved["state"]["plan"])
        assert all("_needs_input" not in operation for operation in saved["state"]["plan"])
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


def test_partially_typed_editor_row_survives_assistance_as_blank_cells(tmp_path, monkeypatch, local_environment):
    service = Workflow(tmp_path)
    job_id = service.create(NEGATIVE, RULES, name="Partially entered correction")
    original_editor = st.data_editor

    def editor(data, *args, **kwargs):
        displayed = original_editor(data, *args, **kwargs)
        if str(kwargs.get("key", "")).startswith(f"plan-{job_id}-") and displayed.empty:
            return pd.DataFrame([{"record": 1, "action": "set", "field": "signup_date", "new_value": None,
                                  "reason": None, "_needs_input": None}])
        return displayed

    monkeypatch.setattr(st, "data_editor", editor)
    try:
        screen = _open_job()
        _button(screen, "Prepare AI-assisted draft").click().run(timeout=20)
        assert not screen.exception
        editor_data = next(table.value for table in screen.dataframe if "new_value" in table.value.columns)
        retained = editor_data.loc[editor_data["field"] == "signup_date"].iloc[0]
        assert retained["new_value"] == retained["reason"] == ""
        assert not retained["_needs_input"]
        assert len(editor_data) == 3
        assert _button(screen, "Submit revised plan for review").disabled
        assert service.snapshot(job_id)["state"]["plan"] == []
    finally:
        service.close()


def test_fallback_is_clear_and_stale_draft_is_rejected(tmp_path, monkeypatch, local_environment):
    service = Workflow(tmp_path)
    job_id = service.create(NEGATIVE, RULES, name="Fallback review")
    result = service.suggest_corrections(job_id)
    result.update(fallback=True, source="local", message="AI assistance was unavailable or invalid. Local rules prepared this draft; you can continue entering corrections.")
    calls = []

    def fallback(self, job):
        calls.append(job)
        return deepcopy(result)

    monkeypatch.setattr(Workflow, "suggest_corrections", fallback)
    try:
        screen = _open_job()
        _button(screen, "Prepare AI-assisted draft").click().run(timeout=20)
        assert not screen.exception
        assert any("AI assistance was unavailable" in item.value for item in screen.warning)
        existing = deepcopy(screen.session_state[f"assisted-draft-{job_id}"])
        result["binding"]["plan_hash"] = "changed-after-screen-render"
        _button(screen, "Prepare AI-assisted draft").click().run(timeout=20)
        assert not screen.exception
        assert len(calls) == 2
        assert screen.session_state[f"assisted-draft-{job_id}"] == existing
        assert any("could not be fully prepared" in item.value for item in screen.warning)
        assert _button(screen, "Submit revised plan for review").disabled
    finally:
        service.close()
