"""Imported provenance must remain bound to both approval gates and fresh runs."""
import hashlib
import io
import json
from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import Workbook

import dq_agent.workflow as workflow_module
from dq_agent.engine import Engine
from dq_agent.imports import parse_upload
from dq_agent.workflow import Workflow


RULES = {"required_columns": ["id", "joined", "country"], "unique_columns": ["id"],
         "date_formats": {"joined": {"input": "%m/%d/%Y", "output": "%Y-%m-%d"}},
         "categories": {"country": {"allowed": ["US"], "aliases": {"us": "US"}}}}
CSV = b"id,joined,country\n001,10/24/2026,us\n001,10/24/2026,us\n"
JSON = b'[{"id":"001","joined":"10/24/2026","country":"us"},{"id":"001","joined":"10/24/2026","country":"us"}]'


@pytest.fixture(autouse=True)
def local_only(monkeypatch):
    monkeypatch.setattr(workflow_module, "load_dotenv", lambda: False)
    monkeypatch.setattr(workflow_module, "record_summary", lambda *args: False)
    def no_provider(*args, **kwargs):
        raise AssertionError("Integration tests must not construct real provider clients")
    monkeypatch.setattr("dq_agent.reasoning.make_model", no_provider)


@pytest.fixture
def workflow(tmp_path):
    instance = Workflow(tmp_path)
    yield instance
    instance.close()


def excel_bytes(*, multiple=False, native_date=False):
    book = Workbook()
    sheet = book.active
    sheet.title = "Customers"
    sheet.append(["id", "joined", "country"])
    value = datetime(2026, 10, 24) if native_date else "10/24/2026"
    sheet.append(["001", value, "us"])
    sheet.append(["001", value, "us"])
    if multiple:
        book.create_sheet("Other").append(["unrelated"])
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


def upload_bytes(extension):
    if extension == "csv":
        return CSV
    if extension == "tsv":
        return CSV.replace(b",", b"\t")
    if extension == "json":
        return JSON
    if extension in {"jsonl", "ndjson"}:
        return b"\n".join(json.dumps(record).encode() for record in json.loads(JSON)) + b"\n"
    return excel_bytes()


def approve(workflow, job_id):
    pending = workflow.snapshot(job_id)["pending"]
    return workflow.resume(job_id, {"action": "approve", "binding": pending["binding"]})


@pytest.mark.parametrize("extension", ["csv", "tsv", "json", "jsonl", "ndjson", "xlsx"])
def test_formats_need_both_approvals(workflow, extension):
    data = upload_bytes(extension)
    job_id = workflow.create_upload(data, "customers." + extension, RULES)
    directory = workflow.engine.job_dir(job_id)
    manifest = workflow.engine.import_manifest(job_id)
    assert manifest["format"] == extension
    assert workflow.engine.original_upload(job_id)["data"] == data
    assert workflow.engine.source_details(job_id)["imported"] is True
    assert (directory / "original.bin").read_bytes() == data
    assert workflow.engine.read_frame(job_id).iloc[0]["id"] == "001"
    assert workflow.snapshot(job_id)["pending"]["kind"] == "repair_approval"
    assert not (directory / "stage.json").exists()
    assert not (directory / "export.json").exists()
    with pytest.raises(ValueError, match="Explicit approval"):
        workflow.engine.apply(job_id, workflow.snapshot(job_id)["state"]["plan"], {})

    first = approve(workflow, job_id)
    assert first["pending"]["kind"] == "export_approval"
    assert (directory / "stage.json").exists()
    assert not (directory / "export.json").exists()
    with pytest.raises(ValueError, match="Explicit approval"):
        workflow.engine.export(job_id, {})
    completed = approve(workflow, job_id)
    assert completed["state"]["status"] == "complete"
    outputs = workflow.engine.verify_export(job_id)
    assert Path(outputs["csv_path"]).read_bytes() == b"id,joined,country\n001,2026-10-24,US\n"
    audit = json.loads(Path(outputs["audit_path"]).read_bytes())
    assert audit["source_provenance"]["manifest"] == manifest
    assert audit["source_provenance"]["original_hash"] == hashlib.sha256(data).hexdigest()
    assert "normalized text table" in audit["output_interpretation"]


@pytest.mark.parametrize("filename", ["original.bin", "manifest.json", "source.csv", "rules.json"])
@pytest.mark.parametrize("gate", ["repair", "export"])
def test_changed_input_blocks_approval_and_reset(workflow, filename, gate):
    job_id = workflow.create_upload(JSON, "customers.json", RULES)
    if gate == "export":
        approve(workflow, job_id)
    path = workflow.engine.job_dir(job_id) / filename
    path.write_bytes(path.read_bytes() + b" ")
    result = approve(workflow, job_id)
    assert result["state"]["status"] == "blocked"
    assert not (workflow.engine.job_dir(job_id) / "export.json").exists()
    if gate == "repair":
        assert not (workflow.engine.job_dir(job_id) / "stage.json").exists()
    with pytest.raises(ValueError, match="changed"):
        workflow.reset_job(job_id)
    with pytest.raises(ValueError, match="changed"):
        workflow.engine.original_upload(job_id)
    assert len(workflow.list_jobs()) == 1


def test_reset_copies_exact_parse_without_reparsing(workflow, monkeypatch):
    data = excel_bytes(multiple=True)
    job_id = workflow.create_upload(data, "customers.xlsx", RULES, sheet="Customers", name="Workbook review")
    approve(workflow, job_id)
    approve(workflow, job_id)
    old_snapshot = workflow.snapshot(job_id)
    old_files = {p.name: p.read_bytes() for p in workflow.engine.job_dir(job_id).iterdir() if p.is_file()}
    def no_reparse(*args, **kwargs):
        raise AssertionError("Reset must use the saved parse and selected sheet")
    monkeypatch.setattr("dq_agent.imports.parse_upload", no_reparse)
    rerun = workflow.reset_job(job_id)
    state = workflow.snapshot(rerun)["state"]
    assert state["rerun_of"] == job_id
    assert state["approval"] == state["export_approval"] == state["outputs"] == {}
    assert state["cycles"] == state["revisions"] == state["model_decisions"] == 0
    assert workflow.job_name(rerun) == "Workbook review — rerun 1"
    assert workflow.engine.source_details(rerun)["sheet"] == "Customers"
    assert workflow.snapshot(rerun)["pending"]["kind"] == "repair_approval"
    for filename in ("original.bin", "manifest.json", "source.csv", "rules.json"):
        assert (workflow.engine.job_dir(rerun) / filename).read_bytes() == old_files[filename]
    assert workflow.snapshot(job_id) == old_snapshot
    assert {p.name: p.read_bytes() for p in workflow.engine.job_dir(job_id).iterdir() if p.is_file()} == old_files
    assert workflow.engine.verify_export(job_id) == old_snapshot["state"]["outputs"]


@pytest.mark.parametrize("data,expected_drop_rows", [
    (b'[{"value":1},{"value":"1"}]', []),
    (b'[{"value":null},{},{"value":""}]', []),
    (b'[{"value":1},{"value":"1"},{"value":1},{"value":"1"}]', [2, 3]),
    (b'[{"value":null},{"value":null},{},{},{"value":""},{"value":""}]', [1, 3, 5]),
])
def test_projected_duplicates_preserve_source_type(workflow, data, expected_drop_rows):
    job_id = workflow.create_upload(data, "typed.json", {})
    plan = workflow.engine.propose(job_id)
    assert [op["row"] for op in plan if op["op"] == "drop"] == expected_drop_rows
    assert workflow.snapshot(job_id)["pending"]["kind"] == "clarification"
    assert workflow.engine.preview(job_id, plan)["blocking_count"] > 0
    with pytest.raises(ValueError, match="explicitly supplied"):
        workflow.engine.preview(job_id, [{"op": "drop", "row": 0, "reason": "Projection alone"}])


def test_manual_choice_can_resolve_typed_collision(workflow):
    job_id = workflow.create_upload(b'[{"value":1},{"value":"1"}]', "typed.json", {})
    plan = [{"op": "set", "row": 1, "column": "value", "value": "text 1", "reason": "User distinguishes text", "user_supplied": True}]
    workflow.resume(job_id, {"action": "revise", "plan": plan})
    approve(workflow, job_id)
    done = approve(workflow, job_id)
    audit = json.loads(Path(done["state"]["outputs"]["audit_path"]).read_bytes())
    assert audit["source_provenance"]["manifest"]["types"]["by_column"]["value"] == {"number": [0]}
    assert audit["changes"][0]["user_supplied"] is True


def test_native_excel_types_reach_audit(workflow):
    job_id = workflow.create_upload(excel_bytes(native_date=True), "native.xlsx", {})
    manifest = workflow.engine.import_manifest(job_id)
    assert manifest["types"]["by_column"]["joined"]
    approve(workflow, job_id)
    result = approve(workflow, job_id)
    audit = json.loads(Path(result["state"]["outputs"]["audit_path"]).read_bytes())
    assert audit["source_provenance"]["manifest"] == manifest


def test_legacy_hash_and_storage_unchanged(workflow):
    job_id = workflow.create(CSV, RULES)
    assert workflow.engine._binding(job_id)["source_hash"] == hashlib.sha256(CSV).hexdigest()
    assert workflow.engine.import_manifest(job_id) is None
    assert not workflow.engine.source_details(job_id)["imported"]
    assert not (workflow.engine.job_dir(job_id) / "original.bin").exists()


def test_binding_covers_raw_bytes_and_parse_choices(workflow):
    data = b'[{"value":"one"}]'
    first = workflow.create_upload(data, "first.json", {})
    second = workflow.create_upload(b"\n" + data, "first.json", {})
    third = workflow.create_upload(data, "renamed.json", {})
    jobs = [first, second, third]
    source_tables = [(workflow.engine.job_dir(job_id) / "source.csv").read_bytes() for job_id in jobs]
    assert source_tables[0] == source_tables[1] == source_tables[2]
    hashes = {workflow.engine._binding(job_id)["source_hash"] for job_id in jobs}
    assert len(hashes) == 3
    assert hashlib.sha256(source_tables[0]).hexdigest() not in hashes


def test_original_filename_is_only_a_label(workflow):
    job_id = workflow.create_upload(JSON, "../../escape/customers.json", RULES)
    download = workflow.engine.original_upload(job_id)
    assert download["filename"] == "customers.json"
    assert download["mime"] == "application/json"
    assert not (workflow.root / "customers.json").exists()
    assert (workflow.engine.job_dir(job_id) / "original.bin").exists()


def test_invalid_manifest_leaves_no_job(tmp_path):
    parsed = parse_upload(JSON, "customers.json")
    parsed.manifest["row_count"] += 1
    engine = Engine(tmp_path)
    with pytest.raises(ValueError, match="dimensions"):
        engine.create_import(parsed.csv_bytes, RULES, JSON, parsed.manifest)
    assert engine.list_jobs() == []
