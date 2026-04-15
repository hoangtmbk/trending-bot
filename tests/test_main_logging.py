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


def test_configure_logging_silences_httpx_at_info(tmp_path):
    """httpx logs request URLs at INFO level, which leaks the Telegram
    bot token (URL contains /bot<TOKEN>/...). The token is effectively
    a credential, so suppress httpx to WARNING+ to keep stdout clean.
    """
    from main import _configure_logging

    _configure_logging(tmp_path / "logs")

    httpx_logger = logging.getLogger("httpx")
    # WARNING is int 30; INFO is 20. Effective level must be >= WARNING.
    assert httpx_logger.getEffectiveLevel() >= logging.WARNING, (
        f"httpx logger is at {logging.getLevelName(httpx_logger.getEffectiveLevel())}, "
        "which would leak Telegram bot tokens in logged URLs"
    )


def test_configure_logging_silences_httpcore_at_info(tmp_path):
    """httpcore (httpx's underlying transport) also logs request URLs."""
    from main import _configure_logging

    _configure_logging(tmp_path / "logs")

    httpcore_logger = logging.getLogger("httpcore")
    assert httpcore_logger.getEffectiveLevel() >= logging.WARNING
