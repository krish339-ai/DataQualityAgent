"""Date and category widgets express a user's choice without inventing facts."""

from copy import deepcopy
from datetime import date, datetime

import pytest

from dq_agent.correction_controls import correction_spec, correction_value
from dq_agent.schemas import ImportRules


RULES = {
    "required_columns": ["member_number", "joined_on", "region"],
    "unique_columns": ["member_number"],
    "date_formats": {"joined_on": {"input": "%m/%d/%Y", "output": "%Y-%m-%d"}},
    "categories": {"region": {"allowed": ["US", "CA", "GB"], "aliases": {"ca": "CA"}}},
}


@pytest.mark.parametrize("raw", ["02/30/2026", "2026-02-30", "02/29/2027", "", None, "2/28/2026"])
def test_invalid_or_absent_dates_do_not_choose_a_default(raw):
    spec = correction_spec("joined_on", RULES, raw)
    assert spec["kind"] == "date"
    assert spec["date_value"] is None
    assert spec["value"] == (raw or "")
    with pytest.raises(ValueError, match="Choose the intended date"):
        correction_value(spec, None)


@pytest.mark.parametrize("raw", ["02/29/2028", "2028-02-29"])
def test_existing_real_dates_are_preserved_and_serialize_to_output(raw):
    spec = correction_spec("joined_on", RULES, raw)
    assert spec["date_value"] == date(2028, 2, 29)
    assert correction_value(spec, spec["date_value"]) == "2028-02-29"


def test_date_selection_serializes_custom_output_format():
    rules = deepcopy(RULES)
    rules["date_formats"]["joined_on"]["output"] = "%d.%m.%Y"
    spec = correction_spec("joined_on", rules, "02/28/2026")
    assert spec["date_value"] == date(2026, 2, 28)
    assert correction_value(spec, date(2026, 10, 5)) == "05.10.2026"


def test_ambiguous_date_uses_declared_output_before_input():
    rules = deepcopy(RULES)
    rules["date_formats"]["joined_on"]["output"] = "%d/%m/%Y"
    spec = correction_spec("joined_on", rules, "10/05/2026")
    assert spec["date_value"] == date(2026, 5, 10)


@pytest.mark.parametrize("value", ["2026-02-28", 20260228, True, datetime(2026, 2, 28), (date(2026, 2, 28),)])
def test_date_selection_rejects_coercion_or_discarding_time(value):
    spec = correction_spec("joined_on", RULES, "")
    with pytest.raises(ValueError, match="Choose the intended date"):
        correction_value(spec, value)


@pytest.mark.parametrize("raw", ["ZZ", "ca", "Canada", "", None])
def test_categories_offer_exact_allowed_values_without_choosing_a_guess(raw):
    spec = correction_spec("region", RULES, raw)
    assert spec["kind"] == "category"
    assert spec["options"] == ["US", "CA", "GB"]
    assert spec["selected_value"] is None
    with pytest.raises(ValueError, match="allowed values"):
        correction_value(spec, raw)


def test_valid_category_is_selected_and_only_exact_values_are_accepted():
    spec = correction_spec("region", RULES, "CA")
    assert spec["selected_value"] == "CA"
    assert correction_value(spec, "GB") == "GB"
    with pytest.raises(ValueError, match="allowed values"):
        correction_value(spec, " gb ")


def test_text_ids_keep_leading_zeros_and_expose_required_unique_guidance():
    spec = correction_spec("member_number", RULES, "00102")
    assert spec["kind"] == "text"
    assert spec["value"] == "00102"
    assert spec["required"] is True and spec["unique"] is True
    assert "unique across the file" in spec["help"]
    assert correction_value(spec, "00103") == "00103"
    assert correction_value(spec, " 00103 ") == " 00103 "
    with pytest.raises(ValueError, match="text value"):
        correction_value(spec, 103)


def test_column_names_do_not_determine_the_control():
    assert correction_spec("country", {}, "CA")["kind"] == "text"
    assert correction_spec("signup_date", {}, "2026-10-05")["kind"] == "text"
    rules = {"categories": {"quality_grade": {"allowed": ["Gold", "Silver"]}}}
    assert correction_spec("quality_grade", rules, "Gold")["kind"] == "category"


@pytest.mark.parametrize("field", ["member_number", "joined_on", "region"])
def test_required_field_cannot_be_cleared(field):
    spec = correction_spec(field, RULES, "")
    with pytest.raises(ValueError, match="required"):
        correction_value(spec, None, allow_blank=True)


@pytest.mark.parametrize("field", ["member_number", "joined_on", "region"])
def test_optional_blank_needs_an_explicit_user_choice(field):
    rules = {**RULES, "required_columns": []}
    spec = correction_spec(field, rules, "")
    assert spec["required"] is False
    with pytest.raises(ValueError):
        correction_value(spec, None)
    with pytest.raises(ValueError):
        correction_value(spec, "")
    assert correction_value(spec, None, allow_blank=True) == ""


def test_timestamp_output_uses_text_without_discarding_hours():
    rules = {"date_formats": {"event": {"input": "%m/%d/%Y %H:%M", "output": "%Y-%m-%d %H:%M"}}}
    spec = correction_spec("event", rules, "2026-10-05 15:30")
    assert spec["kind"] == "text"
    assert spec["date_value"] is None
    assert "calendar cannot represent" in spec["help"]
    assert correction_value(spec, "2026-10-05 15:30") == "2026-10-05 15:30"
    with pytest.raises(ValueError, match="valid value"):
        correction_value(spec, "2026-10-05")


def test_timestamp_input_also_uses_text_even_when_output_is_date_only():
    rules = {"date_formats": {"event": {"input": "%m/%d/%Y %H:%M", "output": "%Y-%m-%d"}}}
    spec = correction_spec("event", rules, "10/05/2026 15:30")
    assert spec["kind"] == "text"
    assert correction_value(spec, "2026-10-05") == "2026-10-05"


def test_literal_percent_in_date_format_can_still_use_calendar():
    rules = {"date_formats": {"event": {"input": "%m/%d/%Y", "output": "%Y-%m-%d%%"}}}
    spec = correction_spec("event", rules, "2026-10-05%")
    assert spec["kind"] == "date"
    assert spec["date_value"] == date(2026, 10, 5)
    assert correction_value(spec, date(2026, 10, 6)) == "2026-10-06%"


def test_helpers_do_not_mutate_rules_values_or_an_existing_spec():
    rules = deepcopy(RULES)
    before = deepcopy(rules)
    category = correction_spec("region", rules, "ZZ")
    correction_value(category, "CA")
    category["options"].append("NEW")
    assert rules == before
    original = correction_spec("member_number", rules, "001")
    before_spec = deepcopy(original)
    correction_value(original, "002")
    assert original == before_spec


def test_model_rules_are_supported_without_mutation():
    rules = ImportRules.model_validate(RULES)
    before = rules.model_dump()
    spec = correction_spec("region", rules, "CA")
    spec["options"].clear()
    assert rules.model_dump() == before


@pytest.mark.parametrize("value", [123, False, date(2026, 10, 5)])
def test_current_values_are_not_implicitly_coerced(value):
    with pytest.raises(ValueError, match="text or empty"):
        correction_spec("member_number", RULES, value)
