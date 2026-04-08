import json
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
