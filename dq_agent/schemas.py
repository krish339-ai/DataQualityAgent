"""Small, explicit contracts for import rules and the permitted repair language."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DateRule(StrictModel):
    input: str
    output: str = "%Y-%m-%d"

    @model_validator(mode="after")
    def valid_formats(self):
        for value in (self.input, self.output):
            # V1 intentionally supports dates, not locale-dependent timestamps.
            if not value or not all(token in value for token in ("%Y", "%m", "%d")):
                raise ValueError("Date formats must contain %Y, %m, and %d.")
            try:
                rendered = datetime(2026, 10, 24).strftime(value)
                datetime.strptime(rendered, value)
            except ValueError as exc:
                raise ValueError("Unsupported date format.") from exc
        return self


class CategoryRule(StrictModel):
    allowed: list[str] = Field(min_length=1)
    aliases: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def no_conflicts(self):
        if any(not value.strip() for value in self.allowed):
            raise ValueError("Allowed categories must be nonblank; optional missing values need no category entry.")
        if len(self.allowed) != len(set(self.allowed)):
            raise ValueError("Allowed category values must be unique.")
        for alias, target in self.aliases.items():
            if not alias.strip():
                raise ValueError("Missing values cannot be filled by aliases; request a user-supplied value.")
            if target not in self.allowed:
                raise ValueError("Every alias must map to an allowed category.")
            if alias in self.allowed and alias != target:
                raise ValueError("An allowed category cannot alias another category.")
        return self


class ConditionalDateRule(StrictModel):
    """Inclusive ISO date bounds, applied only when an exact category matches."""

    column: str
    when_column: str
    equals: str
    min_date: str | None = None
    max_date: str | None = None

    @model_validator(mode="after")
    def valid_bounds(self):
        if not self.equals.strip() or not (self.min_date or self.max_date):
            raise ValueError("Conditional date rules need a nonblank condition and at least one date bound.")
        for value in (self.min_date, self.max_date):
            if value is not None:
                parsed = datetime.strptime(value, "%Y-%m-%d")
                if parsed.strftime("%Y-%m-%d") != value:
                    raise ValueError("Date bounds must use YYYY-MM-DD.")
        if self.min_date and self.max_date and self.min_date > self.max_date:
            raise ValueError("The minimum date cannot be after the maximum date.")
        return self


class ImportRules(StrictModel):
    required_columns: list[str] = Field(default_factory=list)
    unique_columns: list[str] = Field(default_factory=list)
    date_formats: dict[str, DateRule] = Field(default_factory=dict)
    categories: dict[str, CategoryRule] = Field(default_factory=dict)
    email_columns: list[str] = Field(default_factory=list)
    conditional_dates: list[ConditionalDateRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_names(self):
        names = (
            self.required_columns
            + self.unique_columns
            + list(self.date_formats)
            + list(self.categories)
            + self.email_columns
            + [name for rule in self.conditional_dates for name in (rule.column, rule.when_column)]
        )
        if any(not name.strip() for name in names):
            raise ValueError("Rule column names cannot be blank.")
        for values in (self.required_columns, self.unique_columns, self.email_columns):
            if len(values) != len(set(values)):
                raise ValueError("Rule columns cannot be repeated.")
        if set(self.date_formats) & set(self.categories):
            raise ValueError("A column cannot have both date and category rules in v1.")
        if set(self.email_columns) & (set(self.date_formats) | set(self.categories)):
            raise ValueError("Email columns cannot also have date or category rules.")
        for rule in self.conditional_dates:
            if rule.column not in self.date_formats:
                raise ValueError("Each conditional date column needs a declared date format.")
        return self


class RepairOperation(StrictModel):
    op: Literal["set", "drop"]
    row: int = Field(ge=0)
    column: str | None = None
    value: str | None = None
    reason: str = Field(min_length=1)
    rule_id: str | None = None
    user_supplied: bool = False

    @model_validator(mode="after")
    def operation_fields(self):
        if self.op == "set" and (self.column is None or self.value is None):
            raise ValueError("A set operation needs a column and string value.")
        if self.op == "drop" and (self.column is not None or self.value is not None):
            raise ValueError("A drop operation only identifies a row.")
        return self
