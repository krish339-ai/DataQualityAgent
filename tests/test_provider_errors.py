"""Provider failure messages remain useful without exposing provider payloads."""
import pytest

from dq_agent.reasoning import InvestigationError, _invoke_with_retry


PRIVATE_VALUES = ("private-api-key", "private-model-id", "private-response-body")


class ProviderError(RuntimeError):
    def __init__(self, status):
        super().__init__(" ".join(PRIVATE_VALUES))
        self.status_code = status
        self.body = {"model": PRIVATE_VALUES[1], "message": PRIVATE_VALUES[2]}
        self.headers = {"Authorization": PRIVATE_VALUES[0]}


class ProviderTimeoutError(ProviderError):
    pass


class ProviderConnectionError(ProviderError):
    pass


class RateLimitError(ProviderError):
    pass


class FailingModel:
    def __init__(self, error, failures=None):
        self.error = error
        self.failures = failures
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        if self.failures is None or self.calls <= self.failures:
            raise self.error
        return "recovered response"


@pytest.mark.parametrize("status, expected", [
    (401, "API key"),
    (403, "account permissions"),
    (404, "NEBIUS_MODEL or FIREWORKS_MODEL"),
    (400, "Check provider settings"),
])
def test_permanent_errors_are_sanitized_and_not_retried(monkeypatch, status, expected):
    sleeps = []
    monkeypatch.setattr("dq_agent.reasoning.time.sleep", sleeps.append)
    model = FailingModel(ProviderError(status))
    with pytest.raises(InvestigationError) as caught:
        _invoke_with_retry(model, [])
    assert expected in str(caught.value)
    assert all(value not in str(caught.value) for value in PRIVATE_VALUES)
    assert caught.value.__suppress_context__
    assert model.calls == 1
    assert sleeps == []


@pytest.mark.parametrize("error, expected", [
    (ProviderError(429), "rate limiting"),
    (ProviderError(500), "server error"),
    (ProviderError(503), "server error"),
    (ProviderTimeoutError(None), "timed out"),
    (ProviderConnectionError(None), "could not be reached"),
    (RateLimitError(None), "rate limiting"),
])
def test_transient_errors_stop_after_three_attempts(monkeypatch, error, expected):
    sleeps = []
    monkeypatch.setattr("dq_agent.reasoning.time.sleep", sleeps.append)
    model = FailingModel(error)
    with pytest.raises(InvestigationError) as caught:
        _invoke_with_retry(model, [])
    assert expected in str(caught.value)
    assert "three attempts" in str(caught.value)
    assert all(value not in str(caught.value) for value in PRIVATE_VALUES)
    assert caught.value.__suppress_context__
    assert model.calls == 3
    assert sleeps == [1, 2]


def test_transient_failure_can_recover(monkeypatch):
    sleeps = []
    monkeypatch.setattr("dq_agent.reasoning.time.sleep", sleeps.append)
    model = FailingModel(ProviderError(503), failures=1)
    assert _invoke_with_retry(model, []) == "recovered response"
    assert model.calls == 2
    assert sleeps == [1]


@pytest.mark.parametrize("status", [401, 404])
def test_permanent_status_takes_precedence_over_exception_name(monkeypatch, status):
    sleeps = []
    monkeypatch.setattr("dq_agent.reasoning.time.sleep", sleeps.append)
    model = FailingModel(ProviderConnectionError(status))
    with pytest.raises(InvestigationError):
        _invoke_with_retry(model, [])
    assert model.calls == 1
    assert sleeps == []
