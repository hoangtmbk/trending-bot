import json
import pytest
from unittest.mock import patch, MagicMock
from claude_cli import call_claude, call_claude_json


def test_call_claude_returns_stdout():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Hello from Claude"
    mock_result.stderr = ""
    with patch("claude_cli.subprocess.run", return_value=mock_result) as mock_run:
        result = call_claude("Say hello")
        assert result == "Hello from Claude"
        args = mock_run.call_args[0][0]
        assert "claude" in args
        assert "-p" in args


def test_call_claude_json_parses_output():
    response = json.dumps({"items": [{"name": "test"}]})
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = response
    mock_result.stderr = ""
    with patch("claude_cli.subprocess.run", return_value=mock_result):
        result = call_claude_json("Return JSON")
        assert result["items"][0]["name"] == "test"


def test_call_claude_retries_on_failure():
    fail_result = MagicMock()
    fail_result.returncode = 1
    fail_result.stdout = ""
    fail_result.stderr = "Error"

    success_result = MagicMock()
    success_result.returncode = 0
    success_result.stdout = "OK"
    success_result.stderr = ""

    with patch("claude_cli.subprocess.run", side_effect=[fail_result, success_result]):
        result = call_claude("Test", retries=2)
        assert result == "OK"


def test_call_claude_raises_after_exhausting_retries():
    fail_result = MagicMock()
    fail_result.returncode = 1
    fail_result.stdout = ""
    fail_result.stderr = "Error"

    with patch("claude_cli.subprocess.run", return_value=fail_result):
        try:
            call_claude("Test", retries=1)
            assert False, "Should have raised"
        except RuntimeError as e:
            assert "Claude CLI failed" in str(e)


def test_call_claude_json_parses_response_with_preamble_before_fence():
    """Claude often writes a preamble like 'Here is the analysis:' before
    the fenced JSON. The cleaner must still extract the JSON object."""
    fence = "`" * 3
    response = (
        "Based on the announcement, here is the analysis:\n\n"
        f"{fence}json\n"
        '{"what_it_is": "A model", "interest_score": 9}\n'
        f"{fence}\n"
    )
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = response
    mock_result.stderr = ""
    with patch("claude_cli.subprocess.run", return_value=mock_result):
        result = call_claude_json("Analyze")
        assert result == {"what_it_is": "A model", "interest_score": 9}


def test_call_claude_json_parses_bare_object_in_prose():
    """No fences at all — Claude returns prose containing a bare {…} block."""
    response = "Sure! Here you go: {\"answer\": 42, \"ok\": true} hope that helps."
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = response
    mock_result.stderr = ""
    with patch("claude_cli.subprocess.run", return_value=mock_result):
        result = call_claude_json("Compute")
        assert result == {"answer": 42, "ok": True}


def test_call_claude_json_retries_on_parse_failure_then_succeeds():
    """A single malformed response should not kill the call — retry once,
    then succeed if the second attempt is parseable."""
    fence = "`" * 3
    bad = MagicMock(returncode=0, stdout="totally not json", stderr="")
    good = MagicMock(
        returncode=0,
        stdout=f"{fence}json\n{{\"ok\": true}}\n{fence}",
        stderr="",
    )
    with patch("claude_cli.subprocess.run", side_effect=[bad, good]) as mock_run:
        result = call_claude_json("Test", retries=2)
        assert result == {"ok": True}
        assert mock_run.call_count == 2


def test_call_claude_treats_empty_stdout_as_failure_and_retries():
    """rc=0 with empty stdout is not a real success — retry it."""
    empty = MagicMock(returncode=0, stdout="", stderr="")
    good = MagicMock(returncode=0, stdout="hello", stderr="")
    with patch("claude_cli.subprocess.run", side_effect=[empty, good]) as mock_run:
        result = call_claude("Test", retries=2)
        assert result == "hello"
        assert mock_run.call_count == 2


def test_call_claude_json_raises_after_exhausting_retries_on_unparseable():
    bad = MagicMock(returncode=0, stdout="not json at all, no braces", stderr="")
    with patch("claude_cli.subprocess.run", return_value=bad):
        with pytest.raises((RuntimeError, ValueError)):
            call_claude_json("Test", retries=2)
