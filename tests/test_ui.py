"""Exercise the real Streamlit screen and both user approval gates."""

import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import streamlit as st
import pytest
from streamlit.testing.v1 import AppTest

from dq_agent.workflow import Workflow


APP = Path(__file__).resolve().parents[1] / "app.py"


def _button(app, label):
    return next(button for button in app.button if button.label == label)


def _checkbox(app, label):
    return next(box for box in app.checkbox if box.label == label)


def _workspace():
    app = AppTest.from_file(str(APP))
    app.query_params["view"] = "workspace"
    return app.run(timeout=20)



def _to_preview(app, name=""):
    _button(app, "Continue to rules").click().run()
    if name:
        next(field for field in app.text_input if field.label == "Job name").set_value(name).run()
    _button(app, "Continue to preview").click().run()
    assert not app.exception


def test_sample_screen_clarification_both_approvals_and_downloads(tmp_path, monkeypatch):
    monkeypatch.setenv("DQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DQ_PROVIDER", "offline")
    monkeypatch.setenv("DQ_LANGSMITH_TRACING", "false")
    app = _workspace()
    assert not app.exception
    _button(app, "Negative test").click().run()
    assert any("02/30/2026,ZZ" in block.value for block in app.code)
    _to_preview(app, "October customer review")
    _button(app, "Create job and inspect data").click().run(timeout=20)
    assert not app.exception
    job_id = app.session_state["active_job"]
    service = Workflow(tmp_path)
    try:
        assert service.job_name(job_id) == "October customer review"
        snapshot = service.snapshot(job_id)
        assert snapshot["pending"]["kind"] == "clarification"
        assert snapshot["state"]["findings"]["blocking_count"] == 3
        assert len(service.engine.read_frame(job_id)) == 2
        assert not (service.engine.job_dir(job_id) / "stage.json").exists()
        # AppTest cannot edit a data_editor cell directly. Supply the synthetic
        # fixture's missing facts through the same public workflow endpoint.
        plan = snapshot["state"]["plan"] + [
            {"op": "set", "row": 0, "column": "signup_date", "value": "2026-02-28",
             "reason": "Verified synthetic signup date", "user_supplied": True},
            {"op": "set", "row": 0, "column": "country", "value": "US",
             "reason": "Verified synthetic country", "user_supplied": True},
            {"op": "set", "row": 1, "column": "customer_id", "value": "102",
             "reason": "Verified synthetic source ID", "user_supplied": True},
        ]
        service.resume(job_id, {"action": "revise", "plan": plan})
        app.run(timeout=20)
        assert not app.exception
        assert _button(app, "Approve repairs and validate the copy").disabled
        assert not (service.engine.job_dir(job_id) / "stage.json").exists()
        _checkbox(app, "I approve this exact plan and writing its changes to a staged copy.").check().run()
        assert not _button(app, "Approve repairs and validate the copy").disabled
        stale_button = _button(app, "Approve repairs and validate the copy")
        stale_key = stale_button.key
        # Another window revises the plan after this window renders its consent.
        revised_plan = plan + [{
            "op": "set", "row": 0, "column": "name", "value": "Ada Chen",
            "reason": "Explicitly confirmed synthetic name", "user_supplied": True,
        }]
        service.resume(job_id, {"action": "revise", "plan": revised_plan})
        stale_button.click().run(timeout=20)
        assert not app.exception
        assert _button(app, "Approve repairs and validate the copy").key != stale_key
        assert _button(app, "Approve repairs and validate the copy").disabled
        assert not (service.engine.job_dir(job_id) / "stage.json").exists()
        _checkbox(app, "I approve this exact plan and writing its changes to a staged copy.").check().run()
        _button(app, "Approve repairs and validate the copy").click().run(timeout=20)
        assert not app.exception
        assert service.snapshot(job_id)["pending"]["kind"] == "export_approval"
        assert not (service.engine.job_dir(job_id) / "export.json").exists()
        assert _button(app, "Approve export").disabled
        _checkbox(app, "I approve creating the final CSV, audit report, and validation summary.").check().run()
        _button(app, "Approve export").click().run(timeout=20)
        assert not app.exception
        snapshot = service.snapshot(job_id)
        assert snapshot["state"]["status"] == "complete"
        assert len(snapshot["state"]["outputs"]) == 3
        assert all(Path(path).is_file() for path in snapshot["state"]["outputs"].values())
        assert len(app.get("download_button")) == 3
        assert service.engine.read_frame(job_id, staged=True).iloc[1]["customer_id"] == "102"
        # A modified artifact must not be served as a verified download.
        Path(snapshot["state"]["outputs"]["csv_path"]).write_text("altered file", encoding="utf-8")
        app.run(timeout=20)
        assert not app.exception
        assert len(app.get("download_button")) == 0
        assert any("could not be verified" in error.value for error in app.error)
    finally:
        service.close()


def test_positive_sample_and_reset_keep_previous_results(tmp_path, monkeypatch):
    monkeypatch.setenv("DQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DQ_PROVIDER", "offline")
    monkeypatch.setenv("DQ_LANGSMITH_TRACING", "false")
    app = _workspace()
    assert not app.exception
    _button(app, "Positive test").click().run()
    scenario = next(field for field in app.selectbox if field.label == "Sample scenario")
    assert scenario.value == "Positive test — rule-based repairs"
    assert len(scenario.options) == 2
    positive_source = (APP.parent / "samples" / "customers_positive.csv").read_bytes()
    assert any(positive_source.decode().strip() == block.value.strip() for block in app.code)
    _to_preview(app, "Positive sample review")
    _button(app, "Create job and inspect data").click().run(timeout=20)
    assert not app.exception
    original_id = app.session_state["active_job"]
    service = Workflow(tmp_path)
    try:
        initial = service.snapshot(original_id)
        assert initial["pending"]["kind"] == "repair_approval"
        assert initial["state"]["plan"]
        assert len(service.engine.read_frame(original_id)) == 8
        assert (service.engine.job_dir(original_id) / "source.csv").read_bytes() == positive_source
        assert _button(app, "Approve repairs and validate the copy").disabled
        _checkbox(app, "I approve this exact plan and writing its changes to a staged copy.").check().run()
        _button(app, "Approve repairs and validate the copy").click().run(timeout=20)
        assert not app.exception
        assert service.snapshot(original_id)["pending"]["kind"] == "export_approval"
        _checkbox(app, "I approve creating the final CSV, audit report, and validation summary.").check().run()
        _button(app, "Approve export").click().run(timeout=20)
        assert not app.exception
        completed = service.snapshot(original_id)
        assert completed["state"]["status"] == "complete"
        output_bytes = {path: Path(path).read_bytes() for path in completed["state"]["outputs"].values()}
        _button(app, "Reset job").click().run(timeout=20)
        assert not app.exception
        fresh_id = app.session_state["active_job"]
        assert fresh_id != original_id
        fresh = service.snapshot(fresh_id)
        assert fresh["pending"]["kind"] == "repair_approval"
        assert fresh["state"]["mode"] == "offline"
        assert _button(app, "Approve repairs and validate the copy").disabled
        assert not (service.engine.job_dir(fresh_id) / "stage.json").exists()
        assert not (service.engine.job_dir(fresh_id) / "export.json").exists()
        assert (service.engine.job_dir(fresh_id) / "source.csv").read_bytes() == positive_source
        assert service.snapshot(original_id) == completed
        assert all(Path(path).read_bytes() == data for path, data in output_bytes.items())
        assert service.resolve_job("Positive sample review") == original_id
        assert "rerun" in service.job_name(fresh_id).lower()
        assert len(service.list_jobs()) == 2
        # Reset can be used again, including before any approval in a fresh run.
        _button(app, "Reset job").click().run(timeout=20)
        assert not app.exception
        second_fresh_id = app.session_state["active_job"]
        assert second_fresh_id not in {original_id, fresh_id}
        assert len(service.list_jobs()) == 3
        assert service.snapshot(fresh_id) == fresh
        assert service.snapshot(original_id) == completed
    finally:
        service.close()


def test_provider_default_is_configurable_without_displaying_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("DQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DQ_PROVIDER", "nebius")
    monkeypatch.setenv("NEBIUS_API_KEY", "test-key-never-show-this")
    app = _workspace()
    assert not app.exception
    _button(app, "Settings").click().run()
    assert next(field for field in app.selectbox if field.label == "Investigation mode for new jobs").value == "Nebius Token Factory"
    captions = " ".join(item.value for item in app.caption)
    assert "configured" in captions
    assert "test-key-never-show-this" not in captions


def test_named_job_lookup_and_rename_in_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("DQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DQ_PROVIDER", "offline")
    monkeypatch.setenv("DQ_LANGSMITH_TRACING", "false")
    service = Workflow(tmp_path)
    try:
        job_id = service.create(b"customer_id,name\n101,Iris Demo\n", {
            "required_columns": ["customer_id", "name"], "unique_columns": ["customer_id"],
        }, name="October customers")
        app = _workspace()
        assert not app.exception
        assert _button(app, "Continue review")
        _button(app, "Settings").click().run()
        next(field for field in app.text_input if field.label == "Open by job name").set_value("OCTOBER CUSTOMERS")
        _button(app, "Open by name").click().run(timeout=20)
        assert not app.exception
        assert app.session_state["active_job"] == job_id
        before_theme_switch = service.snapshot(job_id)
        assert app.segmented_control[0].value == "Dark"
        app.segmented_control[0].set_value("Light").run(timeout=20)
        assert not app.exception
        assert app.session_state["active_job"] == job_id
        assert app.segmented_control[0].value == "Light"
        assert service.snapshot(job_id) == before_theme_switch
        next(field for field in app.text_input if field.label == "Rename job").set_value("October import review")
        _button(app, "Save name").click().run(timeout=20)
        assert not app.exception
        assert service.job_name(job_id) == "October import review"
        assert app.segmented_control[0].value == "Light"
        _button(app, "Settings").click().run(timeout=20)
        next(field for field in app.text_input if field.label == "Open by job name").set_value("october import review")
        _button(app, "Open by name").click().run(timeout=20)
        assert not app.exception
        assert app.session_state["active_job"] == job_id
        assert service.snapshot(job_id)["pending"]["kind"] == "repair_approval"
    finally:
        service.close()


def test_landing_is_separate_and_theme_carries_into_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("DQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DQ_PROVIDER", "offline")
    app = AppTest.from_file(str(APP)).run(timeout=20)
    assert not app.exception
    assert not app.text_input
    assert not app.selectbox
    assert not app.get("file_uploader")
    assert not app.sidebar.button
    app.segmented_control[0].set_value("Light").run(timeout=20)
    assert app.query_params["appearance"] == "light"
    # Follow the landing link in a fresh browser session with its URL parameters.
    workspace = AppTest.from_file(str(APP))
    workspace.query_params["view"] = "workspace"
    workspace.query_params["appearance"] = "light"
    workspace.run(timeout=20)
    assert not workspace.exception
    assert workspace.segmented_control[0].value == "Light"
    assert _button(workspace, "Start a review")
    _button(workspace, "Back to product").click().run(timeout=20)
    assert not workspace.exception
    assert not workspace.text_input
    assert not workspace.sidebar.button
    assert workspace.segmented_control[0].value == "Light"


def _supply_upload(monkeypatch, data, filename):
    """AppTest has no uploader driver; exercise the real screen with file bytes."""
    uploaded = SimpleNamespace(name=filename, getvalue=lambda: data)
    original_uploader = st.file_uploader

    def file_uploader(label, *args, **kwargs):
        if label == "Customer data file (up to 10 MB)":
            return uploaded
        return original_uploader(label, *args, **kwargs)

    monkeypatch.setattr(st, "file_uploader", file_uploader)


def _workbook_bytes(sheets):
    from openpyxl import Workbook

    book = Workbook()
    book.remove(book.active)
    for name, rows in sheets.items():
        sheet = book.create_sheet(name)
        for row in rows:
            sheet.append(row)
    buffer = BytesIO()
    book.save(buffer)
    book.close()
    return buffer.getvalue()


def test_json_upload_preview_does_not_create_job_until_clicked(tmp_path, monkeypatch):
    monkeypatch.setenv("DQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DQ_PROVIDER", "offline")
    monkeypatch.setenv("DQ_LANGSMITH_TRACING", "false")
    data = b'[{"customer_id":"001","name":"Iris Demo","email":"iris@example.com","signup_date":"2026-10-05","country":"US"}]'
    filename = "customers.json"
    _supply_upload(monkeypatch, data, filename)
    app = _workspace()
    _button(app, "Start a review").click().run()
    assert not app.exception
    assert not _button(app, "Continue to rules").disabled
    assert any(field.value == filename for field in app.text)
    service = Workflow(tmp_path)
    try:
        assert service.list_jobs() == []
        _to_preview(app)
        assert service.list_jobs() == []
        assert any("Values are shown as text" in item.value for item in app.caption)
        _button(app, "Create job and inspect data").click().run(timeout=20)
        assert not app.exception
        job_id = app.session_state["active_job"]
        assert service.snapshot(job_id)["pending"]["kind"] == "repair_approval"
        assert service.engine.read_frame(job_id).iloc[0]["customer_id"] == "001"
        assert service.engine.source_details(job_id)["format"] == "json"
        assert service.engine.original_upload(job_id)["data"] == data
        assert any(button.label == "Download original upload" for button in app.get("download_button"))
    finally:
        service.close()


def test_multisheet_upload_requires_selection_before_creation(tmp_path, monkeypatch):
    monkeypatch.setenv("DQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DQ_PROVIDER", "offline")
    monkeypatch.setenv("DQ_LANGSMITH_TRACING", "false")
    rows = [
        ["customer_id", "name", "email", "signup_date", "country"],
        ["001", "Iris Demo", "iris@example.com", "2026-10-05", "US"],
    ]
    data = _workbook_bytes({"Customers": rows, "Other": [["note"], ["A different table"]]})
    _supply_upload(monkeypatch, data, "customer-book.xlsx")
    app = _workspace()
    _button(app, "Start a review").click().run()
    assert not app.exception
    sheet = next(field for field in app.selectbox if field.label == "Worksheet to review")
    assert sheet.value is None
    assert sheet.options == ["Customers", "Other"]
    assert _button(app, "Continue to rules").disabled
    service = Workflow(tmp_path)
    try:
        assert service.list_jobs() == []
        sheet.set_value("Customers").run()
        assert not app.exception
        assert not _button(app, "Continue to rules").disabled
        assert service.list_jobs() == []
        _to_preview(app)
        assert service.list_jobs() == []
        assert any("Values are shown as text" in item.value for item in app.caption)
        _button(app, "Create job and inspect data").click().run(timeout=20)
        assert not app.exception
        job_id = app.session_state["active_job"]
        assert service.engine.source_details(job_id)["sheet"] == "Customers"
        assert service.engine.original_upload(job_id)["data"] == data
        assert service.engine.read_frame(job_id).iloc[0]["customer_id"] == "001"
    finally:
        service.close()


def test_rejected_nested_json_and_formula_workbook_cannot_create_jobs(tmp_path, monkeypatch):
    monkeypatch.setenv("DQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DQ_PROVIDER", "offline")
    monkeypatch.setenv("DQ_LANGSMITH_TRACING", "false")
    uploads = [
        (b'[{"customer_id":"001","details":{"country":"US"}}]', "nested.json", "nested"),
        (_workbook_bytes({"Customers": [["customer_id", "name"], ["001", "=1+1"]]}), "formula.xlsx", "formula"),
    ]
    service = Workflow(tmp_path)
    try:
        for data, filename, expected_message in uploads:
            _supply_upload(monkeypatch, data, filename)
            app = _workspace()
            _button(app, "Start a review").click().run()
            assert not app.exception
            assert _button(app, "Continue to rules").disabled
            assert any("could not be prepared" in item.value for item in app.error)
            assert any(expected_message in item.value.lower() for item in app.text)
            assert service.list_jobs() == []
    finally:
        service.close()


def test_hub_search_status_filters_and_saved_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("DQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DQ_PROVIDER", "offline")
    monkeypatch.setenv("DQ_LANGSMITH_TRACING", "false")
    service = Workflow(tmp_path)
    try:
        rules = {"required_columns": ["customer_id"]}
        completed_id = service.create(b"customer_id,name\n001,Iris\n", rules, name="October approved")
        for _ in range(2):
            pending = service.snapshot(completed_id)["pending"]
            service.resume(completed_id, {"action": "approve", "binding": pending["binding"]})
        completed = service.snapshot(completed_id)
        service.create(b"customer_id,name\n,Noah\n", rules, name="October follow-up")
        cancelled_id = service.create(b"customer_id,name\n002,Remy\n", rules, name="January cancelled")
        service.resume(cancelled_id, {"action": "cancel"})
        app = _workspace()
        assert not app.exception
        assert not app.sidebar.button
        assert len([button for button in app.button if button.label == "Continue review"]) == 2
        assert _button(app, "View results")
        assert any(item.value == "3 of 3 saved reviews" for item in app.caption)
        status_filter = next(field for field in app.segmented_control if field.label == "Review status")
        status_filter.set_value("Needs attention").run()
        assert len([button for button in app.button if button.label == "Continue review"]) == 1
        assert not any(button.label == "View results" for button in app.button)
        next(field for field in app.text_input if field.label == "Search saved reviews").set_value("JANUARY").run()
        assert any("No reviews match" in item.value for item in app.info)
        assert any(item.value == "0 of 3 saved reviews" for item in app.caption)
        next(field for field in app.text_input if field.label == "Search saved reviews").set_value("OCTOBER").run()
        next(field for field in app.segmented_control if field.label == "Review status").set_value("Completed").run()
        assert any(item.value == "1 of 3 saved reviews" for item in app.caption)
        _button(app, "Saved reviews").click().run()
        assert not any(button.label == "Start a review" for button in app.button)
        next(button for button in app.button if button.key == f"review-reset-{completed_id}").click().run(timeout=20)
        assert not app.exception
        assert app.session_state["active_job"] != completed_id
        assert service.snapshot(completed_id) == completed
        assert len(service.list_jobs()) == 4
        assert _button(app, "Confirm unchanged copy").disabled
    finally:
        service.close()


def test_draft_persists_across_steps_theme_and_hub_then_file_removal_blocks_progress(tmp_path, monkeypatch):
    monkeypatch.setenv("DQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DQ_PROVIDER", "offline")
    monkeypatch.setenv("DQ_LANGSMITH_TRACING", "false")
    data = b'[{"customer_id":"001","name":"Iris"}]'
    rule_bytes = b'{"required_columns":["customer_id"],"unique_columns":["customer_id"]}'
    uploads = {
        "Customer data file (up to 10 MB)": SimpleNamespace(name="customers.json", getvalue=lambda: data),
        "Import specification (JSON)": SimpleNamespace(name="rules.json", getvalue=lambda: rule_bytes),
    }
    original_uploader = st.file_uploader
    monkeypatch.setattr(st, "file_uploader", lambda label, *args, **kwargs: uploads[label] if label in uploads else original_uploader(label, *args, **kwargs))
    app = _workspace()
    _button(app, "Start a review").click().run()
    _button(app, "Continue to rules").click().run()
    _checkbox(app, "Use the included customer import rules").uncheck().run()
    name = "![review](https://example.org/preview.png)"
    next(field for field in app.text_input if field.label == "Job name").set_value(name).run()
    _button(app, "Continue to preview").click().run()
    assert not app.exception
    assert any(item.value == f"Review name: {name}" for item in app.text)
    assert not any(name in item.value for item in app.markdown)
    service = Workflow(tmp_path)
    try:
        assert service.list_jobs() == []
        app.segmented_control[0].set_value("Light").run()
        _button(app, "Back to workspace").click().run()
        assert _button(app, "Continue draft")
        assert service.list_jobs() == []
        uploads["Customer data file (up to 10 MB)"] = None
        uploads["Import specification (JSON)"] = None
        _button(app, "Continue draft").click().run()
        assert any(item.value == f"Review name: {name}" for item in app.text)
        assert app.session_state["review_draft"]["data"] == data
        assert app.session_state["review_draft"]["custom_rules"] == rule_bytes
        _button(app, "Back to rules").click().run()
        assert next(field for field in app.text_input if field.label == "Job name").value == name
        assert not _checkbox(app, "Use the included customer import rules").value
        _button(app, "Back to file").click().run()
        assert not _button(app, "Continue to rules").disabled
        assert app.segmented_control[0].value == "Light"
        _button(app, "Remove file").click().run()
        assert not app.exception
        assert _button(app, "Continue to rules").disabled
        assert app.session_state["review_draft"]["parsed"] is None
        assert app.session_state["review_draft"]["data"] is None
        assert service.list_jobs() == []
    finally:
        service.close()


def test_replaced_rules_and_sample_are_the_ones_used_at_creation(tmp_path, monkeypatch):
    monkeypatch.setenv("DQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DQ_PROVIDER", "offline")
    monkeypatch.setenv("DQ_LANGSMITH_TRACING", "false")
    current_rules = {"data": b'{"required_columns":["customer_id"]}'}
    original_uploader = st.file_uploader

    def uploader(label, *args, **kwargs):
        if label == "Import specification (JSON)":
            return SimpleNamespace(name="rules.json", getvalue=lambda: current_rules["data"]) if current_rules["data"] else None
        return original_uploader(label, *args, **kwargs)

    monkeypatch.setattr(st, "file_uploader", uploader)
    app = _workspace()
    _button(app, "Positive test").click().run()
    _button(app, "Continue to rules").click().run()
    _checkbox(app, "Use the included customer import rules").uncheck().run()
    _button(app, "Continue to preview").click().run()
    service = Workflow(tmp_path)
    try:
        assert service.list_jobs() == []
        _button(app, "Back to rules").click().run()
        current_rules["data"] = None
        _button(app, "Remove custom rules").click().run()
        assert _button(app, "Continue to preview").disabled
        current_rules["data"] = b'{invalid'
        app.run()
        assert _button(app, "Continue to preview").disabled
        replacement = {"required_columns": ["customer_id", "country"], "unique_columns": ["customer_id"]}
        current_rules["data"] = json.dumps(replacement).encode()
        app.run()
        _button(app, "Back to file").click().run()
        next(field for field in app.selectbox if field.label == "Sample scenario").set_value("Negative test — needs your knowledge").run()
        _to_preview(app)
        assert service.list_jobs() == []
        assert app.session_state["review_draft"]["parsed"].manifest["row_count"] == 2
        _button(app, "Create job and inspect data").click().run(timeout=20)
        assert not app.exception
        job_id = app.session_state["active_job"]
        assert len(service.engine.read_frame(job_id)) == 2
        loaded_rules = service.engine.load_rules(job_id)
        assert loaded_rules["required_columns"] == replacement["required_columns"]
        assert loaded_rules["unique_columns"] == replacement["unique_columns"]
        assert loaded_rules["date_formats"] == {}
        assert loaded_rules["categories"] == {}
    finally:
        service.close()


def _capture_scorecards(monkeypatch):
    from dq_agent import presentation

    captured = []
    original = presentation.render_summary_metrics

    def render(records, blockers, changes, **kwargs):
        captured.append({"records": records, "blockers": blockers, "changes": changes, **kwargs})
        return original(records, blockers, changes, **kwargs)

    monkeypatch.setattr(presentation, "render_summary_metrics", render)
    return captured


@pytest.mark.parametrize("legacy", [False, True], ids=["new-failure", "legacy-missing-findings"])
def test_failed_model_keeps_local_count_and_manual_corrections_require_both_approvals(tmp_path, monkeypatch, legacy):
    monkeypatch.setenv("DQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DQ_PROVIDER", "offline")
    monkeypatch.setenv("DQ_LANGSMITH_TRACING", "false")
    scores = _capture_scorecards(monkeypatch)

    class FailedModel:
        calls = 0

        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            self.calls += 1
            raise RuntimeError("synthetic provider failure; never displayed")

    unexpected_model_calls = []

    def no_provider_call(*args, **kwargs):
        unexpected_model_calls.append(True)
        raise AssertionError("Manual continuation must not create a provider client")

    monkeypatch.setattr("dq_agent.reasoning.make_model", no_provider_call)
    fake = FailedModel()
    service = Workflow(tmp_path, mode="nebius", model=fake)
    original = (APP.parent / "samples" / "customers_negative.csv").read_bytes()
    rules = json.loads((APP.parent / "samples" / "import_rules.json").read_text())
    try:
        job_id = service.create(original, rules, name="Stopped investigation")
        failed = service.snapshot(job_id)
        assert failed["state"]["status"] == "blocked"
        assert failed["state"]["findings"]["blocking_count"] == 3
        assert fake.calls == 1
        decisions = failed["state"]["model_decisions"]
        if legacy:
            service.graph.update_state(service._config(job_id), {
                "findings": {}, "failure_stage": "",
                "error": "The model returned an invalid plan twice. No changes were made.",
            }, as_node="investigate")
        app = _workspace()
        _button(app, "Continue review").click().run()
        assert not app.exception
        assert scores[-1]["blockers"] == 3
        assert scores[-1]["blocker_caption"] == "Original file — local rule checks"
        issues = next(table.value for table in app.dataframe if "kind" in table.value.columns)
        assert len(issues) == 3
        assert _button(app, "Continue with manual corrections")
        _button(app, "Continue with manual corrections").click().run(timeout=20)
        assert not app.exception
        assert app.session_state["active_job"] == job_id
        manual = service.snapshot(job_id)
        assert manual["pending"]["kind"] == "clarification"
        assert manual["state"]["plan"] == []
        assert manual["state"]["manual_recovery"] is True
        assert manual["state"]["mode"] == "nebius"
        assert manual["state"]["model_decisions"] == decisions
        assert scores[-1]["blockers"] == 3
        assert any("No additional model request" in item.value for item in app.info)
        assert _button(app, "Submit revised plan for review")
        assert not (service.engine.job_dir(job_id) / "stage.json").exists()
        plan = [
            {"op": "set", "row": 0, "column": "signup_date", "value": "2026-02-28", "reason": "Confirmed synthetic date", "user_supplied": True},
            {"op": "set", "row": 0, "column": "country", "value": "US", "reason": "Confirmed synthetic country", "user_supplied": True},
            {"op": "set", "row": 1, "column": "customer_id", "value": "102", "reason": "Confirmed synthetic ID", "user_supplied": True},
        ]
        service.resume(job_id, {"action": "revise", "plan": plan})
        app.run()
        assert not app.exception
        assert scores[-1]["blockers"] == 0
        assert not any("kind" in table.value.columns for table in app.dataframe)
        assert _button(app, "Approve repairs and validate the copy").disabled
        _checkbox(app, "I approve this exact plan and writing its changes to a staged copy.").check().run()
        _button(app, "Approve repairs and validate the copy").click().run(timeout=20)
        assert not app.exception
        assert service.snapshot(job_id)["pending"]["kind"] == "export_approval"
        assert _button(app, "Approve export").disabled
        assert not (service.engine.job_dir(job_id) / "export.json").exists()
        _checkbox(app, "I approve creating the final CSV, audit report, and validation summary.").check().run()
        _button(app, "Approve export").click().run(timeout=20)
        assert not app.exception
        assert service.snapshot(job_id)["state"]["status"] == "complete"
        assert service.snapshot(job_id)["state"]["mode"] == "nebius"
        assert (service.engine.job_dir(job_id) / "source.csv").read_bytes() == original
        assert len(app.get("download_button")) == 3
        assert fake.calls == 1
        assert unexpected_model_calls == []
    finally:
        service.close()


def test_unverified_validation_is_unknown_and_failed_write_has_no_manual_recovery(tmp_path, monkeypatch):
    from dq_agent.engine import Engine

    monkeypatch.setenv("DQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DQ_PROVIDER", "offline")
    monkeypatch.setenv("DQ_LANGSMITH_TRACING", "false")
    scores = _capture_scorecards(monkeypatch)
    service = Workflow(tmp_path)
    try:
        job_id = service.create(b"customer_id,name\n001,Iris\n", {"required_columns": ["customer_id"]}, name="Stopped export")
        binding = service.snapshot(job_id)["pending"]["binding"]
        service.resume(job_id, {"action": "approve", "binding": binding})
        service.graph.update_state(service._config(job_id), {
            "status": "blocked", "failure_stage": "export", "error": "Export was not committed.",
        }, as_node="export")
        app = _workspace()
        _button(app, "Continue review").click().run()
        assert not app.exception
        assert not any(button.label == "Continue with manual corrections" for button in app.button)
        with monkeypatch.context() as local:
            def unavailable(*args, **kwargs):
                raise ValueError("Synthetic unavailable validation")

            local.setattr(Engine, "validate", unavailable)
            app.run()
            assert not app.exception
            assert scores[-1]["blockers"] is None
            assert any("does not mean there are zero issues" in item.value for item in app.warning)
            assert not any("No blocking issues" in item.value for item in app.success)
            assert not any(button.label == "Continue with manual corrections" for button in app.button)
        (service.engine.job_dir(job_id) / "source.csv").write_text("tampered source", encoding="utf-8")
        app.run()
        assert not app.exception
        assert any("could not be opened" in item.value for item in app.error)
        assert not any(button.label == "Continue with manual corrections" for button in app.button)
    finally:
        service.close()
