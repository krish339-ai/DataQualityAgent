"""Verify transformations against expected data, not just mocked tool calls."""

import hashlib
import json
from pathlib import Path

import pytest

import dq_agent.engine as engine_module
from dq_agent.engine import DataQualityError, Engine


RULES = {
    "required_columns": ["customer_id", "name", "signup_date", "country"],
    "unique_columns": ["customer_id"],
    "date_formats": {"signup_date": {"input": "%m/%d/%Y", "output": "%Y-%m-%d"}},
    "categories": {"country": {"allowed": ["US", "CA"], "aliases": {"us": "US", "ca": "CA"}}},
}
HEADER = "customer_id,name,signup_date,country\n"
ROW_A = "001,Ada,2026-10-24,US\n"
ROW_B = "002,Ben,2026-10-23,CA\n"


@pytest.fixture
def engine(tmp_path):
    return Engine(tmp_path / "jobs")


def repair_approval(engine, job_id, plan):
    preview = engine.preview(job_id, plan)
    return {key: preview[key] for key in ("job_id", "source_hash", "rules_hash", "plan_hash")} | {"approved": True}


def stage(engine, job_id, plan=None):
    if plan is None:
        plan = engine.propose(job_id)
    return engine.apply(job_id, plan, repair_approval(engine, job_id, plan))


@pytest.mark.parametrize("source,manual,expected", [
    (ROW_A, [], ROW_A),
    (ROW_A + ROW_A, [], ROW_A),
    (ROW_A + ROW_B + ROW_A + ROW_B, [], ROW_A + ROW_B),
    ("001,Ada,2026-10-24,us\n", [], ROW_A),
    ("002,Ben,2026-10-23,ca\n", [], ROW_B),
    ("001,Ada,10/24/2026,US\n", [], ROW_A),
    ("002,Ben,10/23/2026,CA\n", [], ROW_B),
    (",Ada,2026-10-24,US\n", [{"op": "set", "row": 0, "column": "customer_id", "value": "001", "reason": "User verified customer ID.", "user_supplied": True}], ROW_A),
    ("001,Ada,10/24/2026,us\n" * 2, [], ROW_A),
    ("001,Ada,10/24/2026,us\n002,Ben,10/23/2026,ca\n", [], ROW_A + ROW_B),
], ids=["clean", "duplicate", "two-duplicates", "category-us", "category-ca", "date-a", "date-b", "clarification", "mixed-duplicate", "mixed-two-rows"])
def test_ten_repairable_cases(engine, source, manual, expected):
    original = (HEADER + source).encode()
    job_id = engine.create_job(original, RULES)
    plan = engine.propose(job_id) + manual
    preview = engine.preview(job_id, plan)
    assert preview["blocking_count"] == 0
    staged = stage(engine, job_id, plan)
    assert engine.validate(job_id, staged=True)["blocking_count"] == 0
    # Replaying a paused write has no duplicate effect and returns the same commit.
    assert stage(engine, job_id, plan) == staged
    approval = {**engine.export_binding(job_id), "approved": True}
    outputs = engine.export(job_id, approval)
    assert Path(outputs["csv_path"]).read_bytes() == (HEADER + expected).encode()
    assert engine.export(job_id, approval) == outputs
    assert (engine.job_dir(job_id) / "source.csv").read_bytes() == original
    audit = json.loads(Path(outputs["audit_path"]).read_text(encoding="utf-8"))
    assert len(audit["changes"]) == len(plan)
    assert audit["validation"]["blocking_count"] == 0
    assert audit["export_approval"]["approved"] is True


def test_strings_and_blank_rows_are_preserved(engine):
    source = b"customer_id,name,signup_date,country\n001,NA,2026-10-24,US\n\n002,null,2026-10-23,CA\n"
    job = engine.create_job(source, RULES)
    frame = engine.read_frame(job)
    assert frame["customer_id"].tolist() == ["001", "", "002"]
    assert frame["name"].tolist() == ["NA", "", "null"]
    assert engine.profile(job)["row_count"] == 3
    assert engine.validate(job)["counts"]["missing_required"] == 4


@pytest.mark.parametrize("source", [
    b"", b"name,name\na,b\n", b"name,\na,b\n", b"name,id\na\n",
    b"name,id\na,b,c\n", b'name,id\n"unfinished,b\n', b"name\n\xff\n",
    b"name\na\x00\n", b"name\n",
])
def test_malformed_input_rejected_before_job_created(engine, source):
    with pytest.raises(DataQualityError):
        engine.create_job(source, {})
    assert engine.list_jobs() == []


def test_utf8_bom_is_supported(engine):
    job = engine.create_job(b"\xef\xbb\xbf" + (HEADER + ROW_A).encode(), RULES)
    assert engine.read_frame(job).columns[0] == "customer_id"


def test_file_and_row_limits_are_enforced(engine, monkeypatch):
    monkeypatch.setattr(engine_module, "MAX_BYTES", 10)
    with pytest.raises(DataQualityError, match="10 MB"):
        engine.create_job(b"field\nlong value\n", {})
    monkeypatch.setattr(engine_module, "MAX_BYTES", 1000)
    monkeypatch.setattr(engine_module, "MAX_ROWS", 2)
    with pytest.raises(DataQualityError, match="100,000"):
        engine.create_job(b"field\none\ntwo\nthree\n", {})


def test_no_write_without_exact_approval(engine):
    job = engine.create_job((HEADER + ROW_A + ROW_A).encode(), RULES)
    plan = engine.propose(job)
    approval = repair_approval(engine, job, plan)
    for modified in ({}, {**approval, "approved": False}, {**approval, "approved": 1},
                     {**approval, "plan_hash": "stale"}, {**approval, "job_id": "other"}):
        with pytest.raises(DataQualityError):
            engine.apply(job, plan, modified)
    assert not (engine.job_dir(job) / "stage.json").exists()
    changed_plan = [{**plan[0], "reason": "A revised explanation needs fresh approval."}]
    with pytest.raises(DataQualityError, match="stale"):
        engine.apply(job, changed_plan, approval)


def test_source_or_rules_tampering_invalidates_job(engine):
    for filename in ("source.csv", "rules.json"):
        job = engine.create_job((HEADER + ROW_A).encode(), RULES)
        path = engine.job_dir(job) / filename
        path.write_bytes(path.read_bytes() + b" ")
        with pytest.raises(DataQualityError, match="changed after upload"):
            engine.preview(job, [])


def test_arbitrary_changes_require_explicit_user_supplied_marker(engine):
    job = engine.create_job((HEADER + ROW_A).encode(), RULES)
    operation = {"op": "set", "row": 0, "column": "name", "value": "Different", "reason": "An invented guess"}
    with pytest.raises(DataQualityError, match="explicitly supplied"):
        engine.preview(job, [operation])
    operation["user_supplied"] = True
    stage(engine, job, [operation])
    assert engine.read_frame(job, staged=True).at[0, "name"] == "Different"


def test_unknown_values_remain_unresolved(engine):
    job = engine.create_job((HEADER + ",Ada,03/04/26,unknown\n").encode(), RULES)
    assert engine.propose(job) == []
    assert engine.validate(job)["counts"] == {"missing_required": 1, "date_format": 1, "category": 1}
    stage(engine, job, [])
    with pytest.raises(DataQualityError, match="blocked"):
        engine.export(job, {**engine.export_binding(job), "approved": True})


def test_declared_date_format_controls_ambiguous_dates(engine):
    job = engine.create_job((HEADER + "001,Ada,03/04/2026,US\n").encode(), RULES)
    assert engine.propose(job)[0]["value"] == "2026-03-04"
    alternate = {**RULES, "date_formats": {"signup_date": {"input": "%d/%m/%Y", "output": "%Y-%m-%d"}}}
    other_job = engine.create_job((HEADER + "001,Ada,03/04/2026,US\n").encode(), alternate)
    assert engine.propose(other_job)[0]["value"] == "2026-04-03"


def test_conflicting_customer_identity_not_merged(engine):
    job = engine.create_job((HEADER + ROW_A + "001,Someone Else,2026-10-24,US\n").encode(), RULES)
    assert engine.propose(job) == []
    assert engine.validate(job)["counts"] == {"duplicate_key": 2}


@pytest.mark.parametrize("value", ["=1+1", "+SUM(A1)", "-1+2", "@SUM(A1)", "  =1", "\tplain"])
def test_formula_values_block_export(engine, value):
    job = engine.create_job((HEADER + f"001,{value},2026-10-24,US\n").encode(), RULES)
    assert engine.validate(job)["counts"]["formula_risk"] == 1
    stage(engine, job, [])
    with pytest.raises(DataQualityError, match="blocked"):
        engine.export(job, {**engine.export_binding(job), "approved": True})


def test_formula_header_blocks_export(engine):
    job = engine.create_job(b"=1+1,name\n001,Ada\n", {})
    assert engine.validate(job)["issues"][0]["kind"] == "formula_risk"


def test_conflicting_plans_rejected(engine):
    job = engine.create_job((HEADER + ROW_A + ROW_B).encode(), RULES)
    change = {"op": "set", "row": 0, "column": "name", "value": "Updated", "reason": "User confirmed", "user_supplied": True}
    drop = {"op": "drop", "row": 0, "reason": "User confirmed", "user_supplied": True}
    for plan in ([change, change], [change, drop], [{**change, "row": 99}], [{**change, "column": "absent"}]):
        with pytest.raises(DataQualityError):
            engine.preview(job, plan)


def test_deleting_all_rows_not_exportable(engine):
    job = engine.create_job((HEADER + ROW_A).encode(), RULES)
    plan = [{"op": "drop", "row": 0, "reason": "User selected removal", "user_supplied": True}]
    assert engine.preview(job, plan)["blocking_count"] == 1
    with pytest.raises(DataQualityError, match="every data row"):
        stage(engine, job, plan)


@pytest.mark.parametrize("rules", [
    {"unexpected": True}, {"required_columns": ["", "name"]}, {"required_columns": ["name", "name"]},
    {"categories": {"country": {"allowed": ["US"], "aliases": {"ca": "CA"}}}},
    {"categories": {"country": {"allowed": ["US"], "aliases": {"": "US"}}}},
    {"categories": {"country": {"allowed": [""]}}},
    {"categories": {"country": {"allowed": ["US", "CA"], "aliases": {"CA": "US"}}}},
    {"date_formats": {"signup_date": {"input": "%m/%d/%y", "output": "%Y-%m-%d"}}},
])
def test_invalid_rules_rejected(engine, rules):
    with pytest.raises(DataQualityError, match="Invalid import rules"):
        engine.create_job((HEADER + ROW_A).encode(), rules)


def test_staged_and_export_approvals_detect_tampering(engine):
    job = engine.create_job((HEADER + ROW_A).encode(), RULES)
    record = stage(engine, job, [])
    approval = {**engine.export_binding(job), "approved": True}
    with pytest.raises(DataQualityError, match="stale"):
        engine.export(job, {**approval, "validation_hash": "changed"})
    (engine.job_dir(job) / record["staged_file"]).write_text(HEADER + ROW_B, encoding="utf-8")
    with pytest.raises(DataQualityError, match="staged file changed"):
        engine.export(job, approval)


def test_same_result_from_revised_plan_requires_fresh_export_approval(engine):
    job = engine.create_job((HEADER + ROW_A + ROW_A).encode(), RULES)
    plan = engine.propose(job)
    stage(engine, job, plan)
    approval = {**engine.export_binding(job), "approved": True}
    original_exports = engine.export(job, approval)
    revised = [{**plan[0], "reason": "A revised documented reason."}]
    stage(engine, job, revised)
    with pytest.raises(DataQualityError, match="stale"):
        engine.export(job, approval)
    latest = engine.export(job, {**engine.export_binding(job), "approved": True})
    assert latest["audit_path"] != original_exports["audit_path"]
    assert json.loads(Path(latest["audit_path"]).read_text())["changes"][0]["reason"] == revised[0]["reason"]


def test_completed_download_integrity_is_read_only(engine):
    job = engine.create_job((HEADER + ROW_A).encode(), RULES)
    with pytest.raises(DataQualityError, match="No approved export"):
        engine.verify_export(job)
    stage(engine, job, [])
    paths = engine.export(job, {**engine.export_binding(job), "approved": True})
    assert engine.verify_export(job) == paths
    Path(paths["csv_path"]).write_text(HEADER + ROW_B)
    with pytest.raises(DataQualityError, match="artifact changed"):
        engine.verify_export(job)


def test_crash_before_manifest_commit_can_be_replayed(engine, monkeypatch):
    job = engine.create_job((HEADER + ROW_A + ROW_A).encode(), RULES)
    original = engine_module._atomic

    def crash_on_commit(path, data):
        if path.name == "stage.json":
            raise OSError("Simulated interruption before commit")
        return original(path, data)

    monkeypatch.setattr(engine_module, "_atomic", crash_on_commit)
    with pytest.raises(OSError, match="Simulated interruption"):
        stage(engine, job)
    monkeypatch.setattr(engine_module, "_atomic", original)
    restarted = Engine(engine.root)
    stage(restarted, job)
    assert restarted.read_frame(job, staged=True)["customer_id"].tolist() == ["001"]
    assert hashlib.sha256((engine.job_dir(job) / "source.csv").read_bytes()).hexdigest() == engine.metadata(job)["source_hash"]


def test_job_boundaries_and_deletion(engine, tmp_path):
    with pytest.raises(DataQualityError, match="identifier"):
        engine.job_dir("../outside")
    job = engine.create_job((HEADER + ROW_A).encode(), RULES)
    other = tmp_path / "do-not-delete.txt"
    other.write_text("keep")
    nested = engine.job_dir(job) / "unexpected"
    nested.mkdir()
    with pytest.raises(DataQualityError, match="Unexpected nested"):
        engine.delete_job(job)
    nested.rmdir()
    engine.delete_job(job)
    assert not engine.job_dir(job).exists()
    assert other.read_text() == "keep"


def test_findings_do_not_echo_customer_values(engine):
    secret_value = "private.customer@example.test"
    job = engine.create_job((HEADER + f"001,{secret_value},2026-10-24,private-category\n").encode(), RULES)
    findings = json.dumps(engine.validate(job))
    assert secret_value not in findings
    assert "private-category" not in findings
