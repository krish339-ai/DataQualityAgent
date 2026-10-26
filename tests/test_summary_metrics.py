from dq_agent.presentation import render_summary_metrics


def test_unavailable_validation_is_not_presented_as_zero(monkeypatch):
    rendered = []
    monkeypatch.setattr("dq_agent.presentation.st.html", rendered.append)
    render_summary_metrics(2, None, 0)
    html = rendered[0]
    issues = html.split("Blocking issues", 1)[1].split("Proposed changes", 1)[0]
    assert "Not available" in issues
    assert "Validation could not be verified" in issues
    assert '>0</div>' not in issues


def test_verified_blocker_count_and_context_are_displayed(monkeypatch):
    rendered = []
    monkeypatch.setattr("dq_agent.presentation.st.html", rendered.append)
    render_summary_metrics(2, 3, 0, blocker_caption="In the original file")
    html = rendered[0]
    issues = html.split("Blocking issues", 1)[1].split("Proposed changes", 1)[0]
    assert '>3</div>' in issues
    assert "In the original file" in issues
    assert "Not available" not in html
