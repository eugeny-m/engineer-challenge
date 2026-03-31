"""Structured logging configuration using structlog.

In production (LOG_FORMAT=json or not set), emits JSON logs.
In development (LOG_FORMAT=console), emits human-readable colored console logs.

Log context keys used across the service:
  user_id    - UUID of the authenticated/affected user
  email      - email address involved in the operation
  operation  - name of the command/query being executed
  duration_ms - elapsed time in milliseconds for the operation
"""
import logging
import os
import sys

import structlog


def configure_logging() -> None:
    """Configure structlog processors and stdlib logging integration."""
    log_format = os.getenv("LOG_FORMAT", "json").lower()
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if log_format == "console":
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level, logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Also configure stdlib logging to use structlog formatting
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level, logging.INFO))


def get_logger(name: str) -> structlog.typing.FilteringBoundLogger:
    """Return a bound structlog logger for the given module name."""
    return structlog.get_logger(name)
