"""Pure, rules-driven controls for a human's draft corrections.

These helpers only describe inputs and serialize a user's chosen value. They do
not infer missing facts, edit data, or replace whole-file validation.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .schemas import ImportRules


def _calendar_format(fmt: str) -> bool:
    """A calendar may represent dates, but must never discard time components."""
    index = 0
    while index < len(fmt):
        if fmt[index] == "%":
            index += 1
            if index >= len(fmt) or fmt[index] not in {"Y", "m", "d", "%"}:
                return False
        index += 1
    return True


def _parse_date(value: str, fmt: str) -> date | None:
    try:
        parsed = datetime.strptime(value, fmt)
        # Match the engine: strptime alone also accepts incorrectly padded dates.
        return parsed.date() if parsed.strftime(fmt) == value else None
    except (ValueError, OverflowError):
        return None


def correction_spec(
    field: str, rules: ImportRules | dict[str, Any], current: str | None
) -> dict[str, Any]:
    """Describe a control using the configured rule, never the column's name.

    ``value`` preserves the original string; ``date_value`` and
    ``selected_value`` are safe widget defaults. Invalid or absent values do not
    select today's date, the first category, or a category alias automatically.
    """
    if not isinstance(field, str) or not field.strip():
        raise ValueError("Choose a field to correct.")
    if current is not None and not isinstance(current, str):
        raise ValueError("The current field value must be text or empty.")
    validated = rules if isinstance(rules, ImportRules) else ImportRules.model_validate(rules)
    raw = current if current is not None else ""
    required = field in validated.required_columns
    unique = field in validated.unique_columns
    spec: dict[str, Any] = {
        "field": field,
        "kind": "text",
        "value": raw,
        "selected_value": None,
        "date_value": None,
        "options": [],
        "input_format": None,
        "output_format": None,
        "required": required,
        "unique": unique,
    }
    guidance = ["A value is required." if required else "This field may be left blank."]
    if unique:
        guidance.append("The value must be unique across the file; the preview checks this.")
    if field in validated.email_columns:
        guidance.append("Use a confirmed email address with an ASCII mailbox and dotted domain. Syntax checks do not verify delivery.")
    for limit in validated.conditional_dates:
        if limit.column == field:
            guidance.append(f"When {limit.when_column} is {limit.equals}, inclusive date bounds are {limit.min_date or 'unbounded'} to {limit.max_date or 'unbounded'}. Confirm eligibility; do not change a true date just to fit.")
    if field in validated.categories:
        allowed = list(validated.categories[field].allowed)
        spec.update(kind="category", options=allowed, selected_value=raw if raw in allowed else None)
        guidance.append("Choose an allowed value exactly as listed in your rules.")
    elif field in validated.date_formats:
        rule = validated.date_formats[field]
        spec.update(input_format=rule.input, output_format=rule.output)
        if _calendar_format(rule.input) and _calendar_format(rule.output):
            # Output takes precedence when both formats can parse an ambiguous value.
            parsed = _parse_date(raw, rule.output) or _parse_date(raw, rule.input)
            spec.update(kind="date", date_value=parsed)
            display_format = rule.output.replace("%%", "\x00").replace("%Y", "YYYY").replace("%m", "MM").replace("%d", "DD").replace("\x00", "%")
            guidance.append(f"Choose the intended date; it will be saved as {display_format}.")
        else:
            guidance.append(
                "This rule includes components a calendar cannot represent. "
                f"Enter the complete value in the required output format: {rule.output}."
            )
    else:
        guidance.append("Enter the confirmed value. Text and leading zeros are preserved.")
    spec["help"] = " ".join(guidance)
    return spec


def correction_value(spec: dict[str, Any], value: Any, *, allow_blank: bool = False) -> str:
    """Serialize an explicit selection without guessing or coercing values.

    ``allow_blank=True`` expresses an explicit decision to clear an optional
    field; a missing widget selection alone never expresses that decision.
    Cross-record constraints, such as uniqueness, remain the preview's job.
    """
    if allow_blank:
        if spec["required"]:
            raise ValueError("This field is required and cannot be left blank.")
        return ""
    kind = spec["kind"]
    if kind == "date":
        if type(value) is not date:
            raise ValueError("Choose the intended date from the calendar.")
        rendered = value.strftime(spec["output_format"])
        if _parse_date(rendered, spec["output_format"]) != value:
            raise ValueError("This date cannot be represented by the configured output format.")
        return rendered
    if kind == "category":
        if not isinstance(value, str) or value not in spec["options"]:
            raise ValueError("Choose one of the allowed values from the list.")
        return value
    if kind != "text":
        raise ValueError("This field control is not supported.")
    if not isinstance(value, str):
        raise ValueError("Enter a text value for this field.")
    if not value.strip():
        if spec["required"]:
            raise ValueError("This field is required and cannot be left blank.")
        raise ValueError("Choose to leave this optional field blank explicitly.")
    # Date rules with unsupported calendar components use a complete text input.
    if spec["output_format"]:
        try:
            parsed = datetime.strptime(value, spec["output_format"])
            valid = parsed.strftime(spec["output_format"]) == value
        except (ValueError, OverflowError):
            valid = False
        if not valid:
            raise ValueError(f"Enter a valid value matching {spec['output_format']}.")
    return value
