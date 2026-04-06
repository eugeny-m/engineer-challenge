"""Unit tests for auth_service.infrastructure.logging."""
import logging

import structlog

from auth_service.infrastructure.logging import configure_logging, get_logger


def _reset_structlog() -> None:
    structlog.reset_defaults()
    # Remove any handlers added by previous configure_logging() calls
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)


def test_configure_logging_does_not_raise(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "console")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    _reset_structlog()
    configure_logging()
    logger = get_logger(__name__)
    # Must not raise AttributeError
    logger.info("test message")


def test_add_logger_name_console_mode(monkeypatch, capsys):
    monkeypatch.setenv("LOG_FORMAT", "console")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    _reset_structlog()
    configure_logging()
    logger = get_logger("my.module")
    logger.info("checking logger name")
    captured = capsys.readouterr()
    assert "my.module" in captured.out


def test_add_logger_name_json_mode(monkeypatch, capsys):
    monkeypatch.setenv("LOG_FORMAT", "json")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    _reset_structlog()
    configure_logging()
    logger = get_logger("my.json.module")
    logger.info("checking logger name json")
    captured = capsys.readouterr()
    assert "my.json.module" in captured.out
