"""Source-policy coverage and conservative date assistance regressions."""
import copy
import json

import pytest
from pydantic import ValidationError

from dq_agent.engine import Engine
from dq_agent.schemas import ImportRules
from dq_agent.value_suggestions import _unsupported_fact, preview_request
from dq_agent.workflow import Workflow


RULES = {
    "required_columns": ["email", "signup_date", "country"],
    "email_columns": ["email"],
    "date_formats": {"signup_date": {"input": "%m/%d/%Y", "output": "%Y-%m-%d"}},
    "conditional_dates": [{"column": "signup_date", "when_column": "country", "equals": "GB",
                           "min_date": "2027-01-01", "max_date": "2027-12-31"}],
}


def create(engine, email="a@example.com", date="2027-01-01", country="GB", rules=None):
    return engine.create_job(f"email,signup_date,country\n{email},{date},{country}\n".encode(), rules or RULES)


@pytest.mark.parametrize("email", ["not-an-email", "a@", "@example.com", "a..b@example.com", "a@-bad.com", "a@example", "a@example.com "])
def test_rejects_malformed_mailboxes(tmp_path, email):
    engine = Engine(tmp_path)
    issues = engine.validate(create(engine, email=email))["issues"]
    assert "email_syntax" in [x["kind"] for x in issues]


@pytest.mark.parametrize("email", ["a+b@example.com", "o'neil@sub.example.co.uk", "a-b@example.org"])
def test_valid_mailboxes_do_not_trigger_unnecessary_corrections(tmp_path, email):
    engine = Engine(tmp_path)
    assert engine.validate(create(engine, email=email))["valid"]


@pytest.mark.parametrize("date,country,expected", [("2026-12-31", "GB", 1), ("2027-01-01", "GB", 0),
    ("2027-12-31", "GB", 0), ("2028-01-01", "GB", 1), ("2026-12-31", "US", 0)])
def test_conditional_bounds_are_inclusive_and_exact(tmp_path, date, country, expected):
    engine = Engine(tmp_path)
    result = engine.validate(create(engine, date=date, country=country))
    assert result["blocking_count"] == expected
    if expected:
        assert result["issues"][0]["kind"] == "business_qualification"


def test_detects_policy_exception_even_before_date_conversion(tmp_path):
    engine = Engine(tmp_path)
    result = engine.validate(create(engine, date="12/31/2026"))
    assert result["counts"] == {"date_format": 1, "business_qualification": 1}


def test_missing_condition_column_is_blocking(tmp_path):
    engine = Engine(tmp_path)
    job = engine.create_job(b"email,signup_date\na@example.com,2027-01-01\n", RULES)
    assert engine.validate(job)["counts"] == {"missing_column": 1}


@pytest.mark.parametrize("change", [{"min_date": "2027-02-30"}, {"min_date": "2028-01-01"},
    {"min_date": None, "max_date": None}, {"column": "missing"}, {"when_column": " "}])
def test_invalid_policy_rejected_at_import(change):
    rules = copy.deepcopy(RULES)
    rules["conditional_dates"][0].update(change)
    with pytest.raises(ValidationError):
        ImportRules.model_validate(rules)


def test_new_policy_blocks_approval_and_human_corrections_are_rechecked(tmp_path):
    workflow = Workflow(tmp_path, mode="offline")
    try:
        job = workflow.create(b"email,signup_date,country\nnot-an-email,2026-12-31,GB\n", RULES)
        snap = workflow.snapshot(job)
        assert snap["pending"]["kind"] == "clarification"
        assert workflow.engine.validate(job)["blocking_count"] == 2
        plan = [{"op": "set", "row": 0, "column": col, "value": val,
                 "reason": "Confirmed synthetic source", "user_supplied": True}
                for col, val in (("email", "confirmed@example.com"), ("signup_date", "2027-01-01"))]
        workflow.resume(job, {"action": "revise", "plan": plan})
        assert workflow.snapshot(job)["pending"]["kind"] == "repair_approval"
        assert not (workflow.engine.job_dir(job)/"staged.csv").exists()
    finally:
        workflow.close()


def test_disclosure_contains_relevant_policy_without_other_customer_values(tmp_path):
    engine = Engine(tmp_path)
    job = create(engine, date="2026-12-31")
    request = preview_request(engine, job, [], ["signup_date"], mode="nebius", pending_kind="clarification", revisions=0)
    issue = request["payload"]["issues"][0]
    assert issue["rules"]["applicable_date_bounds"] == [{"min_date": "2027-01-01", "max_date": "2027-12-31"}]
    assert "a@example.com" not in json.dumps(request) and '"GB"' not in json.dumps(request)
    assert _unsupported_fact(issue, "2027-01-01", [], request["targets"][0]) is not None


def test_real_declared_date_conversion_is_still_permitted(tmp_path):
    engine = Engine(tmp_path)
    job = create(engine, date="03/04/2027")
    request = preview_request(engine, job, [], ["signup_date"], mode="nebius", pending_kind="clarification", revisions=0)
    assert _unsupported_fact(request["payload"]["issues"][0], "2027-03-04", engine.propose(job), request["targets"][0]) is None


def test_legacy_rules_remain_compatible_and_do_not_infer_omitted_policies(tmp_path):
    engine = Engine(tmp_path)
    job = engine.create_job(b"email,signup_date,country\nnot-an-email,2026-12-31,GB\n", {"required_columns": ["email"]})
    assert engine.validate(job)["valid"]
