# Audit Trail + Idempotency Keys

## Overview

Two independent production-readiness features for the auth service:

1. **Audit Trail** — append-only compliance log of auth events in PostgreSQL; Redis session data expires but this table provides the durable record.
2. **Idempotency Keys** — prevent duplicate side effects on client retries for `login` and `requestPasswordReset`.

These features are independent and should be implemented as two separate PRs in order: Audit Trail first, then Idempotency Keys.

## Context (from discovery)

- **Files involved**: `domain/value_objects/`, `application/dto.py`, `application/ports/`, `infrastructure/db/models.py`, `infrastructure/db/repositories/`, `infrastructure/redis/`, `presentation/graphql/mutations.py`, `presentation/graphql/schema.py`, `container.py`
- **Patterns**: DDD layering — no framework types in inner layers; ports/adapters for infrastructure; constructor injection for command handlers
- **Dependencies**: SQLAlchemy 2.0 async, redis.asyncio, Strawberry GraphQL extensions

## Development Approach

- **Testing approach**: Regular (code first, then tests)
- Complete each task fully before moving to the next
- Make small, focused changes
- **CRITICAL: every task MUST include new/updated tests** for code changes in that task
- **CRITICAL: all tests must pass before starting the next task**
- **CRITICAL: update this plan file when scope changes during implementation**
- Audit log failures must NEVER propagate to the caller — wrap in `try/except Exception`

## Testing Strategy

- **Unit tests**: required for every task
- **Integration tests**:
  - `AuthEventModel` round-trip (save + query from `auth_test` DB)
  - Two identical `login` calls with same idempotency key → one session created
  - Two calls with same key + different body → conflict error
- Run full suite inside Compose network: `docker compose -f docker/docker-compose.yml run --rm app pytest tests/ -v`

## Progress Tracking

- Mark completed items with `[x]` immediately when done
- Add newly discovered tasks with ➕ prefix
- Document issues/blockers with ⚠️ prefix
- Update plan if implementation deviates from scope

## What Goes Where

- **Implementation Steps** (`[ ]` checkboxes): code changes, tests, documentation updates
- **Post-Completion** (no checkboxes): manual testing, deployment steps, external verifications

---

## Implementation Steps

---

### Feature 1: Audit Trail

---

### Task 1: Domain/Application layer foundation

**Files:**
- Create: `domain/value_objects/auth_event_type.py`
- Create: `application/ports/audit_log.py`
- Modify: `application/dto.py`

- [x] create `AuthEventType` enum in `domain/value_objects/auth_event_type.py` with all 7 event type strings (`login_success`, `login_failed`, `logout`, `session_revoked`, `token_refreshed`, `password_reset_requested`, `password_reset_completed`)
- [x] create `AuditEventDTO` dataclass in `application/dto.py` with fields: `id: UUID`, `user_id: UUID | None`, `event_type: AuthEventType`, `session_id: UUID | None`, `ip_address: str | None`, `occurred_at: datetime`, `metadata: dict`
- [x] create `AuditLogPort(ABC)` in `application/ports/audit_log.py` with single abstract method `async def record(self, event: AuditEventDTO) -> None`
- [x] write unit tests for `AuthEventType` enum (all values present, correct string values)
- [x] run tests — must pass before Task 2

---

### Task 2: AuthEventModel + Alembic migration

**Files:**
- Modify: `infrastructure/db/models.py`
- Create: `alembic/versions/<hash>_add_auth_events_table.py`

- [x] add `AuthEventModel` to `infrastructure/db/models.py` with columns: `id UUID PK`, `user_id UUID FK→users(id) ON DELETE SET NULL nullable`, `event_type VARCHAR(50) NOT NULL`, `session_id UUID nullable`, `ip_address INET nullable`, `occurred_at TIMESTAMPTZ NOT NULL`, `metadata JSONB NOT NULL DEFAULT '{}'`
- [x] add indexes: `idx_auth_events_user_id`, `idx_auth_events_occurred_at`, `idx_auth_events_event_type`
- [x] generate Alembic migration: `docker compose -f docker/docker-compose.yml run --rm app alembic revision --autogenerate -m "add_auth_events_table"`
- [x] verify generated migration SQL matches the data model spec; adjust if autogenerate missed INET type or JSONB default
- [x] apply migration: `docker compose -f docker/docker-compose.yml run --rm app alembic upgrade head`
- [x] write integration test: save an `AuthEventModel` to `auth_test` DB, query it back, assert all fields round-trip correctly
- [x] run tests — must pass before Task 3

---

### Task 3: AuditLogRepository

**Files:**
- Create: `infrastructure/db/repositories/audit_log_repository.py`

- [x] implement `AuditLogRepository(AuditLogPort)` in `infrastructure/db/repositories/audit_log_repository.py` using async SQLAlchemy session
- [x] `record()` maps `AuditEventDTO` → `AuthEventModel`, calls `session.add()` + `session.flush()`
- [x] write unit tests for `AuditLogRepository.record()` with mocked session (assert `add` called with correct model fields)
- [x] write integration test: call `repository.record(dto)`, query DB, assert row persisted with correct data
- [x] run tests — must pass before Task 4

---

### Task 4: Wire AuditLogPort in container

**Files:**
- Modify: `container.py`

- [ ] import `AuditLogRepository` in `container.py`
- [ ] bind `AuditLogPort` → `AuditLogRepository` in `GlobalContainer` (request-scoped, using DB session)
- [ ] write unit test: resolve `AuditLogPort` from container, assert instance is `AuditLogRepository`
- [ ] run tests — must pass before Task 5

---

### Task 5: IP address propagation to commands

**Files:**
- Modify: `application/dto.py`
- Modify: `presentation/graphql/mutations.py`

- [ ] add `ip_address: str | None = None` field to: `AuthenticateUserCommand`, `RefreshTokenCommand`, `RevokeSessionCommand`, `RequestPasswordResetCommand`, `ResetPasswordCommand`
- [ ] in each corresponding mutation resolver in `mutations.py`, extract IP: `request = info.context["request"]; ip_address = request.client.host if request.client else None`
- [ ] pass `ip_address=ip_address` to each command constructor
- [ ] write unit tests for each mutation resolver: assert `ip_address` is extracted and forwarded correctly (mock request context)
- [ ] run tests — must pass before Task 6

---

### Task 6: Integrate audit logging in LoginUser command handler

**Files:**
- Modify: `application/command_handlers/authenticate_user.py` (or equivalent)

- [ ] inject `AuditLogPort` via constructor in `AuthenticateUserCommandHandler`
- [ ] on success path: after session created, call `await self._audit_log.record(AuditEventDTO(event_type=AuthEventType.LOGIN_SUCCESS, user_id=..., session_id=..., ip_address=..., metadata={...}))` wrapped in `try/except Exception`
- [ ] on `login_failed` path (invalid password): catch domain exception, record `login_failed` event with `reason: "invalid_password"` and `user_id` set, re-raise
- [ ] on `login_failed` path (user not found): record `login_failed` event with `reason: "user_not_found"` and `user_id=None`, re-raise
- [ ] on `login_failed` path (inactive account): record `login_failed` with `reason: "inactive_account"`, re-raise
- [ ] write unit test: verify `audit_log.record()` called with `LOGIN_SUCCESS` on success (mock `AuditLogPort`)
- [ ] write unit test: verify `audit_log.record()` called with `LOGIN_FAILED` + correct reason metadata for each failure case
- [ ] write unit test: verify audit log failure (mock raises) does NOT propagate — main operation result still returned
- [ ] run tests — must pass before Task 7

---

### Task 7: Integrate audit logging in remaining command handlers

**Files:**
- Modify: `application/command_handlers/logout.py`
- Modify: `application/command_handlers/revoke_session.py`
- Modify: `application/command_handlers/refresh_token.py`
- Modify: `application/command_handlers/request_password_reset.py`
- Modify: `application/command_handlers/reset_password.py`

- [ ] `LogoutCommandHandler`: inject `AuditLogPort`; record `logout` with `reason: "user_logout"` on success, wrapped in try/except
- [ ] `RevokeSessionCommandHandler`: inject `AuditLogPort`; record `session_revoked` with `reason: "password_reset"` (or appropriate reason) on success, wrapped in try/except
- [ ] `RefreshTokenCommandHandler`: inject `AuditLogPort`; record `token_refreshed` (empty metadata) on success, wrapped in try/except
- [ ] `RequestPasswordResetCommandHandler`: inject `AuditLogPort`; record `password_reset_requested` (empty metadata — no email for PII minimisation) on success, wrapped in try/except
- [ ] `ResetPasswordCommandHandler`: inject `AuditLogPort`; record `password_reset_completed` (empty metadata) on success, wrapped in try/except
- [ ] write unit tests for each handler: verify `audit_log.record()` called with correct event type and metadata
- [ ] write unit test for each handler: verify audit log failure does NOT propagate
- [ ] run tests — must pass before Task 8

---

### Feature 2: Idempotency Keys

---

### Task 8: IdempotencyStore

**Files:**
- Create: `infrastructure/redis/idempotency_store.py`

- [ ] implement `IdempotencyStore` class with Redis client injected via constructor
- [ ] `async def get(self, key: str) -> dict | None` — fetch and JSON-decode from Redis, return `None` on miss
- [ ] `async def set(self, key: str, value: dict, ttl: int) -> None` — JSON-encode and store with TTL (24h = 86400s)
- [ ] key format: `idempotency:{operation}:{idempotency_key_value}`
- [ ] stored value format: `{"request_hash": "<sha256>", "response": {...}}`
- [ ] write unit tests: get miss → None, get hit → dict, set stores correct JSON and TTL (mock Redis)
- [ ] run tests — must pass before Task 9

---

### Task 9: IdempotencyExtension (Strawberry)

**Files:**
- Create: `presentation/graphql/idempotency.py`

- [ ] create `IdempotencyExtension(SchemaExtension)` in `presentation/graphql/idempotency.py`
- [ ] `IDEMPOTENT_OPERATIONS = {"login", "requestPasswordReset"}`
- [ ] implement `on_executing()`: extract operation name; skip if not in `IDEMPOTENT_OPERATIONS`
- [ ] if no `Idempotency-Key` header present: yield (execute normally)
- [ ] compute `request_hash = sha256(operation + json.dumps(request_body, sort_keys=True))`
- [ ] on cache hit with matching hash: inject cached response, skip execution
- [ ] on cache hit with mismatching hash: return GraphQL error `{"code": "IDEMPOTENCY_CONFLICT"}` (do NOT use HTTP 409 — GraphQL convention is always 200 with errors array)
- [ ] on cache miss: yield (execute normally), then store result in `IdempotencyStore` with 24h TTL
- [ ] write unit test: cache hit with matching hash → cached response returned, handler not called
- [ ] write unit test: cache miss → handler called, response stored
- [ ] write unit test: cache hit with different hash → `IDEMPOTENCY_CONFLICT` error returned
- [ ] run tests — must pass before Task 10

---

### Task 10: Register IdempotencyExtension in schema

**Files:**
- Modify: `presentation/graphql/schema.py`

- [ ] import `IdempotencyExtension` in `schema.py`
- [ ] add `IdempotencyExtension` to the `extensions` list when constructing the Strawberry schema
- [ ] wire `IdempotencyStore` into the extension (via DI or direct instantiation with Redis client from container)
- [ ] write integration test: two identical `login` calls with same `Idempotency-Key` header → only one session created in Redis, second call returns same tokens
- [ ] write integration test: two `login` calls with same `Idempotency-Key` but different body → `IDEMPOTENCY_CONFLICT` error returned
- [ ] write integration test: two identical `requestPasswordReset` calls with same key → only one email dispatched (mock email sender), second call returns same response
- [ ] run tests — must pass before Task 11

---

### Task 11: Verify acceptance criteria

- [ ] verify all 7 audit event types are recorded in the correct command handlers
- [ ] verify audit log failures never propagate (covered by unit tests)
- [ ] verify IP address flows from GraphQL request → command → audit event
- [ ] verify idempotency works for `login` and `requestPasswordReset`; other mutations unaffected
- [ ] verify `Idempotency-Key` header absence is handled gracefully (no error, normal execution)
- [ ] run full test suite: `docker compose -f docker/docker-compose.yml run --rm app pytest tests/ -v`
- [ ] verify 0 failures, 0 warnings

---

### Task 12: [Final] Update documentation

- [ ] update `CLAUDE.md` if new patterns introduced (e.g. audit log fire-and-forget pattern, idempotency extension pattern)
- [ ] move this plan to `docs/plans/completed/`

---

## Technical Details

### Audit Trail — events and metadata

| Event type | Trigger | `user_id` | `session_id` |
|---|---|---|---|
| `login_success` | Successful authentication | ✓ | ✓ (new session) |
| `login_failed` | Invalid credentials or inactive user | nullable | — |
| `logout` | User explicitly revokes own session | ✓ | ✓ |
| `session_revoked` | Session revoked programmatically | ✓ | ✓ |
| `token_refreshed` | Refresh token rotation | ✓ | ✓ |
| `password_reset_requested` | Reset email dispatched | ✓ | — |
| `password_reset_completed` | Password changed via reset token | ✓ | — |

`login_failed`: `user_id` nullable — for non-existent email the user is never found; when user exists but password is wrong, `user_id` should be recorded.

**Explicitly out of scope:** `session_expired` — Redis TTL expiry is silent; capturing it would require Redis keyspace notifications (separate infrastructure concern).

### Audit Trail — metadata contract per event type

```python
# login_success
{"device_info": "Chrome 120 / macOS", "user_agent": "Mozilla/5.0 ..."}

# login_failed
{"reason": "invalid_password"}   # user exists, wrong password
{"reason": "user_not_found"}     # no account for this email
{"reason": "inactive_account"}   # account deactivated

# logout / session_revoked
{"reason": "user_logout"}
{"reason": "password_reset"}     # revoked after password change

# token_refreshed / password_reset_requested / password_reset_completed
{}
```

### Audit Trail — data model

```sql
CREATE TABLE auth_events (
    id          UUID PRIMARY KEY,
    user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
    event_type  VARCHAR(50) NOT NULL,
    session_id  UUID,
    ip_address  INET,
    occurred_at TIMESTAMPTZ NOT NULL,
    metadata    JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_auth_events_user_id     ON auth_events(user_id);
CREATE INDEX idx_auth_events_occurred_at ON auth_events(occurred_at);
CREATE INDEX idx_auth_events_event_type  ON auth_events(event_type);
```

`session_id` has no FK — session lives in Redis and is ephemeral; column is informational only.

### Idempotency Keys — scope

| Mutation | Idempotent | Rationale |
|---|---|---|
| `login` | ✓ | Retry must not create a second session |
| `requestPasswordReset` | ✓ | Retry must not send a second email |
| `register` | — | `UserAlreadyExistsError` already prevents duplicates |
| `resetPassword` | — | Token is single-use; natural idempotency via `consume()` |
| `refreshToken` | — | `GETDEL` on refresh token is already single-use |
| `revokeSession` | — | Revoking a non-existent session is already a no-op |

### Idempotency Keys — Redis storage

- Key format: `idempotency:{operation}:{idempotency_key_value}`
- TTL: 24 hours (86400s)
- Stored value: `{"request_hash": "<sha256(operation + request_body_json)>", "response": {...}}`
- `response` is the serialised GraphQL `data` field

### Idempotency Keys — conflict response format

GraphQL always returns HTTP 200; conflicts are signalled via the `errors` array:

```json
{
  "errors": [{
    "message": "Idempotency key reused with different request",
    "extensions": { "code": "IDEMPOTENCY_CONFLICT" }
  }]
}
```

## Post-Completion

**Manual verification:**
- Send `login` request twice with same `Idempotency-Key` via curl/Postman; confirm identical token response and single session in Redis
- Send `requestPasswordReset` twice with same key; confirm single email in mail log
- Query `auth_events` table after login, logout, and password reset flows; verify rows present with correct fields

**Migration deployment:**
- Run `alembic upgrade head` in production before deploying code that writes audit events
