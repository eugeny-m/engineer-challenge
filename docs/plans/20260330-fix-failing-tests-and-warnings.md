# Fix Failing Tests and Warnings

## Overview

13 tests fail and 7 warnings are emitted in the current test run (see `docs/test_results.txt`).
The failures split into three root causes:

1. **`generate_access_token` return type mismatch** — the port/implementation changed its
   signature from `-> str` to `-> tuple[str, str]`, but callers (command handlers, fake,
   test assertions) were not all updated consistently.
2. **`rotate_session` does not delete the old refresh token** — the integration test calls
   `rotate_session` directly (without going through `get_session_by_refresh_token` first),
   so the old refresh key is never removed from Redis and the assertion fails.
3. **JWT HMAC key-length warnings** — test secrets are shorter than the 32-byte minimum
   required by PyJWT for HS256, producing `InsecureKeyLengthWarning` on every token encode.

## Context (from discovery)

**Files involved:**
- `auth_service/application/ports/token_service.py` — abstract port defining return type
- `auth_service/infrastructure/security/jwt_token_service.py` — concrete implementation
- `auth_service/application/commands/authenticate_user.py` — callers of `generate_access_token`
- `auth_service/application/commands/refresh_token.py` — callers of `generate_access_token`
- `tests/unit/application/fakes.py` — `FakeTokenService.generate_access_token`
- `tests/unit/infrastructure/test_security.py` — unit tests + short test secrets
- `tests/unit/application/test_authenticate_user.py` — uses FakeTokenService via handler
- `tests/unit/application/test_token_lifecycle.py` — uses FakeTokenService via handler
- `tests/integration/test_token_store.py` — integration test for `rotate_session`
- `auth_service/infrastructure/redis/redis_token_store.py` — `rotate_session` implementation

**Failure groups:**

| # | Test(s) | Error | Root cause |
|---|---------|-------|------------|
| 7 | `test_security.py::TestJwtTokenService::*` | `ValueError: too many values to unpack (expected 2)` | `generate_access_token` returns unexpected number of values |
| 5 | `test_authenticate_user.py::*`, `test_token_lifecycle.py::*` | `AttributeError: 'tuple' object has no attribute 'split'` | Token result used as string but is a tuple |
| 1 | `test_token_store.py::test_rotate_session_old_refresh_rejected` | `AssertionError: assert {...} is None` | Old refresh token not deleted by `rotate_session` |
| — | 7 warnings | `InsecureKeyLengthWarning` | Test secrets < 32 bytes |

## Development Approach

- **Testing approach:** Regular (fix then verify)
- Complete each task fully before moving to the next
- Run `pytest tests/unit/ -v` after each task to confirm progress
- Integration tests require Docker (`docker compose -f docker/docker-compose.yml run --rm app pytest tests/ -v`)

## Progress Tracking

- Mark completed items with `[x]` immediately when done
- Add ➕ prefix for newly discovered tasks
- Add ⚠️ prefix for blockers
- Move plan to `docs/plans/completed/` on completion

## Implementation Steps

### Task 1: Align `generate_access_token` signature across port, implementation, and fake

**Root cause:** `generate_access_token` was changed to return `tuple[str, str]` in some places
but not all, causing either "too many values to unpack" (if implementation returns 3 values) or
`AttributeError: 'tuple' has no attribute 'split'` (if callers still expect a plain string).

**Files:**
- Modify: `auth_service/application/ports/token_service.py`
- Modify: `auth_service/infrastructure/security/jwt_token_service.py`
- Modify: `tests/unit/application/fakes.py`

- [x] Confirm `TokenService.generate_access_token` signature is `-> tuple[str, str]` with
  docstring "returns (token, jti)"
- [x] Confirm `JwtTokenService.generate_access_token` returns exactly `(token, jti)` — a 2-tuple
  where `token` is the JWT string and `jti` is the UUID4 string embedded in claims
- [x] Confirm `FakeTokenService.generate_access_token` returns `(f"access:{user_id}:{session_id}:{jti}", jti)`
  — a 2-tuple matching the same contract
- [x] Run `pytest tests/unit/infrastructure/test_security.py -v` — all 11 tests pass, 0 failures

### Task 2: Fix command handlers to unpack the tuple correctly

**Root cause:** If a handler still calls `self._token_service.generate_access_token(...)` and
assigns the result to a single variable, that variable holds the whole tuple. Subsequent code
(logging, DTO construction, or downstream calls) then receives a tuple where a string is expected,
causing `AttributeError: 'tuple' object has no attribute 'split'` in the fake's `decode_access_token`.

**Files:**
- Modify: `auth_service/application/commands/authenticate_user.py`
- Modify: `auth_service/application/commands/refresh_token.py`

- [x] In `AuthenticateUserHandler.handle`: ensure `generate_access_token` result is unpacked as
  `access_token, jti = self._token_service.generate_access_token(user.id, session_id)` and
  `access_token` (not the tuple) is passed to `TokenPairDTO` and `create_session`
- [x] In `RefreshTokenHandler.handle`: ensure `generate_access_token` result is unpacked as
  `new_access_token, new_jti = self._token_service.generate_access_token(user_id, session_id)`
  and individual values are used, not the tuple
- [x] Run `pytest tests/unit/application/ -v` — all 24 tests pass, 0 failures

### Task 3: Fix `rotate_session` to explicitly delete the old refresh token

**Root cause:** `RedisTokenStore.rotate_session` assumed the caller had already consumed (and
therefore deleted) the old refresh token via `get_session_by_refresh_token` (which uses
`GETDEL`). The integration test calls `rotate_session` directly, bypassing that step, so the
old `refresh:{token}` key is never removed from Redis.

**Fix:** Add an explicit `pipe.delete(self._refresh_key(old_refresh_token))` inside the
`rotate_session` pipeline. This is safe — `DEL` on a non-existent key is a no-op, so it does
not break the normal flow where `GETDEL` already removed it.

**Files:**
- Modify: `auth_service/infrastructure/redis/redis_token_store.py`

- [ ] Inside `rotate_session`, add `pipe.delete(self._refresh_key(old_refresh_token))` to the
  pipeline so the old refresh token is always invalidated, regardless of whether
  `get_session_by_refresh_token` was called first
- [ ] Run integration tests inside Docker:
  `docker compose -f docker/docker-compose.yml run --rm app pytest tests/integration/test_token_store.py -v`
  — `test_rotate_session_old_refresh_rejected` passes

### Task 4: Fix JWT HMAC key-length warnings

**Root cause:** Two test secrets in `test_security.py` are below PyJWT's 32-byte minimum for
HS256: `_SECRET` (30 bytes) and the inline `"wrong-secret"` (12 bytes).

**Files:**
- Modify: `tests/unit/infrastructure/test_security.py`

- [ ] Extend `_SECRET = "test-secret-key-for-unit-tests"` to ≥ 32 bytes,
  e.g. `"test-secret-key-for-unit-tests!!"` (32 bytes)
- [ ] Extend the inline `secret="wrong-secret"` in
  `test_token_signed_with_wrong_secret_raises_invalid_token_error` to ≥ 32 bytes,
  e.g. `"wrong-secret-key-for-unit-tests!!"` (34 bytes)
- [ ] Run `pytest tests/unit/infrastructure/test_security.py -v -W error::DeprecationWarning`
  and confirm 0 `InsecureKeyLengthWarning` lines in output

### Task 5: Verify acceptance criteria

- [ ] Run full unit suite: `pytest tests/unit/ -v` — 0 failures, 0 `InsecureKeyLengthWarning`
- [ ] Run full suite in Docker:
  `docker compose -f docker/docker-compose.yml run --rm app pytest tests/ -v`
  — 0 failures, 0 `InsecureKeyLengthWarning`
- [ ] Confirm all 13 previously-failing tests now pass

### Task 6: [Final] Clean up

- [ ] Move this plan to `docs/plans/completed/`

## Technical Details

**Return-type contract for `generate_access_token`:**
```python
def generate_access_token(self, user_id: UUID, session_id: UUID) -> tuple[str, str]:
    """Returns (token, jti) where token is the signed JWT string and jti is
    the UUID4 claim embedded in the token. Returning jti directly avoids a
    redundant decode by callers that need it for session storage."""
```

**`rotate_session` pipeline fix:**
```python
async with self._redis.pipeline(transaction=True) as pipe:
    # Explicitly delete old refresh token — safe no-op if already removed by GETDEL
    pipe.delete(self._refresh_key(old_refresh_token))
    # ... rest of pipeline unchanged
```

**Test secret minimum lengths:**
- `_SECRET`: extend from 30 → 32 bytes (append 2 characters)
- inline wrong secret: extend from 12 → 32+ bytes

## Post-Completion

**Manual verification:** Re-run `docker compose ... pytest tests/ -v` after merging to confirm
a clean run with 0 failures and 0 warnings.
