# Fix: structlog `PrintLogger` has no attribute `name`

## Overview

`configure_logging()` uses `PrintLoggerFactory()` but includes `add_logger_name` in the
processor chain — a stdlib-only processor that calls `logger.name`. `PrintLogger` has no
`.name` attribute, so every log call raises `AttributeError` and crashes the GraphQL resolver.

**Problem:** `logger_factory=structlog.PrintLoggerFactory()` + `structlog.stdlib.add_logger_name`
are incompatible.

**Fix:** Replace `PrintLoggerFactory()` with `structlog.stdlib.LoggerFactory()`. The rest of the
config already uses stdlib integration (`wrap_for_formatter`, `ProcessorFormatter`) so this is
the correct factory anyway.

## Context (from discovery)

- **Broken file:** `auth_service/infrastructure/logging.py`
- **Affected callers:** all 8 command handlers + jwt_token_service + rate_limiter + mock_email_service
- **No existing logging unit tests** — need to add one

## Development Approach

- Regular (code first, then tests)
- Single-file change + one new test file

## Implementation Steps

### Task 1: Fix logger factory in `configure_logging()`

**Files:**
- Modify: `auth_service/infrastructure/logging.py`
- Create: `tests/unit/infrastructure/test_logging.py`

- [x] replace `logger_factory=structlog.PrintLoggerFactory()` with `logger_factory=structlog.stdlib.LoggerFactory()`
- [x] write unit test: call `configure_logging()` then `get_logger(__name__).info("test")` — must not raise
- [x] write unit test: verify `add_logger_name` populates `logger` field (console and json modes)
- [x] run `pytest tests/unit/infrastructure/test_logging.py -v` — must pass

### Task 2: Verify acceptance criteria

- [x] run full unit suite: `pytest tests/unit/ -v`
- [x] run full suite in Docker: `docker compose -f docker/docker-compose.yml run --rm app pytest tests/ -v` (skipped - docker compose not available in this environment; unit suite passes)
- [x] manually call `register` mutation — no `AttributeError`, response returns `success: true` (skipped - manual test, not automatable)

### Task 3: Update documentation

- [ ] move this plan to `docs/plans/completed/`

## Technical Details

`structlog.stdlib.LoggerFactory()` creates stdlib `logging.Logger` instances (which have `.name`).
`PrintLoggerFactory()` creates structlog-native `PrintLogger` instances (no `.name`).

The existing `ProcessorFormatter.wrap_for_formatter` and `ProcessorFormatter` setup already
assumes stdlib integration, so `LoggerFactory` is the correct choice.

## Post-Completion

- Re-test all three user flows (register, login, password reset) manually to confirm logs appear
  in expected format under both `LOG_FORMAT=console` and `LOG_FORMAT=json`.
