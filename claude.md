# CLAUDE.md — AI knowledge base for auth_service

## Project overview

Production-quality authentication service (DDD + CQRS + GraphQL). Three user flows:
Registration, Login, Password Recovery.

## Architecture

Strict DDD layering — no framework types in inner layers:

```
domain/         — entities, value objects, repository interfaces, exceptions
application/    — command handlers, port interfaces (PasswordHasher, TokenService, etc.)
infrastructure/ — SQLAlchemy repos, Redis token store, bcrypt, JWT, rate limiter
presentation/   — Strawberry GraphQL mutations/queries
container.py    — dependency wiring (GlobalContainer + request_scope context var)
main.py         — FastAPI app, ASGI middleware, lifespan
```

## Test execution model

Integration tests connect to services by Docker Compose service name (`postgres`, `redis`).
They CANNOT run outside the Compose network — they will fail with a connection error, not skip.

```bash
# Unit tests — run locally, no services needed
pytest tests/unit/ -v

# Full suite — must run inside the Compose network
docker compose -f docker/docker-compose.yml run --rm app pytest tests/ -v
```

## Test database allocation

| Scope | PostgreSQL DB | Redis DB |
|---|---|---|
| App (runtime) | `auth` | DB 0 |
| Repository integration tests | `auth_test` | — |
| Token store integration tests | — | DB 1 |
| GraphQL integration tests | `auth_test` | DB 2 |

`.env.docker` is the env_file used by docker-compose.yml for the `app` service; it sets all
URLs with Docker service names (`postgres`, `redis`). `.env` is for local dev (localhost URLs).
`REDIS_TOKEN_TEST_URL` (DB1) is used by token store integration tests.

## Key conventions

- All async; SQLAlchemy 2.0 async sessions, redis.asyncio
- Request-scoped DB session via `request_scope` context var in container.py
- Access tokens: short-lived JWTs with `jti`; revoked JTIs stored in Redis
- Refresh tokens: opaque UUIDs stored in Redis under `refresh:{token}` key
- Sessions keyed as `session:{session_id}` hash in Redis; tracked per-user in `sessions:{user_id}` set
- Rate limiting via SlowAPI with Redis backend; email-keyed limits on `login` and `requestPasswordReset`
- Structured logging via structlog; JSON in production (`LOG_FORMAT=json`), console in dev (`LOG_FORMAT=console`)

## Build / migration commands

```bash
# Run database migrations inside the container
docker compose -f docker/docker-compose.yml run --rm app alembic upgrade head

# Create a new migration
docker compose -f docker/docker-compose.yml run --rm app alembic revision --autogenerate -m "description"
```
