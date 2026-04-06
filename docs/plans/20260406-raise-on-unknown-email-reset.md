# Raise on Unknown Email in requestPasswordReset

## Overview

Change `requestPasswordReset` to raise `UserNotFoundError` when the provided email is not registered, replacing the current silent-success behavior.

Currently the handler returns `None` silently and the GraphQL mutation responds with `success=True` and a generic message to prevent email enumeration. The new behavior raises an exception, and the mutation returns `success=False` with an explicit error message.

> **Security note:** This removes email enumeration protection — callers can now distinguish between registered and unregistered emails. This is an intentional product decision.

## Context (from discovery)

- **Command handler:** `auth_service/application/commands/request_password_reset.py` — lines 44–53 do the silent `return` when `user is None`
- **GraphQL mutation:** `auth_service/presentation/graphql/mutations.py` — `request_password_reset` (lines 141–156) catches `InvalidEmailError` only
- **Domain exception:** `auth_service/domain/exceptions.py` — `UserNotFoundError` already exists
- **Unit tests:** `tests/unit/application/test_password_reset.py` — `test_request_password_reset_unknown_email` (lines 87–98) asserts silent return
- **Integration tests:** `tests/integration/test_graphql.py` — `test_request_reset_unknown_email` (lines 405–413) asserts `success=True`

## Development Approach

- **Testing approach:** TDD — update failing tests first, then fix production code to make them pass
- Complete each task fully before moving to the next
- All tests must pass before starting the next task
- Update this plan file when scope changes

## Solution Overview

1. Update unit test to expect `UserNotFoundError` raised from handler
2. Update integration test to expect `success=False` from mutation
3. Update handler to raise `UserNotFoundError` instead of silent return — **raise before the outer `try/except Exception` block** so it is not swallowed/logged as a generic failure
4. Update mutation to catch `UserNotFoundError` and return `success=False` using `str(exc)` (consistent with `InvalidEmailError` and `reset_password` patterns); `UserNotFoundError` is already imported in `mutations.py`

**Idempotency note:** `IdempotencyExtension` caches `requestPasswordReset` responses for 24 hours keyed by SHA-256(operation+body). After this change, an unknown-email `success=False` will be cached. If the same `Idempotency-Key` header is reused after the user registers, they will receive the cached failure. This is intentional — the client must use a fresh idempotency key to get a new result.

## Implementation Steps

### Task 1: Update unit test for unknown-email case (TDD — red)

**Files:**
- Modify: `tests/unit/application/test_password_reset.py`

- [x] Change `test_request_password_reset_unknown_email` to assert `pytest.raises(UserNotFoundError)` instead of silent return
- [x] Update the inline comment/docstring in the test to reflect the new expected behavior (was "should complete silently")
- [x] Import `UserNotFoundError` in the test file if not already imported
- [x] Run unit tests — test MUST fail (red): `pytest tests/unit/application/test_password_reset.py -v`

### Task 2: Update integration test for unknown-email case (TDD — red)

**Files:**
- Modify: `tests/integration/test_graphql.py`

- [x] Change `test_request_reset_unknown_email` to assert `success=False` and check `message` matches the error
- [x] Run inside Docker to confirm the test now fails (red): `docker compose -f docker/docker-compose.yml run --rm app pytest tests/integration/test_graphql.py::TestPasswordReset::test_request_reset_unknown_email -v` (skipped - docker compose unavailable in this environment)

### Task 3: Raise UserNotFoundError in handler (TDD — green)

**Files:**
- Modify: `auth_service/application/commands/request_password_reset.py`

- [x] Move the `user is None` check **before** the outer `try/except Exception` block (or raise outside it) so `UserNotFoundError` is not logged as a generic `request_password_reset.failure`
- [x] Replace the silent `return` with `raise UserNotFoundError(f"No user with email {command.email}")`
- [x] Import `UserNotFoundError` from `auth_service.domain.exceptions` if not already present
- [x] Run unit tests — `test_request_password_reset_unknown_email` must now pass (green): `pytest tests/unit/application/test_password_reset.py -v`
- [x] Run full unit suite and confirm no regressions: `pytest tests/unit/ -v`

### Task 4: Catch UserNotFoundError in GraphQL mutation (TDD — green)

**Files:**
- Modify: `auth_service/presentation/graphql/mutations.py`

- [x] Add `except UserNotFoundError as exc` block in `request_password_reset` mutation (`UserNotFoundError` is already imported)
- [x] Return `OperationResult(success=False, message=str(exc))` — consistent with `InvalidEmailError` and `reset_password` patterns
- [x] Confirm `InvalidEmailError` still returns `success=False` (existing behavior unchanged)
- [x] Run unit tests: `pytest tests/unit/ -v` — all must pass

### Task 5: Verify acceptance criteria

- [ ] Run full unit test suite: `pytest tests/unit/ -v`
- [ ] Run full integration suite inside Docker: `docker compose -f docker/docker-compose.yml run --rm app pytest tests/ -v`
- [ ] Confirm `test_request_reset_unknown_email` passes with `success=False`
- [ ] Confirm `test_request_password_reset_unknown_email` passes with `UserNotFoundError`
- [ ] Confirm all other password-reset tests still pass (success flow, idempotency, token single-use)

### Task 6: [Final] Update documentation

- [ ] Add a note to `CLAUDE.md` under Key conventions: `requestPasswordReset` now raises `UserNotFoundError` for unknown emails (email enumeration protection removed by product decision)
- [ ] Move this plan to `docs/plans/completed/`

## Post-Completion

**Manual verification:**
- Test via GraphQL Playground: send `requestPasswordReset` with an unregistered email and confirm `success: false` is returned
- Test with a registered email to confirm the happy path still works
