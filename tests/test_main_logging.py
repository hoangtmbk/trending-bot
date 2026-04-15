import logging
import logging.handlers
from pathlib import Path


def test_configure_logging_creates_log_file(tmp_path):
    from main import _configure_logging

    log_dir = tmp_path / "logs"
    _configure_logging(log_dir)

    logger = logging.getLogger("trendbot")
    logger.info("hello from test")

    # Flush handlers so the test can observe the file.
    for h in logger.handlers + logging.getLogger().handlers:
        h.flush()

    log_file = log_dir / "trendbot.log"
    assert log_file.exists(), f"expected {log_file} to exist"
    content = log_file.read_text()
    assert "hello from test" in content


def test_configure_logging_is_idempotent(tmp_path):
    from main import _configure_logging

    log_dir = tmp_path / "logs"
    _configure_logging(log_dir)
    _configure_logging(log_dir)  # should not double-attach handlers

    root_file_handlers = [
        h for h in logging.getLogger().handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    # Exactly one rotating file handler on the root logger.
    assert len(root_file_handlers) == 1


def test_configure_logging_creates_log_dir_if_missing(tmp_path):
    from main import _configure_logging

    log_dir = tmp_path / "does" / "not" / "exist"
    assert not log_dir.exists()

    _configure_logging(log_dir)

    assert log_dir.exists() and log_dir.is_dir()
