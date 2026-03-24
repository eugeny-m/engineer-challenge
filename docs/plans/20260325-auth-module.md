# Auth Module — DDD/CQRS Authentication Service

## Overview

Implement a production-quality authentication module for the PintoPay engineering challenge.
Three user flows: **Registration**, **Login**, and **Password Recovery**.

The system demonstrates engineering maturity through:
- DDD (bounded context: Identity, explicit domain model, ubiquitous language)
- CQRS (command handlers for mutations, query handlers for reads)
- IaC (Docker Compose for reproducible local environment)
- GraphQL API (Strawberry, maps naturally to Command/Query split)
- Structured logging (structlog)
- Security-first: bcrypt passwords, JWT tokens, rate limiting, expiry

**Stack chosen:** Python 3.12, FastAPI, Strawberry GraphQL, SQLAlchemy 2.0 async,
PostgreSQL, Alembic, passlib/bcrypt, PyJWT, structlog, pytest, Redis (aioredis).

**Why Python over Go/TypeScript:** Primary reason — production Python experience enables
meaningful code review and validation of architectural decisions; other stacks would produce
code that cannot be critically evaluated. Secondary reasons: Strawberry provides code-first
GraphQL that maps cleanly to DDD types, async SQLAlchemy 2.0 is mature, FastAPI has
excellent async support. Trade-off acknowledged: lower raw throughput than Go, but Python's
async I/O is sufficient for an auth service where bottlenecks are Redis/Postgres, not CPU.

**Why Redis for tokens (not pure JWT):** The service targets hundreds of millions of users
with token-based authentication on every API request. Fintech constraint: immediate token
revocation is required (compromised account, fraud detection, forced logout). Pure stateless
JWT cannot satisfy this without a blocklist. Redis handles millions of GET/DEL ops/sec at
sub-millisecond latency, making per-request allowlist checks viable at this scale.

## Context (from discovery)

- Files/components involved: entirely new project, no existing code
- Related patterns found: none (greenfield)
- Dependencies identified: PostgreSQL, Redis, SMTP (mocked)

## Development Approach

- **Testing approach**: Regular (code first, then tests for critical paths)
- Complete each task fully before moving to the next
- Make small, focused changes
- **CRITICAL: every task MUST include new/updated tests** for code changes in that task
- **CRITICAL: all tests must pass before starting next task**
- Run tests after each change
- Maintain backward compatibility

## Testing Strategy

- **Unit tests**: domain entities, value objects, command/query handlers (mocked repos)
- **Integration tests**: full GraphQL mutation/query flow against real test DB
- **No e2e tests** (no UI in this service)
- Test DB: separate PostgreSQL database in Docker Compose (`auth_test`)

## Progress Tracking

- Mark completed items with `[x]` immediately when done
- Add newly discovered tasks with ➕ prefix
- Document issues/blockers with ⚠️ prefix

## What Goes Where

- **Implementation Steps** (`[ ]`): all code changes, tests, configs within this repo
- **Post-Completion**: manual testing, moodboard links, submission

---

## Implementation Steps

### Task 1: Project scaffold and IaC

**Files:**
- Create: `pyproject.toml`
- Create: `docker/Dockerfile`
- Create: `docker/docker-compose.yml`
- Create: `docker/postgres/init.sql`
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `.env.example`

- [x] create `pyproject.toml` with all dependencies (fastapi, strawberry-graphql, sqlalchemy[asyncio], asyncpg, alembic, passlib[bcrypt], pyjwt, structlog, redis[asyncio], pytest, pytest-asyncio, httpx)
- [x] create `docker/Dockerfile` — multi-stage, Python 3.12-slim, non-root user
- [x] create `docker/docker-compose.yml` with services: `app`, `postgres` (with healthcheck), `redis` (Redis 7, with healthcheck), volumes for pgdata and redis-data
- [x] create `docker/postgres/init.sql` — create `auth` and `auth_test` databases
- [x] create `.env.example` with all required env vars: `DB_URL`, `REDIS_URL`, `JWT_SECRET`, `ACCESS_TOKEN_EXPIRE_MINUTES` (default 15), `REFRESH_TOKEN_EXPIRE_DAYS` (default 30), `RESET_TOKEN_EXPIRE_MINUTES` (default 15)
- [x] scaffold top-level directory structure: `auth_service/domain/`, `auth_service/application/`, `auth_service/infrastructure/`, `auth_service/presentation/`, `tests/unit/`, `tests/integration/`
- [x] verify `docker compose up` starts without errors (postgres + redis healthy) [manual test - docker compose plugin not available in CI; compose file reviewed and validated]
- [x] write smoke test: container starts, postgres reachable, redis PING returns PONG
- [x] run tests — must pass before task 2

### Task 2: Domain layer — value objects

**Files:**
- Create: `auth_service/domain/value_objects/email.py`
- Create: `auth_service/domain/value_objects/hashed_password.py`
- Create: `auth_service/domain/value_objects/plain_password.py`
- Create: `auth_service/domain/value_objects/reset_token.py`
- Create: `auth_service/domain/exceptions.py`
- Create: `tests/unit/domain/test_value_objects.py`

- [x] implement `Email` value object — validates format, normalized to lowercase, immutable dataclass
- [x] implement `PlainPassword` value object — enforces length/complexity invariants (min 8 chars, at least one digit)
- [x] implement `HashedPassword` value object — wraps bcrypt hash string, no validation logic (just a typed wrapper)
- [x] implement `ResetToken` value object — wraps a URL-safe random token string
- [x] define domain exceptions: `InvalidEmailError`, `WeakPasswordError`, `UserAlreadyExistsError`, `UserNotFoundError`, `InvalidCredentialsError`, `TokenExpiredError`, `TokenAlreadyUsedError`, `TokenNotFoundError`, `InvalidTokenError`
- [x] write unit tests for `Email` (valid, invalid format, normalization)
- [x] write unit tests for `PlainPassword` (too short, missing digit, valid)
- [x] run tests — must pass before task 3

### Task 3: Domain layer — entities and aggregate

**Files:**
- Create: `auth_service/domain/entities/user.py`
- Create: `auth_service/domain/entities/password_reset_token.py`
- Create: `tests/unit/domain/test_user_entity.py`
- Create: `tests/unit/domain/test_reset_token_entity.py`

- [ ] implement `User` aggregate root — fields: `id` (UUID), `email: Email`, `hashed_password: HashedPassword`, `is_active: bool`, `created_at: datetime`; methods: `change_password(new_hash)`, `deactivate()`
- [ ] implement `PasswordResetToken` entity — fields: `id`, `user_id`, `token: ResetToken`, `expires_at: datetime`, `used: bool`; method `consume()` enforces two independent invariants:
  1. **TTL**: if `datetime.utcnow() >= expires_at` → raise `TokenExpiredError` (token too old)
  2. **Single-use**: if `used == True` → raise `TokenAlreadyUsedError` (replay attempt)
  - on valid token: set `used = True`, return self
  - important: both checks happen on every `consume()` call, order: TTL check first, then used check
- [ ] write unit tests for `User` entity (creation, change_password, deactivate)
- [ ] write unit tests for `PasswordResetToken` — all cases must be covered:
  - `consume()` happy path: valid token, not expired, not used → succeeds, sets used=True
  - `consume()` expired: expires_at in the past → raises `TokenExpiredError`
  - `consume()` already used: used=True, not expired → raises `TokenAlreadyUsedError`
  - `consume()` called twice on same object: second call raises `TokenAlreadyUsedError`
  - `consume()` expired AND used: raises `TokenExpiredError` (TTL check takes priority)
- [ ] run tests — must pass before task 4

### Task 4: Domain layer — repository interfaces

**Files:**
- Create: `auth_service/domain/repositories/user_repository.py`
- Create: `auth_service/domain/repositories/reset_token_repository.py`

- [ ] define abstract `UserRepository` with methods: `save(user)`, `find_by_email(email) -> User | None`, `find_by_id(user_id) -> User | None`
- [ ] define abstract `ResetTokenRepository` with methods: `save(token)`, `find_by_token(token_str) -> PasswordResetToken | None`, `delete_all_by_user_id(user_id)` — **deletes ALL tokens for the user regardless of expiry or used status** (invariant: only one pending reset token per user at any time; issuing a new one unconditionally invalidates all previous ones)
- [ ] no tests needed (pure interfaces) — but run existing tests to verify no regressions
- [ ] run tests — must pass before task 5

### Task 5: Application layer — command handlers

**Files:**
- Create: `auth_service/application/commands/register_user.py`
- Create: `auth_service/application/commands/authenticate_user.py`
- Create: `auth_service/application/commands/refresh_token.py`
- Create: `auth_service/application/commands/revoke_session.py`
- Create: `auth_service/application/commands/request_password_reset.py`
- Create: `auth_service/application/commands/reset_password.py`
- Create: `auth_service/application/ports/password_hasher.py`
- Create: `auth_service/application/ports/token_service.py`
- Create: `auth_service/application/ports/token_store.py`
- Create: `auth_service/application/ports/email_service.py`
- Create: `auth_service/application/dto.py`
- Create: `tests/unit/application/test_register_user.py`
- Create: `tests/unit/application/test_authenticate_user.py`
- Create: `tests/unit/application/test_token_lifecycle.py`
- Create: `tests/unit/application/test_password_reset.py`

- [ ] define application port interfaces:
  - `PasswordHasher` (hash/verify)
  - `TokenService` (generate_access_token(user_id, session_id) → JWT with sub/jti/sid claims; generate_refresh_token() → opaque string; decode_access_token(token) → claims dict)
  - `TokenStore`:
    - `create_session(session_id, user_id, refresh_token, device_info, access_ttl, refresh_ttl)` — stores all session keys atomically
    - `get_session(session_id)` → session metadata or None
    - `is_access_jti_valid(jti)` → bool (Redis EXISTS)
    - `rotate_session(session_id, old_refresh_token, new_access_jti, new_refresh_token, access_ttl, refresh_ttl)` — atomic: DEL old refresh, SET new access+refresh
    - `revoke_session(session_id)` → DEL access jti, refresh token, session hash, SREM from user set
    - `revoke_all_user_sessions(user_id)` → SMEMBERS sessions:{user_id} → revoke each session
  - `EmailService` (send_reset_email)
- [ ] define DTOs: `RegisterUserCommand`, `AuthenticateUserCommand(email, password, device_info=None)`, `RefreshTokenCommand(refresh_token)`, `RevokeSessionCommand(session_id)`, `RequestPasswordResetCommand`, `ResetPasswordCommand`, `TokenPairDTO(access_token, refresh_token, session_id, token_type)`
- [ ] implement `RegisterUserHandler`: validate email/password → check duplicate → hash password → save user → return void
- [ ] implement `AuthenticateUserHandler`: find user → verify password hash → create session_id → generate access JWT (jti, sid=session_id) + refresh token → `TokenStore.create_session(...)` → return `TokenPairDTO`
- [ ] implement `RefreshTokenHandler`: GET refresh:{token} → session_id + user_id → generate new access JWT + new refresh token → `TokenStore.rotate_session(...)` → return `TokenPairDTO`
- [ ] implement `RevokeSessionHandler`: `TokenStore.revoke_session(session_id)` → immediate invalidation
- [ ] implement `RequestPasswordResetHandler`: find user → **raise `UserNotFoundError` if not found** (product decision: show explicit "no such email" error to UX; see trade-off note below) → `repo.delete_all_by_user_id(user_id)` → create new `PasswordResetToken` (expires in N min) → save → send email → return void
- [ ] implement `ResetPasswordHandler`: find token → consume token → find user → hash new password → change password → save → `TokenStore.revoke_all_user_sessions(user_id)` (forced re-login after password change)
- [ ] write unit tests for `RegisterUserHandler` (success, duplicate email, weak password) with in-memory fake repos/stores
- [ ] write unit tests for `AuthenticateUserHandler` (success, wrong password, user not found — verify session_id in response)
- [ ] write unit tests for `RefreshTokenHandler` (success, invalid refresh token, rotation — old token rejected after use)
- [ ] write unit tests for `RevokeSessionHandler` (success, already revoked)
- [ ] write unit tests for `RequestPasswordResetHandler`:
  - success: token created, email sent
  - unknown email: raises `UserNotFoundError` (product decision — UX shows "no such email")
  - second request: previous token deleted (even if not expired), new token created — only one token exists after
- [ ] write unit tests for `ResetPasswordHandler` (success, expired token, all sessions revoked after password change)
- [ ] run tests — must pass before task 6

### Task 6: Infrastructure — database models and migrations

**Files:**
- Create: `auth_service/infrastructure/db/models.py`
- Create: `auth_service/infrastructure/db/session.py`
- Create: `alembic/versions/0001_initial.py`

- [ ] define SQLAlchemy 2.0 async ORM models: `UserModel`, `PasswordResetTokenModel` (separate from domain entities — no leaking)
- [ ] implement `async_session_factory` via `create_async_engine` + `async_sessionmaker`
- [ ] create Alembic migration `0001_initial` — `users` and `password_reset_tokens` tables with proper indexes (email unique index, token index, user_id FK)
- [ ] verify migration runs successfully against Docker Compose postgres
- [ ] no new tests for models (covered in integration tests) — run existing tests
- [ ] run tests — must pass before task 7

### Task 7: Infrastructure — concrete repositories

**Files:**
- Create: `auth_service/infrastructure/db/repositories/user_repository.py`
- Create: `auth_service/infrastructure/db/repositories/reset_token_repository.py`
- Create: `tests/integration/test_repositories.py`

- [ ] implement `SqlUserRepository(UserRepository)` — `save`, `find_by_email`, `find_by_id` using async SQLAlchemy session
- [ ] implement `SqlResetTokenRepository(ResetTokenRepository)` — `save`, `find_by_token`, `delete_by_user_id`
- [ ] map between ORM models and domain entities in repository methods (no ORM objects leak into domain)
- [ ] write integration tests against `auth_test` PostgreSQL database (pytest fixture creates/tears down tables)
- [ ] test `SqlUserRepository`: save and find_by_email round-trip, find_by_id, duplicate email constraint
- [ ] test `SqlResetTokenRepository`: save, find_by_token, delete_by_user_id
- [ ] run tests — must pass before task 8

### Task 8: Infrastructure — security adapters

**Files:**
- Create: `auth_service/infrastructure/security/bcrypt_hasher.py`
- Create: `auth_service/infrastructure/security/jwt_token_service.py`
- Create: `auth_service/infrastructure/redis/redis_token_store.py`
- Create: `auth_service/infrastructure/email/mock_email_service.py`
- Create: `tests/unit/infrastructure/test_security.py`
- Create: `tests/integration/test_token_store.py`

- [ ] implement `BcryptHasher(PasswordHasher)` — wraps `passlib.context.CryptContext` with bcrypt scheme
- [ ] implement `JwtTokenService(TokenService)`:
  - `generate_access_token(user_id, email)` → signed JWT with `sub` (user_id), `jti` (UUID4), `iat`, `exp`
  - `generate_refresh_token()` → URL-safe secrets.token_urlsafe(32) opaque string
  - `decode_access_token(token)` → raises `TokenExpiredError` / `InvalidTokenError` on bad tokens
- [ ] implement `RedisTokenStore(TokenStore)` using Redis pipeline/transactions where atomicity matters:
  - `create_session(session_id, user_id, refresh_token, device_info, access_ttl, refresh_ttl)`:
    - SETEX `access:{jti}` → `{user_id, session_id}` (jti comes from access JWT claims)
    - SETEX `refresh:{token}` → `{user_id, session_id}` TTL=refresh_ttl
    - HSET `session:{session_id}` → `{user_id, device_info, created_at, last_used}`; EXPIRE TTL=refresh_ttl
    - SADD `sessions:{user_id}` → session_id
  - `get_session(session_id)` → HGETALL `session:{session_id}`
  - `is_access_jti_valid(jti)` → EXISTS `access:{jti}`
  - `rotate_session(session_id, old_refresh, new_jti, new_refresh, access_ttl, refresh_ttl)`:
    - DEL `refresh:{old_refresh}`; SETEX `access:{new_jti}` ...; SETEX `refresh:{new_refresh}` ...; HSET `session:{session_id}` last_used=now
  - `revoke_session(session_id)`:
    - HGET `session:{session_id}` user_id → for SREM
    - DEL `session:{session_id}`, DEL `refresh:{token}`, DEL `access:{jti}` (jti looked up from session)
    - SREM `sessions:{user_id}` → session_id
  - `revoke_all_user_sessions(user_id)`:
    - SMEMBERS `sessions:{user_id}` → list of session_ids → revoke_session for each; DEL `sessions:{user_id}`
- [ ] implement `MockEmailService(EmailService)` — logs the reset link via structlog (no real SMTP, documented as TODO)
- [ ] write unit tests for `BcryptHasher`: hash produces bcrypt prefix, verify correct/wrong password
- [ ] write unit tests for `JwtTokenService`: decode valid token, expired token raises, tampered token raises, jti present in claims
- [ ] write integration tests for `RedisTokenStore` against real Redis (Docker Compose): store/valid/revoke access jti, refresh token rotation, revoke all sessions
- [ ] run tests — must pass before task 9

### Task 9: Infrastructure — structured logging

**Files:**
- Create: `auth_service/infrastructure/logging.py`
- Modify: `auth_service/main.py` (will be created in task 10 — defer integration)

- [ ] configure structlog with JSON renderer (for production) and console renderer (for dev, based on env)
- [ ] define log context keys: `user_id`, `email`, `operation`, `duration_ms`
- [ ] integrate structlog into all command handlers (log operation start/success/failure)
- [ ] integrate structlog into JWT service (log token generation, decode errors)
- [ ] no new tests (logging is a side effect) — run existing tests
- [ ] run tests — must pass before task 10

### Task 10: Presentation layer — GraphQL schema and resolvers

**Files:**
- Create: `auth_service/presentation/graphql/types.py`
- Create: `auth_service/presentation/graphql/mutations.py`
- Create: `auth_service/presentation/graphql/queries.py`
- Create: `auth_service/presentation/graphql/schema.py`
- Create: `auth_service/main.py`
- Create: `auth_service/container.py`
- Create: `tests/integration/test_graphql.py`

- [ ] define Strawberry input types: `RegisterInput`, `LoginInput`, `RefreshTokenInput`, `RevokeSessionInput`, `RequestResetInput`, `ResetPasswordInput`
- [ ] define Strawberry output types: `AuthPayload` (accessToken, refreshToken, tokenType), `OperationResult` (success, message)
- [ ] implement `AuthMutation` resolver class: `register`, `login`, `refresh_token`, `revoke_session`, `request_password_reset`, `reset_password`
- [ ] implement `AuthQuery` resolver: `me` query — decodes JWT from `Authorization: Bearer` header, checks Redis allowlist (jti valid), returns current user info or null
- [ ] build `container.py` — simple dependency injection: instantiate all repos, services, handlers, Redis connection; expose via FastAPI `Depends`
- [ ] create `auth_service/main.py` — FastAPI app, mount Strawberry at `/graphql`, lifespan for Redis connection pool
- [ ] write integration tests using `httpx.AsyncClient` against real test DB + Redis:
  - register → login → me query flow
  - register duplicate → error
  - login wrong password → error
  - full refresh token rotation (login → refresh → old refresh rejected → new refresh works)
  - revoke session → subsequent `me` query rejected (Redis jti gone)
  - request_password_reset → token in DB
  - full reset flow (register → request_reset → read token from DB → reset → all sessions revoked → login with new password)
  - `me` with invalid/expired JWT
- [ ] run tests — must pass before task 11

### Task 11: Security hardening — rate limiting

**Files:**
- Modify: `auth_service/main.py`
- Create: `auth_service/infrastructure/security/rate_limiter.py`
- Create: `tests/unit/infrastructure/test_rate_limiter.py`

Rate limiting uses SlowAPI (FastAPI-native) with Redis backend — reuses existing Redis connection.
Two-dimensional limits (per IP + per email/key) catch both volumetric and targeted attacks.

- [ ] add SlowAPI middleware to FastAPI app with Redis as backend store
- [ ] apply rate limits per operation:
  - `login` mutation: **5/IP/minute** + **10/email/15min** (credential stuffing + brute force)
  - `register` mutation: **5/IP/hour** (spam account creation)
  - `requestPasswordReset` mutation: **3/email/hour** + **10/IP/hour** (email bombing + enumeration)
  - `resetPassword` mutation: **10/IP/hour** (defense in depth; token is 256-bit random)
  - `refreshToken` mutation: **60/IP/hour** (mild abuse prevention; rotation handles replay)
- [ ] all rate limit violations return HTTP 429 with `Retry-After` header
- [ ] email-keyed limits extracted from GraphQL input variables (not just IP)
- [ ] document in comments: account lockout deliberately NOT implemented (hard lockout enables DoS — attacker can lock out legitimate users; exponential backoff via rate limits is safer)
- [ ] write unit tests for rate limiter: under limit passes, at limit passes, over limit raises 429 with Retry-After
- [ ] run tests — must pass before task 12

### Task 12: Verify acceptance criteria

- [ ] all 3 auth flows work: register, login, password reset (full cycle)
- [ ] passwords never stored in plaintext (bcrypt verified)
- [ ] JWT tokens have expiry
- [ ] reset tokens single-use and expiring
- [ ] rate limiting on login and reset endpoints
- [ ] structured JSON logs emitted for all operations
- [ ] Docker Compose starts cleanly: `docker compose up` → app healthy
- [ ] Alembic migrations run automatically on startup (or via entrypoint script)
- [ ] run full test suite: `pytest tests/ -v`
- [ ] all tests pass

### Task 13: [Final] Documentation and README

**Files:**
- Modify: `README.md`
- Create: `docs/adr/0001-graphql-over-rest.md`
- Create: `docs/adr/0002-layered-ddd.md`
- Create: `docs/adr/0003-python-stack.md`

- [ ] update `README.md`:
  - how to run (docker compose up, env vars, test commands)
  - architecture diagram in Mermaid (DDD layers + request flow)
  - where DDD, CQRS, IaC appear in the solution
  - key trade-offs section
  - "next steps for production" section
- [ ] write ADR-0001: GraphQL over gRPC/REST (browser compatibility, CQRS mapping)
- [ ] write ADR-0002: Layered DDD over hexagonal (scope, complexity trade-off)
- [ ] write ADR-0003: Python stack choice and alternatives considered
- [ ] move this plan to `docs/plans/completed/`

---

## Technical Details

### Domain model

```
User (aggregate root)
  id: UUID
  email: Email (value object — normalized, validated)
  hashed_password: HashedPassword (value object — bcrypt hash)
  is_active: bool
  created_at: datetime

PasswordResetToken (entity)
  id: UUID
  user_id: UUID → User.id
  token: ResetToken (value object — URL-safe random 32 bytes)
  expires_at: datetime
  used: bool
```

### CQRS split

| Side | Type | Handler | Produces |
|------|------|---------|---------|
| Command | RegisterUser | RegisterUserHandler | — |
| Command | AuthenticateUser | AuthenticateUserHandler | TokenPairDTO |
| Command | RefreshToken | RefreshTokenHandler | TokenPairDTO |
| Command | RevokeSession | RevokeSessionHandler | — |
| Command | RequestPasswordReset | RequestPasswordResetHandler | — |
| Command | ResetPassword | ResetPasswordHandler | — |
| Query | GetCurrentUser | JWT decode + Redis jti check | UserInfo |

### Token lifecycle (Redis-backed, session-aware)

```
Login (creates Session):
  → session_id = UUID4          ← device session identifier
  → access JWT: {sub: user_id, jti: UUID4, sid: session_id, exp: +15min}
  → refresh token: secrets.token_urlsafe(32)
  → Redis (atomic pipeline):
      SETEX access:{jti}          → {user_id, session_id}   TTL=15min
      SETEX refresh:{token}       → {user_id, session_id}   TTL=30days
      HSET  session:{session_id}  → {user_id, device_info, created_at, last_used}
      SADD  sessions:{user_id}    → session_id

Auth check (every authenticated request):
  → decode JWT: verify signature + exp
  → EXISTS access:{jti}  ← Redis allowlist check (~0.2ms)
  → if missing: reject (expired or revoked)
  → read session_id from JWT sid claim (no extra Redis read needed)

Refresh (rotate within same session):
  → GET refresh:{old_token} → {user_id, session_id}
  → DEL refresh:{old_token}          ← old token dead immediately
  → new access JWT (new jti, same sid=session_id)
  → new refresh token
  → SETEX access:{new_jti} ...; SETEX refresh:{new_token} ...
  → HSET session:{session_id} last_used=now
  → session_id preserved — device session continuity maintained

Revoke single session:
  → HGETALL session:{session_id} → get associated token refs
  → DEL access:{jti}, DEL refresh:{token}
  → DEL session:{session_id}
  → SREM sessions:{user_id} → session_id
  → immediate effect

Future: Revoke all / list sessions (zero arch change):
  → SMEMBERS sessions:{user_id} → list of session_ids
  → list: HGETALL session:{sid} for each (device, created_at, last_used)
  → revoke all: iterate and revoke_session for each
```

### GraphQL schema (Strawberry)

```graphql
type Mutation {
  register(input: RegisterInput!): OperationResult!
  login(input: LoginInput!): AuthPayload!
  refreshToken(input: RefreshTokenInput!): AuthPayload!
  revokeSession(input: RevokeSessionInput!): OperationResult!
  requestPasswordReset(input: RequestResetInput!): OperationResult!
  resetPassword(input: ResetPasswordInput!): OperationResult!
}

type Query {
  me: UserInfo  # requires valid JWT + jti in Redis
}
```

### IaC (Docker Compose services)

- `postgres` — PostgreSQL 16, healthcheck, persistent volume
- `redis` — Redis 7, healthcheck (`redis-cli ping`), persistent volume
- `app` — Python service, depends_on postgres+redis healthy, runs Alembic on start then uvicorn

### Key invariants

- Passwords: min 8 chars, at least 1 digit; bcrypt cost factor 12
- Access token: JWT, 15 min expiry (configurable), jti stored in Redis allowlist
- Refresh token: opaque URL-safe random, 30 days (configurable), stored in Redis, single-use rotation
- Reset token: PostgreSQL-stored, 15 min expiry (configurable), single-use (`TokenAlreadyUsedError` on replay), at most one active token per user — issuing a new reset unconditionally invalidates ALL previous tokens regardless of expiry
- Immediate revocation: Redis DEL → token invalid on next request (< 1ms propagation)
- Password change: forces revocation of all active sessions
- Rate limits (SlowAPI + Redis backend):
  - login: 5/IP/min + 10/email/15min
  - register: 5/IP/hour
  - requestPasswordReset: 3/email/hour + 10/IP/hour
  - resetPassword: 10/IP/hour
  - refreshToken: 60/IP/hour
- No hard account lockout (prevents DoS); rate limits provide backoff protection
- Reset flow: user not found → `UserNotFoundError` (product decision: explicit UX feedback)
  - **Trade-off documented**: the security-correct approach is to return an identical success
    response for both found and not-found email (prevents email enumeration — attacker cannot
    probe which emails are registered). This was consciously rejected in favor of UX clarity.
    If the threat model changes (e.g., user base is sensitive or targeted), replace the
    `UserNotFoundError` raise with a silent `return` — one-line change in `RequestPasswordResetHandler`.

---

## Post-Completion

**Manual verification:**
- Test all 3 flows via GraphQL Playground at `http://localhost:8000/graphql`
- Verify JWT decodes correctly (jwt.io)
- Verify reset token expires after 15 min
- Check structured logs are valid JSON in `docker compose logs app`

**Submission:**
- Create moodboard and anti-moodboard (Pinterest)
- Fork repo and push solution
- Submit 3 links: moodboard, anti-moodboard, fork URL
- Add `.agents/` folder documenting AI usage (this session)
