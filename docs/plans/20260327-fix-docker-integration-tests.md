# Fix Docker Integration Tests

## Overview

Integration tests currently reference `localhost` for PostgreSQL and Redis, which fails when
tests run inside a Docker container (via ralphex agent orchestration). The fix is to point
all connectivity checks and default URLs at Docker service names (`postgres`, `redis`) that
are already running in the same Docker network.

No local-fallback compatibility required — Docker-only is the target execution environment.

## Prerequisites
Check that postgres and redis awailable in Docker network.
Stop any further execution and exit if they are not.

## Context (from discovery)

- Files involved:
  - `tests/integration/test_repositories.py` — partially fixed (host check uses `postgres`, but default URL still has `localhost`)
  - `tests/integration/test_token_store.py` — REDIS_URL already fixed
  - `tests/integration/test_graphql.py` — still uses `localhost` everywhere
  - `docker/docker-compose.yml` — test volume mount added; missing `DB_TEST_URL` env var
- pytest-asyncio is configured with `asyncio_mode = "auto"` → `@pytest.mark.asyncio` decorators are redundant but harmless
- `auth_test` database is created by `docker/postgres/init.sql` on container start
- Redis DB 1 is used by repo tests, DB 2 by GraphQL tests (DB 0 is the app)

## Development Approach

- **Testing approach**: Regular (fix code, then verify tests pass)
- Make small, focused changes per file
- All tests must pass before moving to the next task

## Progress Tracking

- Mark completed items with `[x]` immediately when done
- Add newly discovered tasks with ➕ prefix
- Document issues/blockers with ⚠️ prefix

## What Goes Where

- **Implementation Steps**: code changes in this repo
- **Post-Completion**: manual Docker verification steps

## Implementation Steps

### Task 1: Fix `test_repositories.py`

**Files:**
- Modify: `tests/integration/test_repositories.py`

- [x] Change `_TEST_DB_URL` default from `localhost:5432` to `postgres:5432`
- [x] Remove dead code `return False` after `raise` in `_check_db_available()` (unreachable line)
- [x] Run unit tests to confirm no regressions: `pytest tests/unit/ -q`

### Task 2: Fix `test_graphql.py`

**Files:**
- Modify: `tests/integration/test_graphql.py`

- [x] Change `_TEST_DB_URL` default from `localhost:5432` to `postgres:5432`
- [x] Change `_REDIS_URL` default from `localhost:6379/2` to `redis:6379/2`
- [x] Change `_port_open("localhost", 5432)` to `_port_open("postgres", 5432)`
- [x] Change `_port_open("localhost", 6379)` to `_port_open("redis", 6379)`
- [x] Run unit tests to confirm no regressions: `pytest tests/unit/ -q`

### Task 3: Add `DB_TEST_URL` to docker-compose.yml

**Files:**
- Modify: `docker/docker-compose.yml`

- [x] Add `DB_TEST_URL: "postgresql+asyncpg://auth_user:auth_password@postgres:5432/auth_test"` to the `app` service environment block
- [x] Add `REDIS_TEST_URL: "redis://redis:6379/2"` to the `app` service environment block (used by `test_graphql.py`)

### Task 4: Verify acceptance criteria

- [ ] Confirm all integration tests pass (no skips due to unavailable services)
- [ ] Run full suite to confirm no regressions

### Task 5: [Final] Update documentation

- [ ] Move this plan to `docs/plans/completed/`

## Technical Details

**Host resolution in Docker:**
- `localhost` inside a container refers to the container itself, not sibling services
- Docker Compose creates a default bridge network; services are reachable by their service name
- `postgres` → PostgreSQL on port 5432
- `redis` → Redis on port 6379

**Database allocation:**
| Service | DB index | Purpose |
|---------|----------|---------|
| App | `auth` | Production data |
| `test_repositories.py` | `auth_test` | Repo integration tests |
| `test_token_store.py` | Redis DB 1 | Token store tests |
| `test_graphql.py` | `auth_test` + Redis DB 2 | Full GraphQL flow tests |

## Post-Completion

**Manual verification:**
- Confirm `pytest tests/integration/ -v` produces zero skipped tests when run inside Docker
- Confirm `pytest tests/unit/ -v` still passes when run locally (no services needed)
