"""Durable orchestration: Python gates keep the model away from write permissions."""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from threading import RLock
from typing import Literal, TypedDict

from dotenv import load_dotenv
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from langsmith import tracing_context

from .engine import Engine
from .job_names import MAX_NAME_LENGTH, JobNames, validate_name
from .reasoning import InvestigationError, investigate
from .telemetry import record_summary


class JobState(TypedDict, total=False):
    job_id: str
    mode: str
    status: str
    findings: dict
    plan: list[dict]
    preview: dict
    approval: dict
    export_approval: dict
    events: list[dict]
    outputs: dict
    error: str
    cycles: int
    revisions: int
    tracing_recorded: bool
    model_decisions: int
    rerun_of: str
    failure_stage: Literal["", "input_validation", "investigation", "preview", "apply", "revalidation", "export_approval", "export"]
    manual_recovery: bool
    investigation_error: str


# Older checkpoints did not record which node failed. These exact messages
# establish an investigation failure without guessing from arbitrary error text.
_LEGACY_INVESTIGATION_ERRORS = frozenset({
    "The model returned an invalid plan twice. No changes were made.",
    "The model exceeded the per-step tool limit.",
    "This job exhausted its 12-decision budget. Start a new job after resolving the cause.",
    "The job reached its decision budget. No changes were made; start a new job after review.",
    "Investigation could not start. Check installed provider packages and configuration, then retry.",
    "Set NEBIUS_API_KEY and NEBIUS_MODEL in your local .env file.",
    "Set FIREWORKS_API_KEY and FIREWORKS_MODEL in your local .env file.",
    "The provider rejected authentication or access. Check your local API key, account permissions, and access to the selected model, then retry the saved job.",
    "The provider could not find the configured model or endpoint. Check NEBIUS_MODEL or FIREWORKS_MODEL and the provider base URL, then retry the saved job.",
    "The provider is still rate limiting requests after three attempts. Check your account quota or wait before retrying the saved job.",
    "The provider is still reporting a server error after three attempts. Retry the saved job later.",
    "The provider could not be reached or timed out after three attempts. Check your connection and provider endpoint, then retry the saved job.",
    "The model request failed. Check provider settings or retry the saved job.",
})


class _JobNameCollision(ValueError):
    """A name was already claimed; a new rerun may try its next suffix."""


class Workflow:
    def __init__(self, root: Path, mode: str = "offline", model=None):
        load_dotenv()
        if mode not in {"offline", "nebius", "fireworks"}:
            raise ValueError("Unknown provider mode")
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.engine = Engine(self.root)
        self.mode, self.model = mode, model
        self.lock = RLock()
        self.connection = sqlite3.connect(str(self.root / "checkpoints.sqlite"), check_same_thread=False)
        self.saver = SqliteSaver(self.connection)
        self.saver.setup()
        g = StateGraph(JobState)
        for name in ("start", "investigate", "preview", "clarify", "approve_repairs", "apply", "revalidate", "approve_export", "export"):
            g.add_node(name, getattr(self, "_" + name))
        g.add_edge(START, "start")
        g.add_edge("start", "investigate")
        g.add_conditional_edges("investigate", lambda s: END if s["status"] == "blocked" else "preview")
        g.add_conditional_edges("preview", lambda s: END if s["status"] == "blocked" else
                                ("clarify" if s["preview"]["blocking_count"] else "approve_repairs"))
        g.add_conditional_edges("clarify", lambda s: END if s["status"] in {"blocked", "cancelled"} else "preview")
        g.add_conditional_edges("approve_repairs", lambda s: END if s["status"] == "cancelled" else
                                ("apply" if s["status"] == "approved" else "preview"))
        g.add_conditional_edges("apply", lambda s: END if s["status"] == "blocked" else "revalidate")
        g.add_conditional_edges("revalidate", lambda s: END if s["status"] == "blocked" else
                                ("clarify" if s["findings"]["blocking_count"] else "approve_export"))
        g.add_conditional_edges("approve_export", lambda s: END if s["status"] in {"blocked", "cancelled"} else "export")
        g.add_edge("export", END)
        self.graph = g.compile(checkpointer=self.saver)
        self.names = JobNames(self.root)
        self.names.ensure_legacy_names(self.engine.list_jobs())

    @staticmethod
    def _config(job_id):
        return {"configurable": {"thread_id": job_id}, "recursion_limit": 100}

    @staticmethod
    def _start(state):
        return {"status": "investigating", "error": "", "approval": {}, "export_approval": {}}

    def _investigate(self, s):
        clean = {"plan": [], "preview": {}, "approval": {}, "export_approval": {}, "events": [],
                 "tracing_recorded": False, "manual_recovery": False, "investigation_error": ""}
        try:
            findings = self.engine.validate(s["job_id"])
        except (ValueError, OSError):
            return {**clean, "findings": {}, "status": "blocked", "failure_stage": "input_validation",
                    "error": "The source or rules could not be validated. Check the saved job inputs."}
        try:
            plan, events = investigate(self.engine, s["job_id"], s["mode"], self.model,
                                       max_decisions=12-s.get("model_decisions", 0))
            return {**clean, "findings": findings, "plan": plan, "events": events, "failure_stage": "", "error": "",
                    "model_decisions": s.get("model_decisions", 0) + max((e.get("step", 0) for e in events), default=0),
                    "tracing_recorded": record_summary(s["mode"], events, findings["blocking_count"])}
        except InvestigationError as exc:
            return {**clean, "findings": findings, "status": "blocked", "failure_stage": "investigation",
                    "error": str(exc), "investigation_error": str(exc),
                    "model_decisions": s.get("model_decisions", 0) + exc.decisions}
        except Exception:
            # Provider setup may itself raise ValueError/OSError. Distinguish it
            # from an input-integrity failure by checking the local inputs again.
            try:
                findings = self.engine.validate(s["job_id"])
            except (ValueError, OSError):
                return {**clean, "findings": {}, "status": "blocked", "failure_stage": "input_validation",
                        "error": "The source or rules could not be validated. Check the saved job inputs."}
            error = "Investigation could not start. Check installed provider packages and configuration, then retry."
            return {**clean, "findings": findings, "status": "blocked", "failure_stage": "investigation",
                    "error": error, "investigation_error": error}

    def _preview(self, s):
        if s.get("revisions", 0) >= 12:
            return {"status": "blocked", "failure_stage": "preview", "error": "The job reached its revision limit. Start a new job with corrected input."}
        try:
            preview = self.engine.preview(s["job_id"], s["plan"])
            return {"preview": preview, "status": "awaiting_clarification" if preview["blocking_count"] else "awaiting_repair_approval",
                    "approval": {}, "export_approval": {}, "failure_stage": ""}
        except (ValueError, OSError) as exc:
            # This is local engine validation, never a provider exception.
            return {"status": "blocked", "failure_stage": "preview", "error": "Repair preview failed: " + str(exc)}

    def _clarify(self, s):
        response = interrupt({"kind": "clarification", "issues": s.get("preview", {}).get("validation", s["findings"])["issues"],
                              "plan": s["plan"], "preview": s.get("preview", {}),
                              "message": "Some blocking issues need your decision. Supply a value or explicitly remove a row, then preview again."})
        if response.get("action") != "revise":
            return {"status": "cancelled"}
        return {"plan": response.get("plan", s["plan"]), "status": "investigating",
                "revisions": s.get("revisions", 0) + 1}

    def _approve_repairs(self, s):
        binding = {k: s["preview"][k] for k in ("source_hash", "rules_hash", "plan_hash")}
        binding["job_id"] = s["job_id"]
        response = interrupt({"kind": "repair_approval", "plan": s["plan"], "preview": s["preview"],
                              "binding": binding,
                              "message": "Approve this exact plan to write a separate staged copy. The original remains unchanged."})
        if response.get("action") == "revise":
            return {"plan": response.get("plan", s["plan"]), "status": "investigating",
                    "revisions": s.get("revisions", 0) + 1}
        if response.get("action") != "approve":
            return {"status": "cancelled"}
        # Bind to the preview actually shown, not newly computed data at resume time.
        return {"approval": {**binding, "approved": True, "job_id": s["job_id"]}, "status": "approved"}

    def _apply(self, s):
        try:
            self.engine.apply(s["job_id"], s["plan"], s["approval"])
            return {"status": "validating", "cycles": s.get("cycles", 0) + 1}
        except (ValueError, OSError) as exc:
            return {"status": "blocked", "failure_stage": "apply", "error": "Repair was not committed: " + str(exc)}

    def _revalidate(self, s):
        try:
            findings = self.engine.validate(s["job_id"], staged=True)
        except (ValueError, OSError):
            return {"status": "blocked", "failure_stage": "revalidation", "error": "The staged copy could not be verified. No export was approved."}
        if findings["blocking_count"] and s.get("cycles", 0) >= 2:
            return {"findings": findings, "status": "blocked", "failure_stage": "revalidation", "error": "Two repair cycles failed validation. Resolve the remaining issues manually."}
        return {"findings": findings, "status": "awaiting_clarification" if findings["blocking_count"] else "awaiting_export_approval"}

    def _approve_export(self, s):
        try:
            binding = self.engine.export_binding(s["job_id"])
        except (ValueError, OSError):
            return {"status": "blocked", "failure_stage": "export_approval", "error": "The staged file or inputs changed. Final export is blocked."}
        response = interrupt({"kind": "export_approval", "binding": binding, "findings": s["findings"],
                              "message": "All blocking checks passed. Approve creation of the final CSV and audit files."})
        if response.get("action") != "approve":
            return {"status": "cancelled"}
        # Interrupt nodes restart on resume. Compare the original payload binding!
        expected = response.get("binding")
        if expected != binding:
            return {"status": "blocked", "failure_stage": "export_approval", "error": "The staged result changed after preview. Review it again before exporting."}
        return {"export_approval": {**binding, "approved": True}, "status": "exporting"}

    def _export(self, s):
        try:
            outputs = self.engine.export(s["job_id"], s["export_approval"])
            return {"outputs": outputs, "status": "complete", "error": ""}
        except (ValueError, OSError) as exc:
            return {"status": "blocked", "failure_stage": "export", "error": "Export was not committed: " + str(exc)}

    def _store_new_job(self, csv_bytes: bytes, rules: dict, name: str | None, *,
                       original_bytes: bytes | None = None, manifest: dict | None = None) -> str:
        # Keep allocation separate from graph execution: only a name collision
        # should cause a rerun to allocate another suffix.
        if name is not None:
            name = validate_name(name)
            try:
                self.names.check_available(name)
            except ValueError as exc:
                raise _JobNameCollision(str(exc)) from exc
        if (original_bytes is None) != (manifest is None):
            raise ValueError("Original upload and import manifest must be supplied together.")
        job_id = (self.engine.create_job(csv_bytes, rules) if manifest is None else
                  self.engine.create_import(csv_bytes, rules, original_bytes, manifest))
        try:
            self.names.assign(job_id, name)
        except Exception as exc:
            # Another app instance may claim the name after the first check.
            # This newly stored job has no workflow history to preserve yet.
            self.engine.delete_job(job_id)
            self.names.remove(job_id)
            if isinstance(exc, ValueError) and name is not None and self.names.lookup(name) is not None:
                raise _JobNameCollision(str(exc)) from exc
            raise
        return job_id

    def _start_new_job(self, job_id: str, mode: str, rerun_of: str | None = None) -> str:
        state = {"job_id": job_id, "mode": mode, "cycles": 0, "revisions": 0, "model_decisions": 0,
                 "approval": {}, "export_approval": {}, "outputs": {}, "error": ""}
        if rerun_of is not None:
            state["rerun_of"] = rerun_of
        self.graph.invoke(state, self._config(job_id))
        return job_id

    def create(self, csv_bytes: bytes, rules: dict, name: str | None = None) -> str:
        with self.lock, tracing_context(enabled=False):
            return self._start_new_job(self._store_new_job(csv_bytes, rules, name), self.mode)

    def create_upload(self, data: bytes, filename: str, rules: dict, *,
                      sheet: str | None = None, name: str | None = None) -> str:
        """Parse a supported upload while preserving its bytes and interpretation."""
        from .imports import parse_upload

        with self.lock, tracing_context(enabled=False):
            parsed = parse_upload(data, filename, sheet=sheet)
            job_id = self._store_new_job(parsed.csv_bytes, rules, name,
                                        original_bytes=data, manifest=parsed.manifest)
            return self._start_new_job(job_id, self.mode)

    def reset_job(self, job_id: str) -> str:
        """Start a new run from verified originals without altering the old run."""
        with self.lock, tracing_context(enabled=False):
            self._job_metadata(job_id)
            previous = self.snapshot(job_id)["state"]
            if not previous:
                raise ValueError("The saved job has no workflow history to restart.")
            mode = previous.get("mode", "offline")
            if mode not in {"offline", "nebius", "fireworks"}:
                raise ValueError("The original job has an unsupported provider mode.")
            # Reuse the exact saved parse, including sheet and type provenance.
            # Reparsing after a library upgrade could reinterpret the upload.
            original = self.engine.read_original_inputs(job_id)
            original_name = self.job_name(job_id)
            number = 1
            while True:
                suffix = f" — rerun {number}"
                candidate = original_name[:MAX_NAME_LENGTH - len(suffix)].rstrip() + suffix
                number += 1
                if self.names.lookup(candidate) is not None:
                    continue
                try:
                    new_job_id = self._store_new_job(original["csv_bytes"], original["rules"], candidate,
                                                     original_bytes=original["original_bytes"],
                                                     manifest=original["manifest"])
                except _JobNameCollision:
                    # Two local app instances may request a rerun together.
                    continue
                return self._start_new_job(new_job_id, mode, rerun_of=job_id)

    def snapshot(self, job_id: str) -> dict:
        with self.lock, tracing_context(enabled=False):
            self.engine.job_dir(job_id)  # Validate path before reading state.
            snap = self.graph.get_state(self._config(job_id))
            pending = next((i.value for task in snap.tasks for i in task.interrupts), None)
            return {"state": dict(snap.values), "pending": pending, "next": list(snap.next)}

    def resume(self, job_id: str, response: dict) -> dict:
        with self.lock, tracing_context(enabled=False):
            snap = self.snapshot(job_id)
            if not snap["pending"]:
                raise ValueError("This job is not waiting for user input.")
            response = dict(response)
            if response.get("action") == "approve" and response.get("binding") != snap["pending"].get("binding"):
                raise ValueError("This approval does not match the displayed plan. Reopen the job and review it again.")
            self.graph.invoke(Command(resume=response), self._config(job_id))
            return self.snapshot(job_id)

    def suggest_corrections(self, job_id: str) -> dict:
        """Read-only assistance for the currently displayed, saved review plan."""
        from .assistance import suggest_corrections

        with self.lock, tracing_context(enabled=False):
            before = self.snapshot(job_id)
            pending = before["pending"]
            if not pending or pending.get("kind") not in {"clarification", "repair_approval"}:
                raise ValueError("Draft assistance is available only while reviewing corrections.")
            result = suggest_corrections(self.engine, job_id, before["state"]["mode"],
                                         pending["plan"], model=self.model)
            if self.snapshot(job_id) != before:
                raise ValueError("The saved review changed while assistance was being prepared. Reopen the job.")
            return result

    def preview_value_request(self, job_id: str, fields: list[str]) -> dict:
        """Prepare an exact selected-field disclosure preview without a model call."""
        from .value_suggestions import preview_request

        with self.lock, tracing_context(enabled=False):
            snapshot = self.snapshot(job_id)
            pending = snapshot["pending"]
            if not pending or pending.get("kind") not in {"clarification", "repair_approval"}:
                raise ValueError("Value suggestions are available only while reviewing corrections.")
            state = snapshot["state"]
            return preview_request(self.engine, job_id, pending["plan"], fields,
                                   mode=state["mode"], pending_kind=pending["kind"],
                                   revisions=state.get("revisions", 0))

    def suggest_values(self, job_id: str, request: dict, consent: bool) -> dict:
        """Use only the exact current disclosure preview that the user consented to."""
        from .value_suggestions import suggest_values

        if consent is not True:
            raise ValueError("Review the exact payload and explicitly consent before sending selected values.")
        if not isinstance(request, dict) or "fields" not in request:
            raise ValueError("Prepare a current disclosure preview before requesting suggestions.")
        with self.lock, tracing_context(enabled=False):
            before = self.snapshot(job_id)
            expected = self.preview_value_request(job_id, request["fields"])
            # Rebuild locally rather than trusting a caller-provided network payload.
            if request != expected:
                raise ValueError("The selected-data preview changed or is stale. Review a fresh preview and consent again.")
            result = suggest_values(self.engine, job_id, before["pending"]["plan"], expected, model=self.model)
            if self.snapshot(job_id) != before:
                raise ValueError("The saved review changed while suggestions were being prepared. Reopen the job.")
            if self.preview_value_request(job_id, request["fields"]) != expected:
                raise ValueError("The selected data changed while suggestions were being prepared. Review a fresh preview.")
            return result

    def retry(self, job_id: str) -> dict:
        with self.lock, tracing_context(enabled=False):
            snap = self.snapshot(job_id)
            if snap["state"].get("status") != "blocked":
                raise ValueError("Only blocked jobs can be retried.")
            self.graph.update_state(self._config(job_id), {"status": "investigating", "error": "", "approval": {}, "export_approval": {}}, as_node="start")
            self.graph.invoke(None, self._config(job_id))
            return self.snapshot(job_id)

    def _manual_recovery_inputs(self, job_id: str) -> tuple[dict, dict]:
        """Verify eligibility afresh; failed write stages never use this route."""
        metadata = self._job_metadata(job_id)
        snapshot = self.snapshot(job_id)
        state = snapshot["state"]
        stage = state.get("failure_stage")
        investigation_failed = (stage == "investigation" or
                                (not stage and state.get("error") in _LEGACY_INVESTIGATION_ERRORS))
        if (state.get("status") != "blocked" or not investigation_failed
                or snapshot["pending"] or snapshot["next"]):
            raise ValueError("Manual continuation is available only after a stopped investigation.")
        if (state.get("cycles", 0) != 0 or state.get("approval") or state.get("export_approval")
                or state.get("outputs") or state.get("revisions", 0) >= 12):
            raise ValueError("This job has reached an approval, write, or revision boundary; manual recovery is unavailable.")
        for checkpoint in self.graph.get_state_history(self._config(job_id)):
            prior = checkpoint.values
            if prior.get("approval") or prior.get("export_approval") or prior.get("outputs") or prior.get("cycles", 0):
                raise ValueError("This job previously reached an approved write; manual recovery is unavailable.")
        original_files = {"source.csv", "rules.json", "metadata.json"}
        if metadata.get("import_version"):
            original_files |= {"original.bin", "manifest.json"}
        if any(path.name not in original_files or not path.is_file() or path.is_symlink()
               for path in self.engine.job_dir(job_id).iterdir()):
            raise ValueError("This job has staged, exported, or unexpected files; manual recovery is unavailable.")
        # Capture verification covers imported provenance as well as CSV/rules.
        self.engine.read_original_inputs(job_id)
        return state, self.engine.validate(job_id)

    def can_continue_manually(self, job_id: str) -> bool:
        """Read-only eligibility check for a deliberate user recovery action."""
        with self.lock, tracing_context(enabled=False):
            try:
                self._manual_recovery_inputs(job_id)
                return True
            except (ValueError, OSError, KeyError, TypeError):
                return False

    def continue_manually(self, job_id: str) -> dict:
        """Resume this job at a real preview without calling or impersonating a model."""
        with self.lock, tracing_context(enabled=False):
            state, findings = self._manual_recovery_inputs(job_id)
            update = {"status": "investigating", "findings": findings, "plan": [], "preview": {},
                      "approval": {}, "export_approval": {}, "outputs": {}, "error": "", "failure_stage": "",
                      "manual_recovery": True, "investigation_error": state.get("error", ""),
                      "events": [*state.get("events", []), {"event": "manual_recovery", "reason": "investigation_failed"}]}
            # The failed investigation remains in checkpoint history. Declaring
            # this explicit handoff as its continuation routes through preview,
            # clarification and both existing approval gates; no write is skipped.
            self.graph.update_state(self._config(job_id), update, as_node="investigate")
            self.graph.invoke(None, self._config(job_id))
            return self.snapshot(job_id)

    def list_jobs(self) -> list[str]:
        with self.lock:
            return sorted([p.name for p in self.root.iterdir() if p.is_dir() and self._is_job(p.name)], reverse=True)

    def _job_metadata(self, job_id: str) -> dict:
        try:
            metadata = self.engine.metadata(job_id)
        except (ValueError, OSError) as exc:
            raise ValueError("No saved job matches that name or identifier.") from exc
        if metadata.get("job_id") != job_id:
            raise ValueError("The saved job metadata does not match its identifier.")
        return metadata

    def job_name(self, job_id: str) -> str:
        with self.lock:
            metadata = self._job_metadata(job_id)
            self.names.ensure_legacy_names([metadata])
            return self.names.get(job_id)

    def list_named_jobs(self) -> list[dict]:
        with self.lock:
            records = []
            for job_id in self.list_jobs():
                metadata = self._job_metadata(job_id)
                records.append({"job_id": job_id, "created_at": metadata["created_at"],
                                "row_count": metadata["row_count"],
                                "status": self.snapshot(job_id)["state"].get("status", "investigating")})
            self.names.ensure_legacy_names(records)
            for record in records:
                record["name"] = self.names.get(record["job_id"])
            return sorted(records, key=lambda item: (item["created_at"], item["job_id"]), reverse=True)

    def resolve_job(self, name_or_id: str) -> str:
        with self.lock:
            if not isinstance(name_or_id, str) or not name_or_id.strip():
                raise ValueError("Enter the name of a saved job.")
            query = name_or_id.strip()
            self.names.ensure_legacy_names(self.engine.list_jobs())
            job_id = self.names.lookup(query)
            if job_id is None:
                try:
                    job_id = str(uuid.UUID(query))
                except ValueError as exc:
                    raise ValueError("No saved job matches that name or identifier.") from exc
            self._job_metadata(job_id)
            return job_id

    def rename_job(self, job_id: str, name: str) -> str:
        with self.lock:
            self.job_name(job_id)  # Verify the job and migrate a legacy record.
            return self.names.rename(job_id, name)

    def _is_job(self, name):
        try:
            return bool(self.snapshot(name)["state"])
        except (ValueError, OSError):
            return False

    def delete(self, job_id: str):
        with self.lock:
            self.engine.job_dir(job_id)
            self.engine.delete_job(job_id)
            self.saver.delete_thread(job_id)
            self.names.remove(job_id)

    def close(self):
        self.names.close()
        self.connection.close()
