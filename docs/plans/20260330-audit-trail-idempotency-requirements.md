# Requirements: Audit Trail + Idempotency Keys

## Overview

Two independent features to improve production-readiness of the auth service:

1. **Audit Trail** — persistent compliance log of auth events in PostgreSQL
2. **Idempotency Keys** — prevent duplicate side effects on client retries for `login` and `requestPasswordReset`

These features are independent and can be implemented in separate plans/PRs.

---

## Feature 1: Audit Trail

### Goal

Persist a historical, append-only log of authentication events in PostgreSQL for compliance
and audit purposes. Redis session data expires — this table provides the durable record.

### Events to capture

| Event type | Trigger | `user_id` | `session_id` |
|---|---|---|---|
| `login_success` | Successful authentication | ✓ | ✓ (new session) |
| `login_failed` | Invalid credentials or inactive user | nullable* | — |
| `logout` | User explicitly revokes own session | ✓ | ✓ |
| `session_revoked` | Session revoked programmatically | ✓ | ✓ |
| `token_refreshed` | Refresh token rotation | ✓ | ✓ |
| `password_reset_requested` | Reset email dispatched | ✓ | — |
| `password_reset_completed` | Password changed via reset token | ✓ | — |

*`login_failed`: `user_id` is nullable because for a non-existent email the user record is
never found. When the user exists but password is wrong, `user_id` should be recorded.

**Explicitly out of scope:** `session_expired` — Redis TTL expiry is silent; capturing it
would require Redis keyspace notifications, which is a separate infrastructure concern.

### Data model

```sql
CREATE TABLE auth_events (
    id          UUID PRIMARY KEY,
    user_id     UUID REFERENCES users(id) ON DELETE SET NULL,  -- nullable
    event_type  VARCHAR(50) NOT NULL,
    session_id  UUID,                    -- nullable, no FK (session is ephemeral in Redis)
    ip_address  INET,                    -- nullable
    occurred_at TIMESTAMPTZ NOT NULL,
    metadata    JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_auth_events_user_id     ON auth_events(user_id);
CREATE INDEX idx_auth_events_occurred_at ON auth_events(occurred_at);
CREATE INDEX idx_auth_events_event_type  ON auth_events(event_type);
```

`session_id` has no FK to any table — the session lives in Redis and is ephemeral. The column
is purely informational for cross-referencing logs.

### Metadata contract per event type

```python
# login_success
{"device_info": "Chrome 120 / macOS", "user_agent": "Mozilla/5.0 ..."}

# login_failed
{"reason": "invalid_password"}          # user exists, wrong password
{"reason": "user_not_found"}            # no account for this email
{"reason": "inactive_account"}          # account deactivated

# logout / session_revoked
{"reason": "user_logout"}
{"reason": "password_reset"}            # revoked after password change

# token_refreshed
{}                                       # no extra metadata needed

# password_reset_requested
{}                                       # email not logged (PII minimisation)

# password_reset_completed
{}
```

### Architecture

**Placement in DDD layers:**

```
domain/value_objects/auth_event_type.py   — AuthEventType enum (all event type strings)
application/ports/audit_log.py            — AuditLogPort interface
application/dto.py                        — AuditEventDTO dataclass (fields: id, user_id,
                                            event_type, session_id, ip_address,
                                            occurred_at, metadata)
infrastructure/db/models.py               — AuthEventModel (SQLAlchemy)
infrastructure/db/repositories/
    audit_log_repository.py               — SQLAlchemy implementation of AuditLogPort
container.py                              — wire AuditLogPort → AuditLogRepository
```

**`AuditLogPort` interface:**

```python
class AuditLogPort(ABC):
    @abstractmethod
    async def record(self, event: AuditEventDTO) -> None: ...
```

**Integration in command handlers (Option A — chosen):**

Each command handler receives `AuditLogPort` via constructor injection. After the main
operation completes (success or failure), the handler calls `audit_log.record(...)`.

**Critical constraint:** audit log failures must NEVER propagate to the caller.
Wrap `audit_log.record(...)` in `try/except Exception` and log the error via structlog.
The main operation's result is returned regardless.

```python
# Pattern for success path
try:
    await self._audit_log.record(event)
except Exception as exc:
    _log.error("audit_log.write_failed", error=str(exc))
```

**For `login_failed`:** the exception is raised after the audit write attempt. The handler
must catch the domain exception, record the failed event, then re-raise.

### IP address propagation

IP is a transport-layer concern — it must be threaded from presentation → application.

**Changes to `application/dto.py`:**

```python
# Add ip_address: str | None = None to:
AuthenticateUserCommand
RefreshTokenCommand
RevokeSessionCommand
RequestPasswordResetCommand
ResetPasswordCommand
```

**Changes to `presentation/graphql/mutations.py`:**

Each resolver extracts IP from the Strawberry context:

```python
request = info.context["request"]
ip_address = request.client.host if request.client else None
```

Pass `ip_address=ip_address` to the corresponding command.

### Alembic migration

New migration file required: `alembic/versions/<hash>_add_auth_events_table.py`

### Testing requirements

- Unit tests for each command handler: verify `audit_log.record()` is called with correct
  event type and metadata (mock `AuditLogPort`)
- Unit tests: verify audit log failure does not propagate (mock raises, main op succeeds)
- Unit tests: verify `login_failed` records correct `reason` in metadata
- Integration test: `AuthEventModel` round-trip (save + query from `auth_test` DB)

---

## Feature 2: Idempotency Keys

### Goal

Allow clients to safely retry `login` and `requestPasswordReset` mutations without creating
duplicate sessions or sending multiple reset emails.

### Scope

| Mutation | Idempotent | Rationale |
|---|---|---|
| `login` | ✓ | Retry must not create a second session |
| `requestPasswordReset` | ✓ | Retry must not send a second email |
| `register` | — | `UserAlreadyExistsError` already prevents duplicates |
| `resetPassword` | — | Token is single-use; natural idempotency via `consume()` |
| `refreshToken` | — | `GETDEL` on refresh token is already single-use |
| `revokeSession` | — | Revoking a non-existent session is already a no-op |

### Mechanism

1. Client sends `Idempotency-Key: <uuid>` HTTP header on the request.
2. If the key has been seen before for the same operation + same request body:
   - Return the original cached response (no re-execution).
3. If the key has been seen but with a **different request body hash**:
   - Return HTTP 409 Conflict with error message.
4. If the key is new: process normally, cache the response, return it.
5. If the header is absent: process normally (idempotency is opt-in).

### Redis storage

Key format: `idempotency:{operation}:{idempotency_key_value}`
TTL: 24 hours

Stored value (JSON):
```json
{
  "request_hash": "<sha256(operation + request_body_json)>",
  "response": { ... },
  "status_code": 200
}
```

`response` is the serialised GraphQL response payload (the `data` field of the JSON response).

### Architecture

**Placement:** Strawberry custom extension (preferred over FastAPI middleware) — it has
access to the parsed GraphQL operation name and the resolved result before serialisation.

```
infrastructure/redis/idempotency_store.py   — Redis read/write/check
presentation/graphql/idempotency.py         — Strawberry SchemaExtension
presentation/graphql/schema.py              — register extension
```

**`IdempotencyStore` interface (infrastructure only, no port needed — presentation concern):**

```python
class IdempotencyStore:
    async def get(self, key: str) -> dict | None: ...
    async def set(self, key: str, value: dict, ttl: int) -> None: ...
```

**Extension logic (pseudocode):**

```python
class IdempotencyExtension(SchemaExtension):
    IDEMPOTENT_OPERATIONS = {"login", "requestPasswordReset"}

    async def on_executing(self):
        operation = get_operation_name(self.execution_context)
        if operation not in self.IDEMPOTENT_OPERATIONS:
            yield; return

        idempotency_key = get_header("Idempotency-Key")
        if not idempotency_key:
            yield; return

        redis_key = f"idempotency:{operation}:{idempotency_key}"
        request_hash = sha256(operation + request_body)

        cached = await self._store.get(redis_key)
        if cached:
            if cached["request_hash"] != request_hash:
                raise HTTP 409
            # inject cached response, skip execution
            return

        yield  # execute normally

        response = get_result()
        await self._store.set(redis_key, {
            "request_hash": request_hash,
            "response": response,
        }, ttl=86400)
```

**409 response format:**

Since this is GraphQL (always HTTP 200 by convention), return the error in the GraphQL
`errors` array with a distinct error code rather than HTTP 409:

```json
{
  "errors": [{
    "message": "Idempotency key reused with different request",
    "extensions": { "code": "IDEMPOTENCY_CONFLICT" }
  }]
}
```

### Testing requirements

- Unit tests for `IdempotencyStore`: get/set/miss/hit
- Unit tests for extension: cache hit returns cached response, miss executes handler,
  conflict returns error
- Integration tests: two identical `login` calls with same key → one session created,
  second call returns same tokens; two calls with same key + different body → conflict error

---

## Implementation order (recommendation)

Implement as two separate PRs in this order:

1. **Audit Trail** — foundational, no dependencies on Feature 2
2. **Idempotency Keys** — independent, can follow

Both features touch `dto.py` (IP propagation is audit-only) and `mutations.py`, but have
no shared infrastructure code.
