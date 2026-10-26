"""A local, single-user review desk for the Data Quality Agent.

Streamlit only presents information and collects decisions. The workflow and
engine independently enforce approval, validation, and file-write rules.
Run with: python -m streamlit run app.py
"""

from __future__ import annotations

import hashlib
import html
import json
import os
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from dq_agent.imports import ParsedImport, inspect_upload, parse_upload
from dq_agent.correction_controls import correction_spec, correction_value
from dq_agent.schemas import ImportRules
from dq_agent.workflow import Workflow
from dq_agent.presentation import (
    BRAND_NAME,
    apply_theme,
    render_brand,
    render_job_header,
    render_landing,
    render_summary_metrics,
    render_workflow_progress,
)


PROJECT_DIR = Path(__file__).resolve().parent
SAMPLE_DIR = PROJECT_DIR / "samples"
SAMPLE_SCENARIOS = {
    "Positive test — rule-based repairs": {
        "file": "customers_positive.csv",
        "description": "Eight synthetic records with repairable duplicates, date formats, and country aliases. All required facts are present: review the proposed repairs, then approve export.",
    },
    "Negative test — needs your knowledge": {
        "file": "customers_negative.csv",
        "description": "Two synthetic records with an impossible date, an unknown country, and a missing customer ID. The agent pauses for facts you supply before asking for repair approval.",
    },
}
MODE_LABELS = {
    "Offline demonstration (no model calls)": "offline",
    "Nebius Token Factory": "nebius",
    "Fireworks": "fireworks",
}
STATUS_LABELS = {
    "investigating": "Inspecting the file",
    "awaiting_clarification": "Needs your knowledge",
    "awaiting_repair_approval": "Ready for repair review",
    "awaiting_export_approval": "Validated — ready for export review",
    "complete": "Complete — outputs are ready",
    "cancelled": "Cancelled",
    "blocked": "Stopped — your attention is needed",
}
FORMAT_LABELS = {"csv": "CSV", "tsv": "TSV", "xlsx": "Excel (.xlsx)", "json": "JSON", "jsonl": "JSON Lines", "ndjson": "NDJSON"}


@st.cache_resource
def get_workflow(data_dir: str, mode: str) -> Workflow:
    """Keep the SQLite connection between Streamlit screen refreshes."""
    return Workflow(Path(data_dir), mode=mode)


def _fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _plan_rows(plan: list[dict]) -> list[dict]:
    """The screen uses one-based record numbers; the engine uses zero-based rows."""
    return [
        {
            "record": operation["row"] + 1,
            "action": operation["op"],
            "field": operation.get("column") or "",
            "new_value": operation.get("value") or "",
            "reason": operation.get("reason") or "",
        }
        for operation in plan
    ]


def _edited_plan(rows: list[dict], original: list[dict]) -> list[dict]:
    """Preserve engine proposals; explicitly mark human edits as user-supplied."""
    originals = {_fingerprint(row): operation for row, operation in zip(_plan_rows(original), original)}
    result = []
    for row in rows:
        # A newly added, entirely blank editor row is not a repair.
        if not row.get("action") and not row.get("record"):
            continue
        record = row.get("record")
        if record is None or pd.isna(record) or float(record) < 1 or not float(record).is_integer():
            raise ValueError("Each change needs a whole record number of at least 1.")
        normalized = {
            "record": int(record),
            "action": str(row.get("action") or ""),
            "field": str(row.get("field") or ""),
            "new_value": str(row.get("new_value") or ""),
            "reason": str(row.get("reason") or ""),
        }
        if _needs_input(row) and normalized["action"] == "set" and not normalized["new_value"].strip():
            raise ValueError("Needs your input: supply a verified New value and Reason for each draft row, or remove the row. Blank draft values cannot clear data.")
        existing = originals.get(_fingerprint(normalized))
        if existing is not None:
            result.append(dict(existing))
            continue
        if normalized["action"] not in {"set", "drop"}:
            raise ValueError("Choose set (change one field) or drop (remove a record).")
        if not normalized["reason"].strip():
            raise ValueError("Explain why each added or changed repair is correct.")
        operation = {
            "op": normalized["action"],
            "row": normalized["record"] - 1,
            "reason": normalized["reason"],
            "user_supplied": True,
        }
        if operation["op"] == "set":
            if not normalized["field"]:
                raise ValueError("A set action needs a field name.")
            operation.update(column=normalized["field"], value=normalized["new_value"])
        result.append(operation)
    return result


def _editor_fields(row: dict) -> dict:
    """Only visible repair values participate in provenance and merge matching."""
    return {field: row.get(field) for field in ("record", "action", "field", "new_value", "reason")}


def _needs_input(row: dict) -> bool:
    value = row.get("_needs_input")
    return value is not None and not pd.isna(value) and bool(value)


def _editor_frame(rows: list[dict]) -> pd.DataFrame:
    """Keep incomplete cells empty when a merged draft becomes editor input."""
    frame = pd.DataFrame(rows, columns=["record", "action", "field", "new_value", "reason", "_needs_input"])
    frame["record"] = frame["record"].astype("Int64")
    for column in ("action", "field", "new_value", "reason"):
        frame[column] = frame[column].fillna("").astype(str)
    frame["_needs_input"] = [_needs_input(row) for row in rows]
    return frame


def _row_target(row: dict) -> tuple[int | None, str, str]:
    try:
        record = int(row.get("record"))
    except (TypeError, ValueError, OverflowError):
        record = None
    return record, str(row.get("action") or ""), str(row.get("field") or "")


def _targets_conflict(left: dict, right: dict) -> bool:
    left_record, left_action, left_field = _row_target(left)
    right_record, right_action, right_field = _row_target(right)
    return left_record is not None and left_record == right_record and (
        left_action == "drop" or right_action == "drop" or left_field == right_field
    )


def _merge_assisted_rows(current: list[dict], baseline: list[dict], result: dict,
                         dismissed: list[dict] | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    """Keep current edits/deletions; append only verified operations or blank prompts."""
    rows = [dict(row) for row in current]
    excluded = [dict(row) for row in (dismissed or [])]
    current_targets = {_row_target(row) for row in current}
    for row in baseline:
        if _row_target(row) not in current_targets and _row_target(row) not in {_row_target(item) for item in excluded}:
            excluded.append(_editor_fields(row))
    known = {_fingerprint(row): operation for row, operation in zip(_plan_rows(result["operations"]), result["operations"])}
    accepted = []
    for candidate in result["rows"]:
        row = _editor_fields(candidate)
        if any(_targets_conflict(row, existing) for existing in [*rows, *excluded]):
            continue
        operation = known.get(_fingerprint(row))
        if operation is not None:
            row["_needs_input"] = False
            accepted.append(dict(operation))
        elif row["action"] == "set" and row["field"] and row["new_value"] == "" and row["reason"] == "":
            row["_needs_input"] = True
        else:
            # The UI never turns an unverified model-supplied value into a repair.
            continue
        rows.append(row)
    return rows, accepted, excluded


def _incomplete_draft_rows(rows: list[dict]) -> list[dict]:
    return [
        {"record": row.get("record"), "field": row.get("field"), "status": "Needs your input"}
        for row in rows
        if _needs_input(row) and (
            not str(row.get("reason") or "").strip()
            or row.get("action") == "set" and not str(row.get("new_value") or "").strip()
        )
    ]


def _editor_fingerprint(rows: list[dict]) -> str:
    canonical = []
    for row in rows:
        values = _editor_fields(row)
        for column in ("action", "field", "new_value", "reason"):
            value = values[column]
            values[column] = "" if value is None or pd.isna(value) else str(value)
        record = values["record"]
        values["record"] = None if record is None or pd.isna(record) else float(record)
        canonical.append({**values, "_needs_input": _needs_input(row)})
    return _fingerprint(canonical)


def _accept_value_suggestion(current: list[dict], baseline: list[dict], dismissed: list[dict],
                             suggestion: dict, provider: str, expected_editor: str) -> list[dict]:
    """Only a deliberate acceptance may insert an unverified AI value in a draft."""
    if _editor_fingerprint(current) != expected_editor:
        raise ValueError("The editor changed after this request. Review a fresh request before using a suggestion.")
    if suggestion.get("disposition") != "suggest" or suggestion.get("local_validation") != "passed" or not isinstance(suggestion.get("value"), str):
        raise ValueError("This suggestion is not available as a replacement value.")
    candidate = {"record": suggestion["record"], "action": "set", "field": suggestion["field"],
                 "new_value": suggestion["value"],
                 "reason": f"User accepted {provider} AI suggestion: {suggestion['rationale']}",
                 "_needs_input": False}
    rows, _, excluded = _merge_assisted_rows(current, baseline, {"operations": [], "rows": []}, dismissed)
    if any(_targets_conflict(candidate, item) for item in excluded):
        raise ValueError("This correction was removed from your draft. It will not be reinserted automatically.")
    matches = [index for index, row in enumerate(rows) if _targets_conflict(candidate, row)]
    if matches:
        if len(matches) != 1:
            raise ValueError("This target already has conflicting edits. Review them manually.")
        index = matches[0]
        row = rows[index]
        if not (_needs_input(row) and row.get("action") == "set" and row.get("field") == candidate["field"]
                and not str(row.get("new_value") or "").strip() and not str(row.get("reason") or "").strip()):
            raise ValueError("Your existing edit takes priority. This suggestion will not replace it.")
        rows[index] = candidate
    else:
        rows.append(candidate)
    return rows


def _value_suggestions(workflow: Workflow, job_id: str, state: dict, context: str,
                       current_rows: list[dict], baseline: list[dict], assistance: dict | None,
                       guided_pending: bool = False, guided_fingerprint: str = "",
                       displayed_binding: dict | None = None) -> None:
    """One action prepares rule repairs and optional, consented value suggestions."""
    with st.container(border=True):
        st.markdown("**Prepare your draft with AI**")
        st.caption("All affected fields are included automatically. Review the suggestions together, then edit your final corrections below.")
        provider = {"nebius": "Nebius", "fireworks": "Fireworks"}.get(state.get("mode"), "the saved provider")
        live_mode = state.get("mode") in {"nebius", "fireworks"}
        try:
            available = workflow.preview_value_request(job_id, [])
        except (ValueError, OSError):
            st.info("A value request cannot be prepared for this saved state. Manual editing is still available.")
            return
        fields = available["available_fields"]
        request = None
        if fields and live_mode:
            try:
                request = workflow.preview_value_request(job_id, fields)
            except (ValueError, OSError) as error:
                st.warning("The request cannot be prepared. Continue with manual corrections below.")
                st.text(str(error), wrap=True)
                return
            if request.get("omitted_count", 0):
                st.warning(f"The request limit is {len(request['targets'])} affected cells. {request['omitted_count']} additional cells need manual review; they are not sent.")
            with st.expander("Preview data shared with AI", expanded=False):
                st.caption("Only these affected values and rules are sent, with task instructions. Unrelated fields and unsaved edits are excluded.")
                st.json(request["payload"])
        elif live_mode:
            st.caption("No unresolved cell values need suggestions. Prepare a rule-based draft for review.")
        else:
            st.caption("This job uses offline mode. Prepare AI-assisted draft prepares local rule-backed repairs and blank prompts without calling a model.")
        store_key = f"value-suggestions-{job_id}"
        session = st.session_state.get(store_key)
        if not session or session["context"] != context:
            session = {"context": context, "epoch": 0, "result": None}
        query_scope = _fingerprint(request)
        if session.get("query_scope") != query_scope:
            session.update(query_scope=query_scope, result=None, error=None)
        editor_hash = _editor_fingerprint(current_rows)
        consent_scope = _fingerprint([request, editor_hash, guided_fingerprint])
        if session.get("consent_scope") != consent_scope:
            session.update(consent_scope=consent_scope, epoch=session["epoch"] + 1)
        st.session_state[store_key] = session
        consent = False
        if request is not None:
            consent = st.checkbox(f"Send this preview to {provider} to suggest replacement values.",
                                  key=f"value-consent-{job_id}-{consent_scope}-{session['epoch']}",
                                  disabled=guided_pending)
        if guided_pending:
            st.caption("Add or discard your unadded field changes before requesting or using AI suggestions.")
        if st.button("Prepare AI-assisted draft", disabled=guided_pending or request is not None and (not consent or not request["targets"]),
                     key=f"prepare-assistance-{job_id}-{context}"):
            try:
                with st.spinner("Preparing corrections and AI suggestions for affected fields…"):
                    draft_result = workflow.suggest_corrections(job_id)
                    if draft_result["binding"] != displayed_binding:
                        raise ValueError("The saved plan changed. Reopen the review before preparing another draft.")
                    rows, accepted, dismissed = _merge_assisted_rows(
                        current_rows, baseline, draft_result, assistance.get("dismissed") if assistance else None,
                    )
                    st.session_state[f"assisted-draft-{job_id}"] = {
                        "context": context, "version": assistance["version"] + 1 if assistance else 1,
                        "rows": rows, "operations": [*(assistance["operations"] if assistance else []), *accepted],
                        "dismissed": dismissed, "result": draft_result,
                    }
                    session.update(result=None, error=None)
                    if request is not None:
                        result = workflow.suggest_values(job_id, request, consent=True)
                        if result["binding"] != request["binding"]:
                            raise ValueError("The saved review changed. Review a fresh preview before requesting suggestions.")
                        session.update(result=result, request=request, expected_editor=_editor_fingerprint(rows), accepted=[])
            except (ValueError, OSError):
                session.update(result=None, error="The draft could not be fully prepared because the request or saved data could not be verified. Your existing edits are preserved; continue manually or review a fresh preview.")
            except Exception:
                session.update(result=None, error="AI assistance did not finish. Your existing edits are preserved. You can continue manually or review the preview and give permission to try again.")
            # A fresh widget key prevents a second request from reusing consent.
            session["epoch"] += 1
            st.session_state[store_key] = session
            st.rerun()
        if session.get("error"):
            st.warning(session["error"])
        result = session.get("result")
        if not result:
            return
        st.markdown("**AI-proposed fixes**")
        st.caption("Possible values, not verified facts. Add available suggestions to the draft, then review or edit the final corrections below.")
        if result.get("fallback"):
            st.warning(result["message"])
        stale = _editor_fingerprint(current_rows) != session["expected_editor"]
        if stale:
            st.warning("Your editor changed after these suggestions were requested. Your edits are preserved; prepare a fresh draft to use new suggestions.")
        table, usable = [], []
        for suggestion in result["suggestions"]:
            actionable = suggestion["disposition"] == "suggest" and suggestion["local_validation"] == "passed"
            status = "Needs your input"
            note = suggestion["rationale"]
            if suggestion["issue_id"] in session["accepted"]:
                status = "Added to draft"
            elif actionable:
                status = "Unverified suggestion"
                try:
                    _accept_value_suggestion(current_rows, baseline, assistance.get("dismissed", []) if assistance else [],
                                             suggestion, provider, session["expected_editor"])
                    usable.append(suggestion)
                except ValueError as error:
                    status = "Existing draft takes priority"
                    note = str(error)
            elif suggestion.get("local_validation") == "rejected":
                status = "Failed checks — enter a value"
            table.append({"Record": suggestion["record"], "Field": suggestion["field"],
                          "Current value": suggestion["current_value"],
                          "Proposed value": suggestion.get("value") or "",
                          "Status": status, "Explanation": note})
        st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")
        if any(item["disposition"] == "suggest" and item["local_validation"] == "passed" for item in result["suggestions"]):
            if st.button("Add available suggestions to draft", disabled=not usable or guided_pending or stale,
                         key=f"use-values-{job_id}-{query_scope}-{session['epoch']}"):
                try:
                    fresh_request = workflow.preview_value_request(job_id, fields)
                    if fresh_request != session["request"]:
                        raise ValueError("The saved input or plan changed. Prepare a fresh draft before adding suggestions.")
                    rows = current_rows
                    # Build the whole batch before saving it; preserve edits and intentional removals.
                    for suggestion in usable:
                        rows = _accept_value_suggestion(rows, baseline, assistance.get("dismissed", []) if assistance else [],
                                                        suggestion, provider, _editor_fingerprint(rows))
                    _, _, dismissed = _merge_assisted_rows(current_rows, baseline, {"operations": [], "rows": []},
                                                           assistance.get("dismissed", []) if assistance else [])
                    st.session_state[f"assisted-draft-{job_id}"] = {
                        "context": context, "version": assistance["version"] + 1 if assistance else 1,
                        "rows": rows, "operations": assistance["operations"] if assistance else [],
                        "dismissed": dismissed, "result": assistance.get("result") if assistance else None,
                    }
                    session["expected_editor"] = _editor_fingerprint(rows)
                    session["accepted"].extend(item["issue_id"] for item in usable)
                    st.session_state[store_key] = session
                    st.rerun()
                except (ValueError, OSError) as error:
                    st.warning("Suggestions could not be added. Your existing draft is unchanged.")
                    st.text(str(error), wrap=True)


def _transition(workflow: Workflow, job_id: str, response: dict) -> None:
    try:
        with st.spinner("Saving your decision and continuing the workflow…"):
            workflow.resume(job_id, response)
        st.rerun()
    except (ValueError, FileNotFoundError) as error:
        st.error(str(error))
    except Exception:
        st.error("The workflow could not continue. Your saved job is still available; use Retry or reopen it.")


def _show_frame(frame: pd.DataFrame) -> None:
    shown = frame.head(500).copy()
    shown.index = shown.index + 1
    shown.index.name = "record"
    st.dataframe(shown, width="stretch")
    if len(frame) > 500:
        st.caption(f"Showing the first 500 of {len(frame):,} records. Validation covers the whole file.")


def _display_issues(issues: list[dict]) -> pd.DataFrame:
    """Use the same record numbering in every customer-facing table."""
    result = pd.DataFrame(issues)
    if "row" in result:
        result.insert(0, "record", pd.to_numeric(result.pop("row"), errors="coerce").astype("Int64") + 1)
    # A drop has a whole-row dictionary while a set has a scalar cell value.
    # Give Arrow one consistent type without losing the local before/after data.
    for column in ("before", "after"):
        if column in result:
            result[column] = result[column].map(
                lambda value: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else "" if value is None else str(value)
            )
    return result


def _downloads(outputs: dict, job_dir: Path) -> None:
    """Serve only output files already created by the approved export step."""
    found = False
    for label, value in outputs.items():
        if not isinstance(value, str):
            continue
        path = Path(value)
        if not path.is_absolute():
            path = job_dir / path
        path = path.resolve()
        if not path.is_relative_to(job_dir.resolve()) or not path.is_file():
            continue
        if path.suffix not in {".csv", ".json", ".txt", ".md"}:
            continue
        found = True
        mime = {".csv": "text/csv", ".json": "application/json"}.get(path.suffix, "text/plain")
        st.download_button(
            f"Download {str(label).replace('_', ' ')}",
            data=path.read_bytes(),
            file_name=path.name,
            mime=mime,
            key=f"download-{label}-{path.name}",
        )
    if not found:
        st.info("The workflow has no approved output files available yet.")


def _upload_preview(data: bytes, filename: str, draft: dict | None = None, *, show_table: bool = True) -> tuple[ParsedImport | None, str | None]:
    """Parse locally without creating a workflow or sending anything to a model."""
    sheet = draft.get("sheet") if draft else None
    try:
        details = inspect_upload(data, filename)
        st.caption(f"Input format: {FORMAT_LABELS.get(details['format'], 'Supported table')}")
        # Uploaded filenames and worksheet names are plain text, never HTML.
        st.text(filename)
        if details.get("requires_sheet"):
            upload_key = hashlib.sha256(data).hexdigest()[:16]
            sheet = st.selectbox(
                "Worksheet to review", details["sheets"], index=details["sheets"].index(sheet) if sheet in details["sheets"] else None,
                placeholder="Choose one worksheet", key=f"upload-sheet-{upload_key}",
                help="Choose the table to inspect. The complete original workbook stays preserved.",
            )
            if sheet is None:
                st.info("Choose a worksheet to see its preview and enable job creation.")
                return None, None
        elif details.get("sheets"):
            sheet = details["sheets"][0]
            st.text(f"Worksheet: {sheet}")
        parsed = parse_upload(data, filename, sheet=sheet)
    except (ValueError, OSError) as error:
        st.error("This file could not be prepared for review.")
        st.text(str(error))
        return None, sheet
    if draft is not None:
        draft["sheet"] = sheet
    if show_table:
        _render_import_preview(parsed)
    else:
        st.caption(f"{parsed.manifest['row_count']:,} records · {parsed.manifest['column_count']:,} columns. Ready for the next step.")
    return parsed, sheet


def _render_import_preview(parsed: ParsedImport) -> None:
    st.markdown("**Imported table preview**")
    st.dataframe(parsed.preview, width="stretch", hide_index=True)
    st.caption(
        f"{parsed.manifest['row_count']:,} records · {parsed.manifest['column_count']:,} columns. "
        "Showing up to 100 records. Values are shown as text for the data-quality checks; this is not a workbook-formatting preview."
    )
    for warning in parsed.manifest.get("warnings", []):
        st.warning("Import note")
        st.text(str(warning))
    st.caption("Previewing stays local and makes no model calls. A job starts only when you choose Create job and inspect data.")


def _go(view: str) -> None:
    st.session_state["workspace_view"] = view
    st.rerun()


def _open_review(job_id: str) -> None:
    st.session_state["active_job"] = job_id
    _go("job")


def _start_draft(source: str, scenario: str | None = None) -> None:
    sequence = st.session_state.get("draft_sequence", 0) + 1
    st.session_state["draft_sequence"] = sequence
    st.session_state["review_draft"] = {
        "id": sequence, "source": source, "scenario": scenario or next(iter(SAMPLE_SCENARIOS)),
        "step": 0, "data": None, "filename": None, "sheet": None, "parsed": None,
        "use_template": True, "custom_rules": None, "rules": None, "name": "",
    }
    _go("new")


def _remember_draft_value(field: str, key: str) -> None:
    draft = st.session_state.get("review_draft")
    if draft is not None:
        draft[field] = st.session_state.get(key)
        if field == "scenario":
            draft.update(parsed=None, sheet=None, data=None, filename=None)
        elif field == "use_template":
            draft["rules"] = None


def _remember_upload(key: str, *, rules: bool = False) -> None:
    draft = st.session_state.get("review_draft")
    if draft is None:
        return
    upload = st.session_state.get(key)
    if rules:
        draft["custom_rules"] = upload.getvalue() if upload is not None else None
        draft["rules"] = None
    else:
        draft.update(data=upload.getvalue() if upload is not None else None,
                     filename=upload.name if upload is not None else None, sheet=None, parsed=None)


def _wizard_steps(step: int) -> None:
    entries = []
    for index, label in enumerate(("File", "Rules", "Preview")):
        current = ' aria-current="step"' if index == step else ""
        entries.append(f'<li{current}><span class="step-number">{index + 1}</span>{label}</li>')
    st.html('<ol class="cw-draft-steps" aria-label="New review steps">' + "".join(entries) + '</ol>')


def _new_job(workflow: Workflow, mode: str) -> None:
    draft = st.session_state.get("review_draft")
    if not draft:
        _go("hub")
        return
    if st.button("Back to workspace", key="draft-back-hub"):
        _go("hub")
    st.html('<div class="cw-hub-intro"><p class="cw-eyebrow">NEW REVIEW</p><h1>One clear step at a time.</h1><p>Your draft stays here as you move between steps.</p></div>')
    step = draft["step"]
    _wizard_steps(step)
    with st.container(border=True, key="lumen_wizard"):
        if step == 0:
            st.subheader("1. Choose your file")
            if draft["source"] == "sample":
                key = f"draft-scenario-{draft['id']}"
                scenario = st.selectbox(
                    "Sample scenario", list(SAMPLE_SCENARIOS), index=list(SAMPLE_SCENARIOS).index(draft["scenario"]),
                    key=key, on_change=_remember_draft_value, args=("scenario", key),
                )
                draft["scenario"] = scenario
                specification = SAMPLE_SCENARIOS[scenario]
                sample_path = SAMPLE_DIR / specification["file"]
                draft.update(data=sample_path.read_bytes(), filename=sample_path.name, sheet=None)
                draft["parsed"] = parse_upload(draft["data"], draft["filename"])
                st.caption(specification["description"])
                with st.expander("Preview or download this sample"):
                    st.code(sample_path.read_text(encoding="utf-8"), language="text")
                    st.download_button("Download selected sample CSV", draft["data"], sample_path.name, "text/csv")
            else:
                key = f"draft-file-{draft['id']}-{draft.get('file_version', 0)}"
                uploaded = st.file_uploader(
                    "Customer data file (up to 10 MB)", type=["csv", "tsv", "xlsx", "json", "jsonl", "ndjson"],
                    key=key, on_change=_remember_upload, args=(key,),
                    help="CSV or TSV text, an Excel worksheet, flat JSON records, or JSON Lines. Nested JSON and workbook formulas are unsupported.",
                )
                if uploaded is not None:
                    data = uploaded.getvalue()
                    if draft["data"] != data or draft["filename"] != uploaded.name:
                        draft.update(data=data, filename=uploaded.name, sheet=None, parsed=None)
                draft["parsed"] = None
                if draft["data"] is not None:
                    parsed, sheet = _upload_preview(draft["data"], draft["filename"], draft, show_table=False)
                    draft.update(parsed=parsed, sheet=sheet)
                    st.caption("Your selected file stays in this draft when you move to another step.")
                    if st.button("Remove file"):
                        draft.update(data=None, filename=None, sheet=None, parsed=None,
                                     file_version=draft.get("file_version", 0) + 1)
                        st.rerun()
                else:
                    st.caption("CSV · TSV · XLSX · JSON · JSONL · NDJSON. Choose a file to continue.")
            st.caption("This step only reads the file locally. It creates no job and makes no model calls.")
            with st.container(key="lumen_wizard_actions"):
                if st.button("Continue to rules", type="primary", disabled=draft["parsed"] is None):
                    draft["step"] = 1
                    st.rerun()
        elif step == 1:
            st.subheader("2. Define what good data looks like")
            key = f"draft-template-{draft['id']}"
            use_template = st.checkbox(
                "Use the included customer import rules", value=draft["use_template"], key=key,
                on_change=_remember_draft_value, args=("use_template", key),
            )
            draft["use_template"] = use_template
            if use_template:
                rule_bytes = (SAMPLE_DIR / "import_rules.json").read_bytes()
                st.caption("Check required fields, unique customer IDs, declared date formats, and allowed countries.")
            else:
                key = f"draft-rules-{draft['id']}-{draft.get('rules_version', 0)}"
                uploaded = st.file_uploader("Import specification (JSON)", type=["json"], key=key,
                                            on_change=_remember_upload, args=(key,), kwargs={"rules": True})
                if uploaded is not None:
                    draft["custom_rules"] = uploaded.getvalue()
                rule_bytes = draft["custom_rules"]
                if rule_bytes is not None:
                    st.caption("Your custom specification is retained in this draft.")
                    if st.button("Remove custom rules"):
                        draft.update(custom_rules=None, rules=None, rules_version=draft.get("rules_version", 0) + 1)
                        st.rerun()
            draft["rules"] = None
            if rule_bytes is not None:
                try:
                    draft["rules"] = ImportRules.model_validate(json.loads(rule_bytes)).model_dump()
                except (ValueError, UnicodeDecodeError) as error:
                    st.error("The rules need attention before you continue.")
                    st.text(str(error))
            if draft["rules"] is not None:
                with st.expander("Read or download these import rules"):
                    st.json(draft["rules"])
                    st.download_button("Download import rules", json.dumps(draft["rules"], indent=2), "import_rules.json", "application/json")
            key = f"draft-name-{draft['id']}"
            draft["name"] = st.text_input(
                "Job name", value=draft["name"], max_chars=80, key=key,
                placeholder="e.g. October customer review", on_change=_remember_draft_value, args=("name", key),
                help="Choose a unique name you will recognize. Leave blank for an automatic name.",
            )
            with st.container(key="lumen_wizard_actions"):
                back, forward = st.columns(2)
                if back.button("Back to file"):
                    draft["step"] = 0
                    st.rerun()
                if forward.button("Continue to preview", type="primary", disabled=draft["rules"] is None):
                    draft["step"] = 2
                    st.rerun()
        else:
            st.subheader("3. Preview before you create the review")
            ready = draft["parsed"] is not None and draft["rules"] is not None
            if ready:
                st.text(draft["filename"])
                if draft["sheet"]:
                    st.text(f"Worksheet: {draft['sheet']}")
                _render_import_preview(draft["parsed"])
                st.text("Review name: " + (draft["name"] or "An automatic name will be assigned"))
                st.caption("Investigation mode: " + next(label for label, value in MODE_LABELS.items() if value == mode))
                with st.expander("Rules used for this review"):
                    st.json(draft["rules"])
            else:
                st.warning("Return to File or Rules to complete this draft.")
            st.caption("Approved outputs are a cleaned CSV, an audit report, and a validation summary. The original stays preserved; repairs and export each need your approval.")
            if mode != "offline":
                st.caption("Creating the review starts the configured model investigation. It receives sanitized summaries; customer values stay local during this investigation. Optional value suggestions later require a separate preview and permission.")
            with st.container(key="lumen_wizard_actions"):
                back, create = st.columns([1, 2])
                if back.button("Back to rules"):
                    draft["step"] = 1
                    st.rerun()
                if create.button("Create job and inspect data", type="primary", disabled=not ready):
                    try:
                        with st.spinner("Checking the file and preparing the review…"):
                            if draft["source"] == "upload":
                                job_id = workflow.create_upload(draft["data"], draft["filename"], draft["rules"],
                                                                sheet=draft["sheet"], name=draft["name"].strip() or None)
                            else:
                                job_id = workflow.create(draft["data"], draft["rules"], name=draft["name"].strip() or None)
                        st.session_state.pop("review_draft", None)
                        _open_review(job_id)
                    except (ValueError, OSError) as error:
                        st.error("The review could not be created. Your draft is still available.")
                        st.text(str(error))
                    except Exception:
                        st.error("Creation did not finish. Your draft is still available; check the input and provider settings.")


def _guided_dirty(form: dict) -> bool:
    return any(form.get(name) != form["initial"].get(name) for name in ("value", "reason", "clear"))


def _remember_guided_input(store_key: str, target_key: str, field: str, widget_key: str) -> None:
    """Keep values outside widget keys so hiding a field or leaving the page is safe."""
    st.session_state[store_key]["forms"][target_key][field] = st.session_state.get(widget_key)


def _remember_guided_target(store_key: str, widget_key: str) -> None:
    st.session_state[store_key]["selected"] = st.session_state.get(widget_key)


def _guided_targets(source: pd.DataFrame, issues: list[dict], rows: list[dict]) -> dict[str, dict]:
    targets = {}
    for issue in issues:
        row, field = issue.get("row"), issue.get("column")
        if not isinstance(row, int) or not 0 <= row < len(source) or field not in source.columns:
            continue
        key = _fingerprint([row + 1, field])
        target = targets.setdefault(key, {"record": row + 1, "field": field, "issues": []})
        if issue.get("kind") not in target["issues"]:
            target["issues"].append(issue.get("kind", "needs review"))
    for row in rows:
        record, action, field = _row_target(row)
        if action != "set" or record is None or not 1 <= record <= len(source) or field not in source.columns:
            continue
        key = _fingerprint([record, field])
        targets.setdefault(key, {"record": record, "field": field, "issues": []})
    return targets


def _save_guided_rows(job_id: str, context: str, rows: list[dict], baseline: list[dict],
                      assistance: dict | None, target: dict, *, removed: bool) -> None:
    """A guided action updates the same unsaved draft used by both AI helpers."""
    _, _, dismissed = _merge_assisted_rows(rows, baseline, {"operations": [], "rows": []},
                                           assistance.get("dismissed", []) if assistance else [])
    if removed:
        if not any(_targets_conflict(target, item) for item in dismissed):
            dismissed.append(_editor_fields(target))
    else:
        dismissed = [item for item in dismissed if not _targets_conflict(target, item)]
    st.session_state[f"assisted-draft-{job_id}"] = {
        "context": context, "version": assistance["version"] + 1 if assistance else 1,
        "rows": rows, "operations": assistance["operations"] if assistance else [],
        "dismissed": dismissed, "result": assistance.get("result") if assistance else None,
    }


def _guided_corrections(workflow: Workflow, job_id: str, context: str, source: pd.DataFrame,
                        current_rows: list[dict], baseline: list[dict], assistance: dict | None) -> tuple[bool, str]:
    """Collect one rule-aware correction at a time without saving or approving it."""
    store_key = f"guided-corrections-{job_id}"
    store = st.session_state.get(store_key)
    if not store or store["context"] != context:
        store = {"context": context, "selected": None, "forms": {}, "epoch": 0, "targets": {}}
        st.session_state[store_key] = store
    rules = workflow.engine.load_rules(job_id)
    issues = workflow.engine.validate(job_id)["issues"]
    targets = _guided_targets(source, issues, current_rows)
    for key, form in store["forms"].items():
        if key not in targets and _guided_dirty(form) and key in store["targets"]:
            targets[key] = store["targets"][key]
    store["targets"] = targets
    if not targets:
        if issues:
            st.info("These issues concern a whole record, column, or file. Use the advanced repair table for a deliberate record removal, or correct the input file or rules for missing columns.")
        return False, ""
    st.markdown("**Fix a field**")
    st.caption("Choose an affected field, enter the fact you know, and add it to your draft. Dates and allowed values follow this job’s rules. Nothing is written to your file here.")
    selected_key = f"guided-target-{job_id}-{context}"
    if store["selected"] not in targets:
        store["selected"] = next(iter(targets))
    if selected_key not in st.session_state:
        st.session_state[selected_key] = store["selected"]

    def label(key):
        target = targets[key]
        description = ", ".join(item.replace("_", " ") for item in target["issues"]) or "draft correction"
        if any(_row_target(row) == (target["record"], "set", target["field"]) for row in current_rows):
            description = "in draft · " + description
        return f"Record {target['record']} · {target['field']} · {description}"

    selected = st.selectbox("Choose a field to fix", list(targets), format_func=label, key=selected_key,
                            on_change=_remember_guided_target, args=(store_key, selected_key))
    store["selected"] = selected
    target = targets[selected]
    record, field = target["record"], target["field"]
    matches = [row for row in current_rows if _row_target(row) == (record, "set", field)]
    draft = matches[-1] if matches else None
    dropped = any(_row_target(row)[:2] == (record, "drop") for row in current_rows)
    original = str(source.iloc[record - 1][field])
    current = str(draft.get("new_value") or "") if draft else original
    spec = correction_spec(field, rules, current)
    version = _fingerprint([_editor_fields(draft) if draft else None, original, spec])
    form = store["forms"].get(selected)
    if form is None or form["version"] != version and not _guided_dirty(form):
        value = spec["date_value"] if spec["kind"] == "date" else spec["selected_value"] if spec["kind"] == "category" else current
        initial = {"value": value, "reason": str(draft.get("reason") or "") if draft else "",
                   "clear": bool(draft and current == "" and not spec["required"] and not _needs_input(draft))}
        store["epoch"] += 1
        form = {**initial, "initial": dict(initial), "version": version, "epoch": store["epoch"]}
        store["forms"][selected] = form
    stale = form["version"] != version
    with st.container(border=True):
        left, right = st.columns(2)
        with left:
            st.caption("Original value")
            st.text(original if original else "(empty)")
        with right:
            st.caption("Value currently in your draft")
            st.text(current if draft and current else "(empty)" if draft else "No correction added yet")
        st.caption(spec["help"])
        if dropped:
            st.warning("This record is already marked for removal. Remove that drop action in the advanced table before changing an individual field.")
        if len(matches) > 1:
            st.warning("This field has more than one draft operation. Resolve the duplicate operations in the advanced table before using this form.")
        if stale:
            st.warning("This field changed elsewhere in your draft while you were editing it. Your unadded input is preserved. Discard it to load the updated draft value.")
        widget_prefix = f"guided-{job_id}-{context}-{selected}-{form['epoch']}"
        value_key, reason_key, clear_key = (f"{widget_prefix}-{name}" for name in ("value", "reason", "clear"))
        for key, name in ((value_key, "value"), (reason_key, "reason"), (clear_key, "clear")):
            if key not in st.session_state:
                st.session_state[key] = form[name]
        disabled = dropped or len(matches) > 1 or stale
        if not spec["required"]:
            st.checkbox("Leave this optional field blank", key=clear_key, disabled=disabled,
                        on_change=_remember_guided_input, args=(store_key, selected, "clear", clear_key))
        if spec["kind"] == "date":
            st.date_input("New date", min_value=date.min, max_value=date.max, format="YYYY-MM-DD",
                          key=value_key, disabled=disabled or form["clear"],
                          on_change=_remember_guided_input, args=(store_key, selected, "value", value_key))
        elif spec["kind"] == "category":
            st.selectbox("New value", spec["options"], index=None, placeholder="Choose an allowed value",
                         key=value_key, disabled=disabled or form["clear"],
                         on_change=_remember_guided_input, args=(store_key, selected, "value", value_key))
        else:
            st.text_input("New value", key=value_key, disabled=disabled or form["clear"],
                          on_change=_remember_guided_input, args=(store_key, selected, "value", value_key))
        serialized, problem = None, None
        try:
            serialized = correction_value(spec, None if form["clear"] else form["value"], allow_blank=bool(form["clear"]))
        except ValueError as error:
            problem = str(error)
        if serialized is not None:
            st.caption("Value that will be written after approval")
            st.text(serialized if serialized else "(empty)")
        elif problem:
            st.caption(problem)
        st.text_input("Why is this correct?", key=reason_key, placeholder="For example: checked against the source record",
                      disabled=disabled, on_change=_remember_guided_input,
                      args=(store_key, selected, "reason", reason_key))
        st.caption("A reason is required. Changing a control does not add or approve a repair.")
        first, second, third = st.columns(3)
        with first:
            action = "Update correction in draft" if draft else "Add correction to draft"
            if st.button(action, key=f"{widget_prefix}-add", type="primary",
                         disabled=disabled or serialized is None or not str(form["reason"] or "").strip()):
                new_row = {"record": record, "action": "set", "field": field, "new_value": serialized,
                           "reason": str(form["reason"]).strip(), "_needs_input": False}
                rows = [dict(row) for row in current_rows if _row_target(row) != (record, "set", field)]
                rows.append(new_row)
                _save_guided_rows(job_id, context, rows, baseline, assistance, new_row, removed=False)
                store["forms"].pop(selected, None)
                st.rerun()
        with second:
            if st.button("Discard unadded changes", key=f"{widget_prefix}-discard", disabled=not _guided_dirty(form) and not stale):
                store["forms"].pop(selected, None)
                st.rerun()
        with third:
            if st.button("Remove draft correction", key=f"{widget_prefix}-remove", disabled=draft is None or _guided_dirty(form)):
                rows = [dict(row) for row in current_rows if _row_target(row) != (record, "set", field)]
                _save_guided_rows(job_id, context, rows, baseline, assistance,
                                  {"record": record, "action": "set", "field": field}, removed=True)
                store["forms"].pop(selected, None)
                st.rerun()
    pending = [(key, value) for key, value in store["forms"].items() if _guided_dirty(value)]
    if pending:
        locations = [f"Record {targets[key]['record']} · {targets[key]['field']}" for key, _ in pending if key in targets]
        st.warning("Unadded changes: " + "; ".join(locations) + ". Add each correction to the draft or discard it before submitting, approving, or using AI assistance.")
    return bool(pending), _fingerprint({key: {name: value.get(name) for name in ("value", "reason", "clear")} for key, value in store["forms"].items()})


def _repair_review(workflow: Workflow, job_id: str, state: dict, pending: dict, source: pd.DataFrame) -> None:
    is_clarification = pending.get("kind") == "clarification"
    st.subheader("3. Supply missing knowledge" if is_clarification else "3. Review the exact repairs")
    if is_clarification:
        st.info("Some values cannot be inferred safely. Add a factual replacement you know, or explicitly remove the affected record. The agent will ask for repair approval afterward.")
    else:
        st.write("Review the proposed changes and their preview. Approval applies to this exact saved plan.")
    plan = pending.get("plan", state.get("plan", []))
    if not plan and not is_clarification:
        st.info("This file needs no proposed repairs. Confirm an unchanged staged copy, then review export separately.")
    st.caption("Record 1 is the first data record in the imported table. Identifier fields stay as text, preserving leading zeros.")
    saved_preview = pending.get("preview", state.get("preview", {}))
    displayed_binding = pending.get("binding") or {
        "job_id": job_id, **{key: saved_preview.get(key) for key in ("source_hash", "rules_hash", "plan_hash")}
    }
    context = _fingerprint([displayed_binding, pending.get("kind"), state.get("revisions", 0)])
    draft_key = f"assisted-draft-{job_id}"
    assistance = st.session_state.get(draft_key)
    if assistance and assistance["context"] != context:
        st.session_state.pop(draft_key, None)
        assistance = None
    baseline = assistance["rows"] if assistance else _plan_rows(plan)
    merge_baseline = baseline
    editor_key = f"plan-{job_id}-{context}-{assistance['version'] if assistance else 0}"
    cache_key = f"repair-editor-cache-{job_id}"
    editor_cache = st.session_state.get(cache_key)
    if editor_cache and editor_cache["key"] == editor_key:
        # The widget disappears during workspace navigation. Rehydrate its latest
        # rows once, rather than replaying old editor deltas against a new frame.
        baseline = editor_cache["input"] if editor_key in st.session_state else editor_cache["rows"]
    guided_panel = st.container()
    ai_panel = st.container()
    with st.container():
        st.markdown("**Final corrections — editable draft**")
        st.caption("Edit New value and Reason directly. ‘set’ changes a field; ‘drop’ removes a record. Nothing is written until you submit and approve.")
        edited = st.data_editor(
            _editor_frame(baseline),
            num_rows="dynamic",
            hide_index=True,
            width="stretch",
            key=editor_key,
            disabled=["_needs_input"],
            column_config={
                "record": st.column_config.NumberColumn("Record", min_value=1, max_value=max(1, len(source)), step=1, required=True),
                "action": st.column_config.SelectboxColumn("Action", options=["set", "drop"], required=True),
                "field": st.column_config.SelectboxColumn("Field", options=[""] + list(source.columns)),
                "new_value": st.column_config.TextColumn("New value"),
                "reason": st.column_config.TextColumn("Reason", required=True),
                "_needs_input": None,
            },
        )
    current_rows = edited.astype(object).where(pd.notnull(edited), None).to_dict("records")
    st.session_state[cache_key] = {"key": editor_key, "input": baseline, "rows": current_rows}
    # Widget rehydration must not erase evidence of an intentionally removed row.
    baseline = merge_baseline
    with guided_panel:
        with st.expander("Optional: Fix individual fields", expanded=False):
            guided_pending, guided_fingerprint = _guided_corrections(workflow, job_id, context, source, current_rows, baseline, assistance)
        if guided_pending:
            st.warning("You have unadded field corrections. Expand ‘Optional: Fix individual fields’ to add or discard them before continuing.")
        guided_progress = st.empty()
    with ai_panel:
        if assistance and (assistance.get("result") or {}).get("fallback"):
            st.warning(assistance["result"]["message"])
        _value_suggestions(workflow, job_id, state, context, current_rows, baseline, assistance,
                           guided_pending=guided_pending, guided_fingerprint=guided_fingerprint,
                           displayed_binding=displayed_binding)
    incomplete = _incomplete_draft_rows(current_rows)
    if incomplete:
        st.caption("Fill the blank New value and Reason cells above, or remove unwanted draft rows. Blank prompts cannot be submitted.")
    current_plan = None
    preview = None
    try:
        current_plan = _edited_plan(current_rows, [*plan, *(assistance["operations"] if assistance else [])])
        preview = workflow.engine.preview(job_id, current_plan)
    except (ValueError, KeyError, TypeError) as error:
        st.warning(f"Adjust the plan before continuing: {error}")
        if incomplete:
            completed_rows = [row for row in current_rows if not (
                _needs_input(row) and (not str(row.get("reason") or "").strip()
                                      or row.get("action") == "set" and not str(row.get("new_value") or "").strip())
            )]
            try:
                completed = _edited_plan(completed_rows, [*plan, *(assistance["operations"] if assistance else [])])
                preview = workflow.engine.preview(job_id, completed)
                st.caption("The preview includes completed draft corrections only. Fill or remove the unfinished prompts before submitting.")
            except (ValueError, KeyError, TypeError):
                pass
    if preview is not None:
        count = preview.get("blocking_count", "—")
        guided_progress.caption(f"Draft preview: {count} blocking issues remain. Only corrections added to the draft are included.")
        st.markdown("**Preview only — the source has not been changed.**")
        diff = preview.get("diff", preview.get("changes", []))
        if diff:
            st.dataframe(_display_issues(diff), width="stretch", hide_index=True)
        else:
            st.caption("No field or row changes in this plan.")
        st.metric("Blocking issues after this proposal", preview.get("blocking_count", "—"))
        validation = preview.get("validation", preview.get("findings", {}))
        with st.expander("Checks after the proposed repairs", expanded=False):
            st.json(validation)
    changed = current_plan is not None and _fingerprint(current_plan) != _fingerprint(plan)
    left, right = st.columns([3, 1])
    with left:
        if is_clarification or changed or incomplete:
            if st.button("Submit revised plan for review", type="primary", disabled=current_plan is None or preview is None or guided_pending):
                _transition(workflow, job_id, {"action": "revise", "plan": current_plan})
            st.caption("This saves your proposal and prepares a new preview. It does not approve a data write.")
        else:
            consent_text = "I approve this exact plan and writing its changes to a staged copy." if plan else "I approve creating an unchanged staged copy for validation."
            binding_key = _fingerprint(pending["binding"])
            consent = st.checkbox(consent_text, key=f"repair-consent-{job_id}-{binding_key}", disabled=guided_pending)
            button_text = "Approve repairs and validate the copy" if plan else "Confirm unchanged copy"
            if st.button(button_text, type="primary", disabled=not consent or preview is None or guided_pending, key=f"repair-approve-{job_id}-{binding_key}"):
                _transition(workflow, job_id, {"action": "approve", "binding": pending["binding"]})
    with right:
        if st.button("Cancel job"):
            _transition(workflow, job_id, {"action": "cancel"})


def _current_findings(workflow: Workflow, job_id: str, state: dict, pending: dict | None) -> tuple[dict | None, str]:
    """Use one freshly verified local result for both the scorecard and table."""
    caption = "Original file — local rule checks"
    try:
        if pending and pending.get("kind") in {"clarification", "repair_approval"}:
            caption = "After the saved repair proposal"
            result = workflow.engine.preview(job_id, pending.get("plan", state.get("plan", [])))["validation"]
        elif state.get("status") in {"awaiting_export_approval", "complete"}:
            caption = "In the staged copy"
            result = workflow.engine.validate(job_id, staged=True)
        else:
            result = workflow.engine.validate(job_id)
        if not isinstance(result, dict) or not isinstance(result.get("issues"), list):
            return None, caption
        if not isinstance(result.get("blocking_count"), int) or result["blocking_count"] < 0:
            return None, caption
        return result, caption
    except (ValueError, OSError, KeyError, TypeError):
        return None, caption


def _show_job(workflow: Workflow, job_id: str) -> None:
    try:
        snapshot = workflow.snapshot(job_id)
        state = snapshot["state"]
        pending = snapshot.get("pending")
        source = workflow.engine.read_frame(job_id)
        name = workflow.job_name(job_id)
        source_details = workflow.engine.source_details(job_id)
    except (ValueError, FileNotFoundError):
        st.error("This job could not be opened. Choose a saved job or start a new review.")
        return
    status = state.get("status", "investigating")
    status_label = STATUS_LABELS.get(status, status.replace("_", " ").capitalize())
    provider_label = next((label for label, value in MODE_LABELS.items() if value == state.get("mode")), "Offline demonstration")
    render_job_header(name, status_label, provider_label)
    if source_details.get("imported"):
        st.caption(f"Original format: {FORMAT_LABELS.get(source_details.get('format'), 'Uploaded table')}")
        if source_details.get("sheet"):
            st.text(f"Worksheet: {source_details['sheet']}")
    reset_explanation, reset_action = st.columns([4, 1])
    with reset_explanation:
        st.caption("Reset starts a fresh run from this job's original file and rules, using its original investigation mode. This run and its results stay saved.")
    with reset_action:
        if st.button("Reset job", key=f"reset-{job_id}", width="stretch"):
            try:
                with st.spinner("Starting a fresh review from the original data…"):
                    fresh_job_id = workflow.reset_job(job_id)
                st.session_state["active_job"] = fresh_job_id
                st.rerun()
            except (ValueError, OSError) as error:
                st.error(f"Reset could not start: {error}")
            except Exception:
                st.error("A fresh run could not be started. This job and its saved results are still available.")
    render_workflow_progress(status)
    shown_findings, blocker_caption = _current_findings(workflow, job_id, state, pending)
    render_summary_metrics(
        records=len(source),
        blockers=shown_findings["blocking_count"] if shown_findings is not None else None,
        changes=len(state.get("plan", [])),
        blocker_caption=blocker_caption,
    )
    if shown_findings is None:
        st.warning("The blocking-issue count is unavailable because local validation could not be verified. This does not mean there are zero issues.")
    if state.get("error"):
        st.warning(state["error"])
    if state.get("manual_recovery"):
        st.info("You are entering corrections manually after an unsuccessful investigation. No additional model request was made to open this editor. AI assistance is optional; the saved investigation mode is unchanged. Repairs and export still need your approval.")
    source_tab, findings_tab, progress_tab = st.tabs(["Original data", "Detected issues", "How this workflow works"])
    with source_tab:
        if source_details.get("imported"):
            st.caption("This is the imported text table used for checks. The original uploaded file is preserved separately.")
            try:
                original = workflow.engine.original_upload(job_id)
                st.download_button(
                    "Download original upload", original["data"], original["filename"], original["mime"],
                    key=f"original-upload-{job_id}",
                )
                manifest = workflow.engine.import_manifest(job_id)
                st.download_button("Download import details", json.dumps(manifest, indent=2), "import-manifest.json",
                                   "application/json", key=f"import-details-{job_id}")
            except (ValueError, OSError):
                st.error("The original upload could not be verified, so its download is unavailable.")
        _show_frame(source)
    with findings_tab:
        issues = shown_findings["issues"] if shown_findings is not None else []
        st.caption(blocker_caption)
        if shown_findings is None:
            st.info("Issue details are unavailable until the local checks can be verified.")
        elif issues:
            st.dataframe(_display_issues(issues), width="stretch", hide_index=True)
            st.caption("Record numbers start at 1, after the CSV header. Missing record numbers indicate a whole-file or column issue.")
        else:
            st.success("No blocking issues were reported for this stage.")
        if shown_findings is not None:
            with st.expander("Validation details"):
                st.json(shown_findings)
    with progress_tab:
        st.write("1. Python inspects the data and evaluates explicit rules.\n\n2. The investigation step uses read tools to build a proposal. Missing facts come back to you.\n\n3. You review a preview and approve the exact repairs.\n\n4. Python writes a separate copy and checks it again.\n\n5. You approve export, then download the CSV and audit report.")
        if state.get("mode", "offline") == "offline":
            st.info("Offline mode uses the actual LangGraph workflow with deterministic proposals. It makes no language-model calls; select a configured provider for model-led investigation.")
        if state.get("agent_summary"):
            st.write(state["agent_summary"])
        if state.get("events"):
            st.markdown("**Investigation history**")
            st.dataframe(pd.DataFrame(state["events"]), width="stretch", hide_index=True)
            st.caption("This investigation history contains operation names and counts. Investigation and tracing payloads exclude customer cell values. Optional replacement-value requests share only the selected data you preview and permit separately.")
        if state.get("tracing_recorded"):
            st.caption("LangSmith: aggregate investigation summary submitted. Full customer-data traces are disabled.")
        elif os.getenv("DQ_LANGSMITH_TRACING", "false").lower() == "true":
            st.warning("LangSmith summary tracing is unavailable for this run. Local progress and approval controls remain active.")
        else:
            st.caption("LangSmith: disabled. Local investigation history is available above.")
    if pending and pending.get("kind") in {"clarification", "repair_approval"}:
        _repair_review(workflow, job_id, state, pending, source)
    elif pending and pending.get("kind") == "export_approval":
        st.subheader("4. Review the validated result")
        try:
            _show_frame(workflow.engine.read_frame(job_id, staged=True))
        except (ValueError, OSError):
            st.error("The saved result could not be verified. Export is unavailable; restore the job's files or create a new job.")
            return
        st.caption("Passing the configured rules establishes import-format conformance; it does not verify every customer fact.")
        binding_key = _fingerprint(pending["binding"])
        consent = st.checkbox("I approve creating the final CSV, audit report, and validation summary.", key=f"export-consent-{job_id}-{binding_key}")
        if st.button("Approve export", type="primary", disabled=not consent, key=f"export-approve-{job_id}-{binding_key}"):
            _transition(workflow, job_id, {"action": "approve", "binding": pending["binding"]})
        if st.button("Cancel without export"):
            _transition(workflow, job_id, {"action": "cancel"})
    elif status == "complete":
        try:
            _show_frame(workflow.engine.read_frame(job_id, staged=True))
            outputs = workflow.engine.verify_export(job_id)
        except (ValueError, OSError):
            st.error("The saved result could not be verified. Downloads are unavailable; restore the job's files or create a new job.")
            return
        st.success("The approved file passed all configured blocking checks. Your original upload is preserved.")
        _downloads(outputs, workflow.engine.job_dir(job_id))
    elif status == "cancelled":
        st.info("This job is cancelled. Its files and recorded decisions remain available until you delete it.")
    elif status == "blocked" or snapshot.get("next"):
        try:
            can_continue_manually = workflow.can_continue_manually(job_id)
        except (ValueError, OSError):
            can_continue_manually = False
        if can_continue_manually:
            st.info("The automatic investigation did not finish. Your original data is unchanged. You can enter corrections you know without another model request; repairs and export will still need your approval.")
            if st.button("Continue with manual corrections", type="primary"):
                try:
                    with st.spinner("Opening the correction editor with verified local checks…"):
                        workflow.continue_manually(job_id)
                    st.rerun()
                except (ValueError, OSError) as error:
                    st.error("Manual correction could not start. The saved review remains available.")
                    st.text(str(error))
        if can_continue_manually:
            st.caption("Retry starts another automatic investigation using this review's saved mode. Manual continuation makes no new model call.")
        else:
            st.info("Review the reason above before retrying. Missing facts or conflicting rules may need a corrected input and a new job.")
        if st.button("Retry from saved progress"):
            try:
                with st.spinner("Resuming from saved progress…"):
                    workflow.retry(job_id)
                st.rerun()
            except Exception:
                st.error("Retry did not complete. The job remains saved. Check the configuration and input.")


def _reset_review(workflow: Workflow, job_id: str) -> None:
    try:
        with st.spinner("Starting a fresh review from the original data…"):
            fresh_id = workflow.reset_job(job_id)
        _open_review(fresh_id)
    except (ValueError, OSError) as error:
        st.error("Reset could not start. The previous review stays saved.")
        st.text(str(error))
    except Exception:
        st.error("A fresh run could not be started. The previous review and its results remain available.")


def _saved_reviews(workflow: Workflow, jobs: list[dict]) -> None:
    with st.container(key="lumen_saved_reviews"):
        st.subheader("Pick up where you left off")
        st.caption("Your data, decisions, and results — together.")
        with st.container(key="lumen_saved_filters"):
            search_column, filter_column = st.columns([1, 2])
            search = search_column.text_input("Search saved reviews", placeholder="Search your reviews…", key="review_search")
            status_filter = filter_column.segmented_control(
                "Review status", ["All reviews", "Needs attention", "Completed"], default="All reviews", required=True,
                key="review_status_filter",
            )
        attention = {"awaiting_clarification", "awaiting_repair_approval", "awaiting_export_approval", "blocked"}
        shown = [job for job in jobs if search.strip().casefold() in job["name"].casefold()
                 and (status_filter == "All reviews" or status_filter == "Completed" and job["status"] == "complete"
                      or status_filter == "Needs attention" and job["status"] in attention)]
        st.caption(f"{len(shown)} of {len(jobs)} saved reviews")
        if not jobs:
            st.info("Your first saved review will appear here. Start with your file or a fictional sample above.")
        elif not shown:
            st.info("No reviews match this search and status filter.")
        for job in shown:
            with st.container(border=True, key=f"lumen_review_row_{job['job_id']}"):
                details, status, actions = st.columns([3, 2, 2])
                with details:
                    st.html(f'<div class="cw-review-name">{html.escape(job["name"])}</div>'
                            f'<div class="cw-review-meta">{int(job.get("row_count", 0)):,} original records · Saved locally</div>')
                with status:
                    st.caption(STATUS_LABELS.get(job["status"], job["status"].replace("_", " ").capitalize()))
                with actions:
                    proceed, reset = st.columns([2, 1])
                    label = "View results" if job["status"] == "complete" else "Continue review"
                    if proceed.button(label, key=f"review-open-{job['job_id']}", width="stretch"):
                        _open_review(job["job_id"])
                    if reset.button("Reset", key=f"review-reset-{job['job_id']}", width="stretch",
                                    help="Start a fresh run from the originals. Keep this review and its results."):
                        _reset_review(workflow, job["job_id"])
        if jobs:
            st.caption("Reset starts a fresh run using the original file, rules, and investigation mode. Earlier results remain saved.")


def _review_hub(workflow: Workflow, jobs: list[dict], *, saved_only: bool = False) -> None:
    if not saved_only:
        st.html('<div class="cw-hub-intro"><p class="cw-eyebrow">YOUR REVIEW HUB</p>'
                '<h1>A clear path to better data.</h1><p>Start a review, explore a sample, or continue where you left off.</p></div>')
        with st.container(key="lumen_hub_actions"):
            own_file, sample = st.columns([1.2, 1], gap="large")
            with own_file, st.container(border=True, key="lumen_review_card"):
                st.subheader("Review my file")
                st.write("Bring your data and rules. See every proposed change before it happens.")
                if st.button("Start a review", type="primary"):
                    _start_draft("upload")
                st.caption("CSV · TSV · XLSX · JSON · JSONL · NDJSON")
            with sample, st.container(border=True, key="lumen_sample_card"):
                st.subheader("Try a sample")
                st.write("Learn with fictional data. Choose a successful repair or a case that needs your knowledge.")
                positive, negative = st.columns(2)
                if positive.button("Positive test", width="stretch"):
                    _start_draft("sample", "Positive test — rule-based repairs")
                if negative.button("Negative test", width="stretch"):
                    _start_draft("sample", "Negative test — needs your knowledge")
                st.caption("Fresh run each time · Earlier results stay saved")
        if st.session_state.get("review_draft"):
            st.caption("You have an unfinished draft. Continue it without uploading the file again.")
            if st.button("Continue draft"):
                _go("new")
    else:
        st.html('<div class="cw-hub-intro"><p class="cw-eyebrow">SAVED REVIEWS</p><h1>Your progress, ready when you are.</h1></div>')
    _saved_reviews(workflow, jobs)
    st.caption("Originals preserved. Every change reviewed. Resume or start fresh.")


def _remember_mode() -> None:
    st.session_state["investigation_mode"] = MODE_LABELS[st.session_state["mode_selector"]]


def _settings(workflow: Workflow, mode: str) -> None:
    st.title("Workspace settings")
    st.caption("Choose how new reviews investigate issues, or open an existing review by name.")
    with st.container(border=True, key="lumen_workspace_tools"):
        selected = st.selectbox(
            "Investigation mode for new jobs", list(MODE_LABELS), index=list(MODE_LABELS.values()).index(mode),
            key="mode_selector", on_change=_remember_mode,
        )
        selected_mode = MODE_LABELS[selected]
        st.session_state["investigation_mode"] = selected_mode
        if selected_mode == "offline":
            st.caption("Runs locally without an API key. No AI model is called.")
        else:
            key_name = "NEBIUS_API_KEY" if selected_mode == "nebius" else "FIREWORKS_API_KEY"
            st.caption(f"Provider credentials: {'configured' if os.getenv(key_name) else 'not configured'}")
        st.caption("This setting applies to new reviews. Saved reviews and reset runs keep their original investigation mode.")
        st.divider()
        with st.form("resume_job"):
            lookup = st.text_input("Open by job name", placeholder="Review name or an older job ID")
            if st.form_submit_button("Open by name"):
                try:
                    _open_review(workflow.resolve_job(lookup))
                except ValueError as error:
                    st.error(str(error))
        st.caption("Names are unique and can be changed in Manage this job. Older job IDs also work in the name field.")


def _manage_job(workflow: Workflow, job_id: str) -> None:
    with st.expander("Manage this job"):
        try:
            name = workflow.job_name(job_id)
        except (ValueError, OSError):
            return
        with st.form(f"rename-{job_id}"):
            revised_name = st.text_input("Rename job", value=name, max_chars=80)
            if st.form_submit_button("Save name"):
                try:
                    workflow.rename_job(job_id, revised_name)
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))
        st.divider()
        st.caption("Deleting a job permanently removes its source, results, and saved decisions.")
        confirm = st.checkbox("Delete all local data for this job", key=f"delete-confirm-{job_id}")
        if st.button("Permanently delete job", disabled=not confirm):
            try:
                workflow.delete(job_id)
                st.session_state.pop("active_job", None)
                st.session_state["workspace_view"] = "hub"
                st.rerun()
            except Exception:
                st.error("The job could not be fully deleted. Close any open files and try again.")


def main() -> None:
    load_dotenv(PROJECT_DIR / ".env")
    landing = st.query_params.get("view", "landing") != "workspace"
    initial_appearance = "Light" if st.query_params.get("appearance") == "light" else "Dark"
    st.set_page_config(page_title=f"{BRAND_NAME} · Data Quality Agent", page_icon="✦", layout="wide", initial_sidebar_state="collapsed")
    theme = str(st.session_state.get("appearance", initial_appearance)).lower()
    apply_theme(theme=theme, landing=landing)
    with st.container(key="lumen_masthead"):
        identity_column, appearance_column = st.columns([3, 1])
        with identity_column:
            render_brand()
        with appearance_column:
            appearance = st.segmented_control(
                "Appearance", ["Dark", "Light"], default=initial_appearance, required=True,
                key="appearance", help="Change the look of your workspace. Your job and saved progress stay the same.",
            )
            theme = str(appearance).lower()
    st.query_params["appearance"] = theme
    if landing:
        render_landing(saved_count=0, theme=theme)
        return
    configured_mode = os.getenv("DQ_PROVIDER", "offline").lower()
    mode = st.session_state.get("investigation_mode", configured_mode if configured_mode in MODE_LABELS.values() else "offline")
    data_dir = str(Path(os.getenv("DQ_DATA_DIR", str(PROJECT_DIR / ".data"))).resolve())
    workflow = get_workflow(data_dir, mode)
    view = st.session_state.get("workspace_view", "hub")
    with st.container(key="lumen_workspace_nav"):
        workspace, saved, settings, product = st.columns([2, 2, 2, 3])
        if workspace.button("Workspace", type="primary" if view == "hub" else "secondary", width="stretch"):
            _go("hub")
        if saved.button("Saved reviews", type="primary" if view == "saved" else "secondary", width="stretch"):
            _go("saved")
        if settings.button("Settings", type="primary" if view == "settings" else "secondary", width="stretch"):
            _go("settings")
        if product.button("Back to product", width="stretch"):
            st.query_params["view"] = "landing"
            st.rerun()
    if view == "new":
        _new_job(workflow, mode)
    elif view == "settings":
        _settings(workflow, mode)
    elif view == "job" and st.session_state.get("active_job"):
        if st.button("Back to workspace", key="job-back-hub"):
            _go("hub")
        job_id = st.session_state["active_job"]
        _show_job(workflow, job_id)
        _manage_job(workflow, job_id)
    else:
        _review_hub(workflow, workflow.list_named_jobs(), saved_only=view == "saved")


if __name__ == "__main__":
    main()
