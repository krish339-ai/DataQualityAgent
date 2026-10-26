"""Names are durable labels; changing a label must never change an approval."""
import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import dq_agent.workflow as workflow_module
from dq_agent.job_names import JobNames
from dq_agent.workflow import Workflow


CSV = b"customer_id,name\n001,Ada\n"
RULES = {"required_columns": ["customer_id", "name"], "unique_columns": ["customer_id"]}


@pytest.fixture(autouse=True)
def local_only(monkeypatch):
    # These tests never inspect .env, call a model, or submit traces.
    monkeypatch.setattr(workflow_module, "load_dotenv", lambda: False)
    monkeypatch.setattr(workflow_module, "record_summary", lambda *args: False)


@pytest.fixture
def workflow(tmp_path):
    instance = Workflow(tmp_path)
    yield instance
    instance.close()


def approve(instance, job_id):
    binding = instance.snapshot(job_id)["pending"]["binding"]
    return instance.resume(job_id, {"action": "approve", "binding": binding})


def file_hashes(directory):
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in directory.iterdir() if path.is_file()}


def test_names_create_list_rename_and_reopen(tmp_path):
    first = Workflow(tmp_path)
    job_a = first.create(CSV, RULES)
    job_b = first.create(CSV, RULES, name="  October import  ")
    assert str(uuid.UUID(job_a)) == job_a
    assert first.job_name(job_a) == "Customer review 001"
    assert first.job_name(job_b) == "October import"
    assert first.resolve_job("OCTOBER IMPORT") == job_b
    assert first.resolve_job(job_b.upper()) == job_b
    assert first.rename_job(job_a, "September cleanup") == "September cleanup"
    named = first.list_named_jobs()
    assert [row["job_id"] for row in named] == [job_b, job_a]
    assert named[0] == {"job_id": job_b, "name": "October import", "created_at": first.engine.metadata(job_b)["created_at"],
                        "status": "awaiting_repair_approval", "row_count": 1}
    assert set(first.list_jobs()) == {job_a, job_b}
    first.close()
    reopened = Workflow(tmp_path)
    try:
        assert reopened.resolve_job("september CLEANUP") == job_a
        assert reopened.job_name(job_b) == "October import"
        job_c = reopened.create(CSV, RULES)
        assert reopened.job_name(job_c) == "Customer review 002"
    finally:
        reopened.close()


def test_default_names_skip_existing_custom_name(workflow):
    custom = workflow.create(CSV, RULES, name="CUSTOMER REVIEW 001")
    automatic = workflow.create(CSV, RULES)
    assert workflow.job_name(custom) == "CUSTOMER REVIEW 001"
    assert workflow.job_name(automatic) == "Customer review 002"


def test_casefold_duplicates_leave_existing_jobs_unchanged(workflow):
    first = workflow.create(CSV, RULES, name="Straße review")
    second = workflow.create(CSV, RULES, name="Second review")
    existing_files = file_hashes(workflow.engine.job_dir(first))
    with pytest.raises(ValueError, match="already uses"):
        workflow.create(CSV, RULES, name="STRASSE REVIEW")
    with pytest.raises(ValueError, match="already uses"):
        workflow.rename_job(second, "strasse review")
    assert workflow.resolve_job("STRASSE REVIEW") == first
    assert workflow.job_name(second) == "Second review"
    assert set(workflow.list_jobs()) == {first, second}
    assert len(workflow.engine.list_jobs()) == 2
    assert file_hashes(workflow.engine.job_dir(first)) == existing_files
    assert workflow.rename_job(first, "STRASSE REVIEW") == "STRASSE REVIEW"


@pytest.mark.parametrize("name", ["", "   ", "x" * 81, "first\nsecond", "tab\tname", "hidden\u200bname", "line\u2028name", str(uuid.uuid4()), 12])
def test_invalid_explicit_names_fail_before_storing_upload(workflow, name):
    with pytest.raises(ValueError):
        workflow.create(CSV, RULES, name=name)
    assert workflow.engine.list_jobs() == []


def test_rename_does_not_invalidate_pending_approval_or_exports(workflow):
    job = workflow.create(CSV, RULES, name="Initial name")
    repair_binding = workflow.snapshot(job)["pending"]["binding"]
    source_hashes = file_hashes(workflow.engine.job_dir(job))
    workflow.rename_job(job, "Ready for review")
    assert workflow.snapshot(job)["pending"]["binding"] == repair_binding
    assert file_hashes(workflow.engine.job_dir(job)) == source_hashes
    approve(workflow, job)
    export_binding = workflow.snapshot(job)["pending"]["binding"]
    workflow.rename_job(job, "Ready to export")
    assert workflow.snapshot(job)["pending"]["binding"] == export_binding
    approve(workflow, job)
    completed_state = workflow.snapshot(job)
    completed_hashes = file_hashes(workflow.engine.job_dir(job))
    workflow.rename_job(job, "Finished customer file")
    assert workflow.snapshot(job) == completed_state
    assert file_hashes(workflow.engine.job_dir(job)) == completed_hashes
    assert workflow.engine.verify_export(job) == completed_state["state"]["outputs"]
    assert workflow.list_named_jobs()[0]["status"] == "complete"


def test_legacy_migration_is_persistent_and_preserves_all_job_data(tmp_path):
    original = Workflow(tmp_path)
    older = original.create(CSV, RULES)
    newer = original.create(CSV, RULES)
    approve(original, older)
    approve(original, older)
    before_state = original.snapshot(older)
    before_files = file_hashes(original.engine.job_dir(older))
    original.close()
    # Simulate the registry never having existed in the pre-feature application.
    (tmp_path / "job_names.sqlite").unlink()
    checkpoint_hash = hashlib.sha256((tmp_path / "checkpoints.sqlite").read_bytes()).hexdigest()
    migrated = Workflow(tmp_path)
    try:
        assert migrated.job_name(older) == "Customer review 001"
        assert migrated.job_name(newer) == "Customer review 002"
        assert migrated.snapshot(older) == before_state
        assert file_hashes(migrated.engine.job_dir(older)) == before_files
        assert migrated.engine.verify_export(older) == before_state["state"]["outputs"]
        assert hashlib.sha256((tmp_path / "checkpoints.sqlite").read_bytes()).hexdigest() == checkpoint_hash
    finally:
        migrated.close()
    reopened = Workflow(tmp_path)
    try:
        assert reopened.resolve_job("customer review 001") == older
        assert reopened.resolve_job("CUSTOMER REVIEW 002") == newer
    finally:
        reopened.close()


def test_missing_and_deleted_jobs_are_not_resolved(workflow):
    missing = str(uuid.uuid4())
    for operation in (lambda: workflow.resolve_job("Unknown job"), lambda: workflow.resolve_job(missing),
                      lambda: workflow.job_name(missing), lambda: workflow.rename_job(missing, "New name"),
                      lambda: workflow.resolve_job("../outside")):
        with pytest.raises(ValueError, match="No saved job"):
            operation()
    with pytest.raises(ValueError, match="Enter the name"):
        workflow.resolve_job("   ")
    job = workflow.create(CSV, RULES, name="Delete me")
    workflow.delete(job)
    with pytest.raises(ValueError, match="No saved job"):
        workflow.resolve_job("Delete me")
    replacement = workflow.create(CSV, RULES, name="Delete me")
    assert replacement != job
    assert workflow.resolve_job("delete me") == replacement


def test_names_never_become_paths(workflow):
    job = workflow.create(CSV, RULES, name="../A human label")
    assert workflow.resolve_job("../A HUMAN LABEL") == job
    assert workflow.engine.job_dir(job).parent == workflow.root
    assert not (workflow.root.parent / "A human label").exists()
    with pytest.raises(ValueError):
        workflow.rename_job("../outside", "Invalid target")


def test_multiple_registry_instances_allocate_unique_names(tmp_path):
    first, second = JobNames(tmp_path), JobNames(tmp_path)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda pair: pair[0].assign(pair[1]), [(first, str(uuid.uuid4())), (second, str(uuid.uuid4()))]))
        assert set(outcomes) == {"Customer review 001", "Customer review 002"}

        def claim(store):
            try:
                return store.assign(str(uuid.uuid4()), "Same custom name")
            except ValueError:
                return "collision"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(claim, (first, second)))
        assert sorted(outcomes) == ["Same custom name", "collision"]
    finally:
        first.close()
        second.close()


def test_registry_rejects_linked_database_path(tmp_path, monkeypatch):
    real_is_symlink = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path.name == "job_names.sqlite" or real_is_symlink(path))
    with pytest.raises(ValueError, match="inside the local job store"):
        JobNames(tmp_path)


def test_concurrent_legacy_scan_does_not_replace_requested_name(workflow, monkeypatch):
    original_create = workflow.engine.create_job

    def create_and_migrate(data, rules):
        job = original_create(data, rules)
        workflow.names.ensure_legacy_names(workflow.engine.list_jobs())
        return job

    monkeypatch.setattr(workflow.engine, "create_job", create_and_migrate)
    job = workflow.create(CSV, RULES, name="Requested display name")
    assert workflow.job_name(job) == "Requested display name"


def test_late_name_collision_cleans_uncheckpointed_job_and_label(workflow, monkeypatch):
    winner = workflow.create(CSV, RULES, name="Contended name")
    original_create = workflow.engine.create_job

    def create_and_migrate(data, rules):
        job = original_create(data, rules)
        workflow.names.ensure_legacy_names(workflow.engine.list_jobs())
        return job

    # Simulate a stale availability check and another instance's migration.
    monkeypatch.setattr(workflow.names, "check_available", lambda name: name)
    monkeypatch.setattr(workflow.engine, "create_job", create_and_migrate)
    with pytest.raises(ValueError, match="already uses"):
        workflow.create(CSV, RULES, name="Contended name")
    assert [job["job_id"] for job in workflow.engine.list_jobs()] == [winner]
    assert workflow.names.lookup("Customer review 001") is None
    assert workflow.resolve_job("Contended name") == winner
