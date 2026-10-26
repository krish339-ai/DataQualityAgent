"""Deterministic data operations. No model, network, or generated code runs here.

Rows in repair plans are zero-based positions in the immutable original upload.
All validation issues are blocking in this first release. Raw data and audit diffs
are local-only; callers must redact them before making model or tracing requests.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from dq_agent.schemas import ImportRules, RepairOperation


MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 100_000


class DataQualityError(ValueError):
    """An actionable, expected input/approval/validation failure."""


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic(path: Path, data: bytes) -> None:
    # A short independent name avoids the Windows 260-character path limit
    # inside long project and pytest directories.
    temporary = path.with_name(f".tmp-{uuid.uuid4().hex}")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_csv(data: bytes) -> pd.DataFrame:
    if not data or len(data) > MAX_BYTES:
        raise DataQualityError("Upload a nonempty CSV no larger than 10 MB.")
    try:
        decoded = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DataQualityError("CSV must use UTF-8 encoding (a UTF-8 BOM is supported).") from exc
    if "\x00" in decoded:
        raise DataQualityError("CSV contains a NUL character; supply a text CSV.")
    try:
        csv.field_size_limit(MAX_BYTES)
        reader = csv.reader(io.StringIO(decoded, newline=""), strict=True)
        headers = next(reader, None)
        if not headers or any(not header.strip() for header in headers):
            raise DataQualityError("CSV needs nonblank column headers.")
        if len(headers) != len(set(headers)):
            raise DataQualityError("CSV column headers must be unique.")
        rows = []
        for position, row in enumerate(reader):
            if position >= MAX_ROWS:
                raise DataQualityError("CSV must contain at most 100,000 data rows.")
            # An empty physical record is retained as a completely empty data row.
            if row == []:
                row = [""] * len(headers)
            if len(row) != len(headers):
                raise DataQualityError(f"Data row {position + 1} has {len(row)} fields; expected {len(headers)}.")
            rows.append(row)
    except csv.Error as exc:
        raise DataQualityError("CSV quoting is malformed or a field exceeds the parser limit.") from exc
    if not rows:
        raise DataQualityError("CSV must contain at least one data row.")
    return pd.DataFrame(rows, columns=headers, dtype=str)


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False, lineterminator="\n", quoting=csv.QUOTE_MINIMAL).encode("utf-8")


def _date(value: str, fmt: str) -> datetime | None:
    try:
        parsed = datetime.strptime(value, fmt)
        return parsed if parsed.strftime(fmt) == value else None
    except ValueError:
        return None


def _formula(value: str) -> bool:
    return value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n"))


def _email(value: str) -> bool:
    """Practical ASCII mailbox syntax, not a deliverability or identity check."""
    if len(value) > 254 or value.count("@") != 1:
        return False
    local, domain = value.split("@")
    if not 1 <= len(local) <= 64 or local.startswith(".") or local.endswith(".") or ".." in local:
        return False
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+", local):
        return False
    labels = domain.split(".")
    return len(labels) >= 2 and all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in labels) and bool(re.fullmatch(r"[A-Za-z]{2,63}", labels[-1]))


class Engine:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: str) -> Path:
        try:
            parsed = str(uuid.UUID(job_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise DataQualityError("Invalid job identifier.") from exc
        if parsed != job_id:
            raise DataQualityError("Invalid job identifier.")
        candidate = self.root / job_id
        if candidate.is_symlink() or candidate.resolve().parent != self.root:
            raise DataQualityError("Job path is outside the local job store.")
        return candidate

    def _path(self, job_id: str, filename: str) -> Path:
        directory = self.job_dir(job_id)
        if Path(filename).name != filename or filename in (".", ".."):
            raise DataQualityError("Invalid job artifact path.")
        path = directory / filename
        if path.is_symlink() or path.resolve().parent != directory:
            raise DataQualityError("Job artifact path is outside the job folder.")
        return path

    def create_job(self, csv_bytes: bytes, rules: dict) -> str:
        frame = _parse_csv(csv_bytes)
        try:
            normalized_rules = ImportRules.model_validate(rules).model_dump()
        except ValueError as exc:
            raise DataQualityError(f"Invalid import rules: {exc}") from exc
        rule_bytes = _json_bytes(normalized_rules)
        job_id = str(uuid.uuid4())
        directory = self.job_dir(job_id)
        directory.mkdir()
        try:
            _atomic(directory / "source.csv", csv_bytes)
            _atomic(directory / "rules.json", rule_bytes)
            _atomic(directory / "metadata.json", _json_bytes({
                "job_id": job_id, "created_at": _now(), "source_hash": _hash(csv_bytes),
                "rules_hash": _hash(rule_bytes), "row_count": len(frame),
                "column_count": len(frame.columns),
            }))
        except Exception:
            shutil.rmtree(directory)
            raise
        return job_id

    def create_import(self, csv_bytes: bytes, rules: dict, original_bytes: bytes, manifest: dict) -> str:
        """Store the uploaded file and its parser recipe beside the working CSV."""
        if not isinstance(original_bytes, bytes) or not original_bytes or len(original_bytes) > MAX_BYTES:
            raise DataQualityError("Upload a nonempty source file no larger than 10 MB.")
        frame = _parse_csv(csv_bytes)
        self._validate_import_manifest(manifest, frame)
        manifest_bytes = _json_bytes(manifest)
        job_id = self.create_job(csv_bytes, rules)
        try:
            _atomic(self._path(job_id, "original.bin"), original_bytes)
            _atomic(self._path(job_id, "manifest.json"), manifest_bytes)
            metadata = self.metadata(job_id)
            metadata.update({"import_version": 1, "original_hash": _hash(original_bytes),
                             "manifest_hash": _hash(manifest_bytes)})
            # This metadata update commits provenance before any graph starts.
            _atomic(self._path(job_id, "metadata.json"), _json_bytes(metadata))
        except Exception:
            self.delete_job(job_id)
            raise
        return job_id

    @staticmethod
    def _validate_import_manifest(manifest: dict, frame: pd.DataFrame) -> None:
        if not isinstance(manifest, dict) or manifest.get("version") != 1:
            raise DataQualityError("Unsupported import manifest version.")
        if manifest.get("format") not in {"csv", "tsv", "xlsx", "json", "jsonl", "ndjson"}:
            raise DataQualityError("Unsupported imported file format.")
        if not isinstance(manifest.get("original_filename"), str) or not manifest["original_filename"]:
            raise DataQualityError("Import manifest needs an original filename.")
        if (manifest.get("row_count") != len(frame) or manifest.get("column_count") != len(frame.columns)
                or manifest.get("columns") != list(frame.columns)):
            raise DataQualityError("Import manifest dimensions do not match the normalized table.")
        types = manifest.get("types", {})
        if not isinstance(types, dict) or types.get("default") != "string" or not isinstance(types.get("by_column"), dict):
            raise DataQualityError("Import manifest needs explicit source type information.")
        for column, groups in types["by_column"].items():
            if column not in frame or not isinstance(groups, dict):
                raise DataQualityError("Import type metadata references an unknown column.")
            seen = set()
            for kind, rows in groups.items():
                if kind not in {"number", "boolean", "null", "missing", "date", "datetime", "time", "blank"} or not isinstance(rows, list):
                    raise DataQualityError("Unsupported source type metadata.")
                if any(type(row) is not int or row < 0 or row >= len(frame) or row in seen for row in rows):
                    raise DataQualityError("Import type metadata has conflicting or invalid row references.")
                if len(rows) != len(set(rows)):
                    raise DataQualityError("Import type metadata repeats a row reference.")
                seen.update(rows)
        lexemes = manifest.get("numeric_lexemes", {})
        if not isinstance(lexemes, dict):
            raise DataQualityError("Import numeric metadata must describe source cells.")
        for column, values in lexemes.items():
            if column not in frame or not isinstance(values, dict):
                raise DataQualityError("Import numeric metadata references an unknown column.")
            for row, value in values.items():
                if (not isinstance(row, str) or not row.isascii() or not row.isdecimal()
                        or str(int(row)) != row or int(row) >= len(frame) or not isinstance(value, str)):
                    raise DataQualityError("Import numeric metadata has an invalid source cell.")

    def metadata(self, job_id: str) -> dict:
        return _read_json(self._path(job_id, "metadata.json"))

    def list_jobs(self) -> list[dict]:
        jobs = []
        for directory in self.root.iterdir():
            if not directory.is_dir() or directory.is_symlink():
                continue
            try:
                jobs.append(self.metadata(directory.name))
            except (ValueError, OSError):
                continue
        return sorted(jobs, key=lambda job: job["created_at"], reverse=True)

    def _binding(self, job_id: str) -> dict:
        metadata = self.metadata(job_id)
        source_hash = _hash(self._path(job_id, "source.csv").read_bytes())
        rules_hash = _hash(self._path(job_id, "rules.json").read_bytes())
        if source_hash != metadata["source_hash"] or rules_hash != metadata["rules_hash"]:
            raise DataQualityError("Source or rules changed after upload. Create a new job for changed input.")
        if "import_version" in metadata:
            if metadata["import_version"] != 1:
                raise DataQualityError("This imported job uses an unsupported storage version.")
            original_hash = _hash(self._path(job_id, "original.bin").read_bytes())
            manifest_hash = _hash(self._path(job_id, "manifest.json").read_bytes())
            if original_hash != metadata["original_hash"] or manifest_hash != metadata["manifest_hash"]:
                raise DataQualityError("The original upload or import manifest changed. Create a new job for changed input.")
            # Preserve the existing approval contract while binding every input
            # and interpretation choice. Legacy CSV source_hash stays unchanged.
            source_hash = _hash(_json_bytes({"version": 1, "normalized_source_hash": source_hash,
                                           "original_hash": original_hash, "manifest_hash": manifest_hash}))
        return {"job_id": job_id, "source_hash": source_hash, "rules_hash": rules_hash}

    def read_original_inputs(self, job_id: str) -> dict:
        """Capture verified originals for a repeat run, never staged/exported data."""
        self._binding(job_id)
        metadata = self.metadata(job_id)
        source = self._path(job_id, "source.csv").read_bytes()
        rule_bytes = self._path(job_id, "rules.json").read_bytes()
        if _hash(source) != metadata["source_hash"] or _hash(rule_bytes) != metadata["rules_hash"]:
            raise DataQualityError("Original input changed while it was being read.")
        result = {"csv_bytes": source, "rules": json.loads(rule_bytes), "original_bytes": None, "manifest": None}
        if "import_version" in metadata:
            original = self._path(job_id, "original.bin").read_bytes()
            manifest_bytes = self._path(job_id, "manifest.json").read_bytes()
            if _hash(original) != metadata["original_hash"] or _hash(manifest_bytes) != metadata["manifest_hash"]:
                raise DataQualityError("Original upload or import manifest changed while it was being read.")
            result.update(original_bytes=original, manifest=json.loads(manifest_bytes))
        return result

    def import_manifest(self, job_id: str) -> dict | None:
        return self.read_original_inputs(job_id)["manifest"]

    @staticmethod
    def _download_filename(filename: str, format_name: str) -> str:
        # Original filenames are labels only; never use them as disk paths.
        basename = filename.replace("\\", "/").rsplit("/", 1)[-1]
        basename = "".join(char for char in basename if ord(char) >= 32 and ord(char) != 127).strip()
        return basename[:180] if basename and basename not in {".", ".."} else f"original.{format_name}"

    def source_details(self, job_id: str) -> dict:
        manifest = self.import_manifest(job_id)
        if manifest is None:
            return {"format": "csv", "filename": "source.csv", "sheet": None, "imported": False}
        return {"format": manifest["format"],
                "filename": self._download_filename(manifest["original_filename"], manifest["format"]),
                "sheet": manifest.get("sheet"), "imported": True}

    def original_upload(self, job_id: str) -> dict:
        inputs = self.read_original_inputs(job_id)
        manifest = inputs["manifest"]
        format_name = manifest["format"] if manifest else "csv"
        filename = self._download_filename(manifest["original_filename"], format_name) if manifest else "source.csv"
        mime = {"csv": "text/csv", "tsv": "text/tab-separated-values", "json": "application/json",
                "jsonl": "application/x-ndjson", "ndjson": "application/x-ndjson",
                "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}[format_name]
        return {"data": inputs["original_bytes"] if manifest else inputs["csv_bytes"], "filename": filename, "mime": mime}

    def load_rules(self, job_id: str) -> dict:
        self._binding(job_id)
        return _read_json(self._path(job_id, "rules.json"))

    def _stage_info(self, job_id: str) -> dict:
        self._binding(job_id)
        path = self._path(job_id, "stage.json")
        if not path.exists():
            raise DataQualityError("No approved staged copy exists for this job.")
        info = _read_json(path)
        actual = _hash(self._path(job_id, info["staged_file"]).read_bytes())
        if actual != info["staged_hash"]:
            raise DataQualityError("The staged file changed; generate a new approved staged copy.")
        return info

    def read_frame(self, job_id: str, staged: bool = False) -> pd.DataFrame:
        self._binding(job_id)
        filename = self._stage_info(job_id)["staged_file"] if staged else "source.csv"
        return _parse_csv(self._path(job_id, filename).read_bytes())

    def profile(self, job_id: str, staged: bool = False) -> dict:
        frame = self.read_frame(job_id, staged)
        return {
            "row_count": len(frame), "column_count": len(frame.columns), "columns": list(frame.columns),
            "missing_counts": {column: int(frame[column].str.strip().eq("").sum()) for column in frame},
            "duplicate_row_count": int(frame.duplicated().sum()),
        }

    def _validate_frame(self, frame: pd.DataFrame, rules: dict) -> dict:
        issues = []

        def add(kind, row, column, rule_id, message):
            issues.append({"id": f"{rule_id}:{row}", "kind": kind, "row": row, "column": column,
                           "rule_id": rule_id, "message": message, "severity": "blocking"})

        configured = set(rules["required_columns"]) | set(rules["unique_columns"]) | set(rules["date_formats"]) | set(rules["categories"])
        configured.update(rules.get("email_columns", []))
        configured.update(name for rule in rules.get("conditional_dates", []) for name in (rule["column"], rule["when_column"]))
        for column in sorted(configured - set(frame.columns)):
            add("missing_column", None, column, f"column:{column}", "A configured column is absent. Supply corrected input or rules.")
        for column in rules["required_columns"]:
            if column in frame:
                for row in frame.index[frame[column].str.strip().eq("")]:
                    add("missing_required", int(row), column, f"required:{column}", "Required value is missing; a user decision is needed.")
        for row in frame.index[frame.duplicated()]:
            add("duplicate_row", int(row), None, "unique:row", "An earlier row has exactly the same values.")
        for column in rules["unique_columns"]:
            if column in frame:
                duplicate = frame[column].duplicated(keep=False) & frame[column].str.strip().ne("")
                for row in frame.index[duplicate]:
                    add("duplicate_key", int(row), column, f"unique:{column}", "Identifier is repeated; distinct customer details require user review.")
        for column, rule in rules["date_formats"].items():
            if column in frame:
                for row, value in frame[column].items():
                    if value.strip() and _date(value, rule["output"]) is None:
                        add("date_format", int(row), column, f"date:{column}", f"Date must be a real calendar date in {rule['output']} format. Confirm the intended date if the source is invalid or ambiguous.")
        for column in rules.get("email_columns", []):
            if column in frame:
                for row, value in frame[column].items():
                    if value.strip() and not _email(value):
                        add("email_syntax", int(row), column, f"email:{column}", "Email must have a valid ASCII mailbox and dotted domain. Confirm the address from its source.")
        for index, rule in enumerate(rules.get("conditional_dates", [])):
            column, condition = rule["column"], rule["when_column"]
            if column not in frame or condition not in frame:
                continue
            fmt = rules["date_formats"][column]
            for row in frame.index[frame[condition].eq(rule["equals"])]:
                value = frame.at[row, column]
                parsed = _date(value, fmt["output"]) or _date(value, fmt["input"])
                if parsed is None:  # Missing/invalid dates are handled by their own rules.
                    continue
                iso = parsed.strftime("%Y-%m-%d")
                if (rule.get("min_date") and iso < rule["min_date"]) or (rule.get("max_date") and iso > rule["max_date"]):
                    add("business_qualification", int(row), column, f"conditional_date:{index}:{column}",
                        f"When {condition} equals {rule['equals']}, date must be within inclusive bounds {rule.get('min_date') or 'unbounded'} to {rule.get('max_date') or 'unbounded'}. Confirm eligibility or the source date; do not shift it to fit.")
        for column, rule in rules["categories"].items():
            if column in frame:
                allowed = set(rule["allowed"])
                for row, value in frame[column].items():
                    if value.strip() and value not in allowed:
                        add("category", int(row), column, f"category:{column}", "Value is outside the allowed categories.")
        for column in frame:
            if _formula(column):
                add("formula_risk", None, column, f"formula:header:{column}", "Column header could execute as a spreadsheet formula.")
            for row, value in frame[column].items():
                if _formula(value):
                    add("formula_risk", int(row), column, f"formula:{column}", "Cell may execute as a spreadsheet formula; explicit user correction is required.")
        if frame.empty:
            add("empty_dataset", None, None, "dataset:nonempty", "The result has no data rows.")
        return {"issues": issues, "blocking_count": len(issues), "row_count": len(frame),
                "counts": dict(Counter(issue["kind"] for issue in issues)), "valid": not issues}

    def validate(self, job_id: str, staged: bool = False) -> dict:
        return self._validate_frame(self.read_frame(job_id, staged), self.load_rules(job_id))

    def propose(self, job_id: str) -> list[dict]:
        frame, rules = self.read_frame(job_id), self.load_rules(job_id)
        plan = []
        duplicates = set(int(row) for row in frame.index[frame.duplicated()])
        manifest = self.import_manifest(job_id)
        if manifest is not None:
            # A JSON number 1 and text "1", or null/missing/empty text, can
            # have equal CSV projections but are not identical source records.
            by_row = {}
            for column, groups in manifest["types"]["by_column"].items():
                for kind, rows in groups.items():
                    for row in rows:
                        by_row.setdefault(row, {})[column] = kind
            original_numbers = {}
            for column, values in manifest.get("numeric_lexemes", {}).items():
                for row, token in values.items():
                    original_numbers.setdefault(int(row), {})[column] = token
            seen, typed_duplicates = set(), set()
            for row, values in enumerate(frame.itertuples(index=False, name=None)):
                identity = (values, tuple(sorted(by_row.get(row, {}).items())),
                            tuple(sorted(original_numbers.get(row, {}).items())))
                if identity in seen:
                    typed_duplicates.add(row)
                seen.add(identity)
            duplicates &= typed_duplicates
        for row in sorted(duplicates):
            plan.append({"op": "drop", "row": row, "reason": "Remove an exact duplicate; retain its first occurrence.", "rule_id": "unique:row"})
        for column, rule in rules["date_formats"].items():
            if column in frame:
                for row, value in frame[column].items():
                    if row in duplicates or _date(value, rule["output"]) is not None:
                        continue
                    parsed = _date(value, rule["input"])
                    if parsed is not None:
                        plan.append({"op": "set", "row": int(row), "column": column, "value": parsed.strftime(rule["output"]),
                                     "reason": "Convert using the declared input and output date formats.", "rule_id": f"date:{column}"})
        for column, rule in rules["categories"].items():
            if column in frame:
                for row, value in frame[column].items():
                    if row not in duplicates and value not in rule["allowed"] and value in rule["aliases"]:
                        plan.append({"op": "set", "row": int(row), "column": column, "value": rule["aliases"][value],
                                     "reason": "Use the explicit category alias in the import specification.", "rule_id": f"category:{column}"})
        return plan

    def _normalized_plan(self, job_id: str, plan: list[dict], frame: pd.DataFrame) -> list[dict]:
        if not isinstance(plan, list):
            raise DataQualityError("Repair plan must be a list of operations.")
        try:
            operations = [RepairOperation.model_validate(op).model_dump() for op in plan]
        except ValueError as exc:
            raise DataQualityError(f"Invalid repair plan: {exc}") from exc
        allowed = {(op["op"], op["row"], op.get("column"), op.get("value")) for op in self.propose(job_id)}
        seen = set()
        dropped = set()
        updated = set()
        for op in operations:
            if op["row"] >= len(frame):
                raise DataQualityError("Repair row is outside the original dataset.")
            if op["op"] == "set" and op["column"] not in frame:
                raise DataQualityError("Repair column is absent from the original dataset.")
            key = (op["row"], op["column"])
            if key in seen:
                raise DataQualityError("The plan contains conflicting operations for the same cell or row.")
            seen.add(key)
            signature = (op["op"], op["row"], op["column"], op["value"])
            if signature not in allowed and not op["user_supplied"]:
                raise DataQualityError("An unsupported repair needs a value or row-removal decision explicitly supplied by the user.")
            (dropped if op["op"] == "drop" else updated).add(op["row"])
        if dropped & updated:
            raise DataQualityError("A row cannot be both changed and removed in the same plan.")
        return operations

    def _transform(self, frame: pd.DataFrame, plan: list[dict]) -> tuple[pd.DataFrame, list[dict]]:
        result, changes, dropped = frame.copy(), [], []
        for op in plan:
            row = op["row"]
            if op["op"] == "drop":
                before, after = frame.loc[row].to_dict(), None
                dropped.append(row)
            else:
                before, after = frame.at[row, op["column"]], op["value"]
                result.at[row, op["column"]] = after
            changes.append({"op": op["op"], "row": row, "column": op["column"], "before": before,
                            "after": after, "reason": op["reason"], "rule_id": op["rule_id"], "user_supplied": op["user_supplied"]})
        return result.drop(index=dropped), changes

    def preview(self, job_id: str, plan: list[dict]) -> dict:
        binding = self._binding(job_id)
        source = self.read_frame(job_id)
        normalized = self._normalized_plan(job_id, plan, source)
        result, changes = self._transform(source, normalized)
        validation = self._validate_frame(result, self.load_rules(job_id))
        return {**binding, "plan_hash": _hash(_json_bytes(normalized)), "changes": changes,
                "blocking_count": validation["blocking_count"], "validation": validation, "row_count": len(result)}

    @staticmethod
    def _require_approval(approval: dict, binding: dict) -> None:
        if approval.get("approved") is not True:
            raise DataQualityError("Explicit approval is required before this write.")
        if any(approval.get(key) != value for key, value in binding.items()):
            raise DataQualityError("Approval is stale or does not match this exact job and result.")

    def apply(self, job_id: str, plan: list[dict], approval: dict) -> dict:
        preview = self.preview(job_id, plan)
        binding = {key: preview[key] for key in ("job_id", "source_hash", "rules_hash", "plan_hash")}
        self._require_approval(approval, binding)
        operation_id = binding["plan_hash"]
        stage_path = self._path(job_id, "stage.json")
        if stage_path.exists():
            previous = _read_json(stage_path)
            if previous["operation_id"] == operation_id:
                verified = self._stage_info(job_id)
                audit = self._path(job_id, verified["audit_file"]).read_bytes()
                if _hash(audit) != verified["audit_hash"]:
                    raise DataQualityError("The operation audit changed; cannot reuse the staged result.")
                return verified
        frame = self.read_frame(job_id)
        normalized = self._normalized_plan(job_id, plan, frame)
        result, changes = self._transform(frame, normalized)
        if result.empty:
            raise DataQualityError("Removing every data row is outside this workflow; cancel the job instead.")
        staged_bytes = _csv_bytes(result)
        # Verify the staged serialization is still a valid supported CSV.
        _parse_csv(staged_bytes)
        staged_file = f"staged-{operation_id[:24]}.csv"
        audit_file = f"changes-{operation_id[:24]}.json"
        audit = {**binding, "approved_at": _now(), "approval": approval, "changes": changes,
                 "row_count_before": len(frame), "row_count_after": len(result)}
        manifest = self.import_manifest(job_id)
        if manifest is not None:
            metadata = self.metadata(job_id)
            audit["source_provenance"] = {"original_hash": metadata["original_hash"],
                                          "manifest_hash": metadata["manifest_hash"],
                                          "normalized_source_hash": metadata["source_hash"], "manifest": manifest}
        audit_bytes = _json_bytes(audit)
        record = {**binding, "operation_id": operation_id, "staged_file": staged_file,
                  "staged_hash": _hash(staged_bytes), "audit_file": audit_file, "audit_hash": _hash(audit_bytes)}
        # The manifest is the commit point. A crash before it can leave orphan
        # files, but replay derives the exact output from the immutable source.
        _atomic(self._path(job_id, staged_file), staged_bytes)
        _atomic(self._path(job_id, audit_file), audit_bytes)
        _atomic(stage_path, _json_bytes(record))
        return record

    def export_binding(self, job_id: str) -> dict:
        info = self._stage_info(job_id)
        validation = self.validate(job_id, staged=True)
        return {**self._binding(job_id), "staged_hash": info["staged_hash"],
                "plan_hash": info["plan_hash"], "audit_hash": info["audit_hash"],
                "validation_hash": _hash(_json_bytes(validation))}

    def verify_export(self, job_id: str) -> dict:
        """Read-only integrity check before offering previously exported downloads."""
        record_path = self._path(job_id, "export.json")
        if not record_path.exists():
            raise DataQualityError("No approved export exists for this job.")
        record = _read_json(record_path)
        if record.get("binding") != self.export_binding(job_id):
            raise DataQualityError("The approved export no longer matches the staged result.")
        info = self._stage_info(job_id)
        if _hash(self._path(job_id, info["audit_file"]).read_bytes()) != info["audit_hash"]:
            raise DataQualityError("The operation audit changed; downloads are blocked.")
        for key, expected_hash in record["hashes"].items():
            if _hash(self._path(job_id, record["files"][key]).read_bytes()) != expected_hash:
                raise DataQualityError("An exported artifact changed; downloads are blocked.")
        return {key: str(self._path(job_id, name)) for key, name in record["files"].items()}

    def export(self, job_id: str, approval: dict) -> dict:
        binding = self.export_binding(job_id)
        self._require_approval(approval, binding)
        validation = self.validate(job_id, staged=True)
        if validation["blocking_count"]:
            raise DataQualityError("Export is blocked until every configured rule and formula-safety check passes.")
        info = self._stage_info(job_id)
        audit_bytes = self._path(job_id, info["audit_file"]).read_bytes()
        if _hash(audit_bytes) != info["audit_hash"]:
            raise DataQualityError("The audit changed; export is blocked.")
        record_path = self._path(job_id, "export.json")
        if record_path.exists():
            previous = _read_json(record_path)
            if previous.get("binding") == binding:
                return self.verify_export(job_id)
        suffix = info["operation_id"][:16]
        files = {"csv_path": f"validated-{suffix}.csv", "audit_path": f"audit-{suffix}.json", "summary_path": f"validation-{suffix}.txt"}
        audit = _read_json(self._path(job_id, info["audit_file"]))
        audit.update({"export_approval": approval, "export_binding": binding, "validation": validation,
                      "limitation": "Passing these rules verifies conformance, not the truth of customer facts."})
        manifest = self.import_manifest(job_id)
        if manifest is not None:
            metadata = self.metadata(job_id)
            audit["source_provenance"] = {"original_hash": metadata["original_hash"],
                                          "manifest_hash": metadata["manifest_hash"],
                                          "normalized_source_hash": metadata["source_hash"], "manifest": manifest}
            audit["output_interpretation"] = "Cleaned CSV contains the normalized text table; original formats and source types are retained in the original upload and manifest."
        csv_data = self._path(job_id, info["staged_file"]).read_bytes()
        summary = (f"Data Quality Agent — validation summary\nJob: {job_id}\nRows: {validation['row_count']}\n"
                   f"Blocking issues: 0\nApproved changes: {len(audit['changes'])}\n"
                   "The original upload is preserved. The cleaned CSV contains normalized text values.\n"
                   "Passing configured rules does not prove that customer facts are correct.\n").encode("utf-8")
        payloads = {"csv_path": csv_data, "audit_path": _json_bytes(audit), "summary_path": summary}
        for key, data in payloads.items():
            _atomic(self._path(job_id, files[key]), data)
        _atomic(record_path, _json_bytes({"binding": binding, "files": files,
                                        "hashes": {key: _hash(data) for key, data in payloads.items()}}))
        return {key: str(self._path(job_id, name)) for key, name in files.items()}

    def delete_job(self, job_id: str) -> None:
        directory = self.job_dir(job_id)
        # Never recurse through user-created links, junctions, or unexpected dirs.
        if directory.exists():
            for entry in directory.iterdir():
                if entry.is_symlink() or entry.is_dir() or entry.resolve().parent != directory:
                    raise DataQualityError("Unexpected nested path in job; deletion stopped for inspection.")
            for entry in directory.iterdir():
                entry.unlink()
            directory.rmdir()
