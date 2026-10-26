"""No live calls: test the evaluator's distinction between errors and abstentions."""
import pytest

from scripts.evaluate_nebius import RecordingModel, score_suggestions, score_detection


def test_oracle_distinguishes_false_refusal_hallucination_and_hidden_truth():
    gold=[{'record':1,'field':'country','value':'CA','evidence':'answerable'},
          {'record':2,'field':'customer_id','value':'00800','evidence':'must_abstain'},
          {'record':3,'field':'signup_date','value':'2027-03-01','evidence':'ambiguous_hypothesis'}]
    targets=[dict(record=x['record'],field=x['field'],issue_id=i) for i,x in enumerate(gold)]
    raw=[{'issue_id':0,'disposition':'abstain','value':None},
         {'issue_id':1,'disposition':'suggest','value':'00800'},
         {'issue_id':2,'disposition':'suggest','value':'2027-02-28'}]
    delivered=[raw[0],{'issue_id':1,'disposition':'abstain','value':None},raw[2]]
    result=score_suggestions(gold,targets,raw,delivered)
    assert result[0]['raw']['unnecessary_refusal']
    assert result[1]['raw']['incorrect']  # Lucky unsupported ID is still an error.
    assert not result[1]['delivered']['incorrect']
    assert result[2]['raw']['hypothesis_truth_mismatch']
    assert not result[2]['raw']['incorrect']  # Kept separate from determinate/policy errors.


def test_missing_response_is_not_counted_as_refusal():
    result=score_suggestions([{'record':1,'field':'country','value':'US','evidence':'answerable'}],
                            [{'record':1,'field':'country','issue_id':0}],[],[])[0]
    assert result['raw']['disposition']=='missing'
    assert not result['raw']['unnecessary_refusal']
    assert not result['delivered']['correct']


def test_wrong_allowed_value_is_still_incorrect_and_detection_is_independent():
    result=score_suggestions([{'record':1,'field':'country','value':'CA','evidence':'answerable'}],
                            [{'record':1,'field':'country','issue_id':0}],
                            [{'issue_id':0,'disposition':'suggest','value':'US'}],[])[0]
    assert result['raw']['incorrect']
    scored=score_detection([[1,'email','email_syntax']],[])
    assert scored['missed']==[(1,'email','email_syntax')]
    assert scored['detected']==0


def test_guardrail_false_refusal_is_not_attributed_to_raw_model():
    result=score_suggestions([{'record':1,'field':'country','value':'CA','evidence':'answerable'}],
                            [{'record':1,'field':'country','issue_id':0}],
                            [{'issue_id':0,'disposition':'suggest','value':'CA'}],
                            [{'issue_id':0,'disposition':'abstain','value':None}])[0]
    assert result['raw']['correct']
    assert not result['raw']['unnecessary_refusal']
    assert result['delivered']['unnecessary_refusal']


def test_network_budget_stops_before_request(monkeypatch):
    class Client:
        def invoke(self, messages):
            raise AssertionError('A network request must not start')
    monkeypatch.setattr(RecordingModel,'requests_started',RecordingModel.request_budget)
    calls=[]
    with pytest.raises(RuntimeError,match='budget'):
        RecordingModel(Client(),calls).invoke([])
    assert calls==[]


def test_recorded_provider_errors_exclude_sensitive_exception_text(monkeypatch):
    class Client:
        def invoke(self, messages):
            raise ValueError('Authorization: FAKE_PRIVATE_TOKEN')
    monkeypatch.setattr(RecordingModel,'requests_started',0)
    calls=[]
    with pytest.raises(ValueError):
        RecordingModel(Client(),calls).invoke([])
    assert calls[0]['error_type']=='ValueError'
    assert 'FAKE_PRIVATE_TOKEN' not in str(calls)
