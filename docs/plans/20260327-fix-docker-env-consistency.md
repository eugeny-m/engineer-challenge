# Fix Docker/Env Configuration Consistency

## Overview

Two related problems in the current config:

1. **`.env` syntax is broken**: uses YAML-style `KEY: "value"` on some lines; Docker service-name URLs are mixed with localhost URLs; postgres container vars (`POSTGRES_USER` etc.) don't belong in the app's env_file.
2. **Tests read undefined env vars**: `test_infrastructure.py` uses `POSTGRES_HOST`, `POSTGRES_PORT`, `REDIS_HOST`, `REDIS_PORT` which are never injected anywhere — causing Docker-context skip checks to use wrong defaults. `test_token_store.py` hardcodes `redis://redis:6379/1`, which breaks local development.

**Approach**: single env_file per context — `.env` for local dev (localhost URLs), `.env.docker` for Docker Compose (service-name URLs). Remove `environment:` override block from docker-compose.yml.

## Context (from discovery)

- Files involved: `.env`, `.env.example`, `docker/docker-compose.yml`, `tests/smoke/test_infrastructure.py`, `tests/integration/test_token_store.py`
- Related files already correct: `tests/integration/test_repositories.py`, `tests/integration/test_graphql.py` (use `DB_TEST_URL`/`REDIS_TEST_URL` env vars with fallbacks)
- Redis DB allocation: DB0=app, DB1=repo+token tests, DB2=graphql tests

## Development Approach

- **Testing approach**: Regular (code first, then verify)
- Complete each task fully before moving to the next
- Run full test suite after all changes via: `docker compose -f docker/docker-compose.yml run --rm app pytest tests/ -v`

## Progress Tracking

- mark completed items with `[x]` immediately when done
- add newly discovered tasks with ➕ prefix
- document issues/blockers with ⚠️ prefix

## Implementation Steps

### Task 1: Fix `.env` for local development

**Files:**
- Modify: `.env`

- [x] Remove lines 1–9 that use broken YAML syntax (`KEY: "value"`) and Docker service names
- [x] Ensure all vars use `KEY=value` format (no colons, no quotes)
- [x] Use `localhost` in DB_URL, DB_TEST_URL, REDIS_URL, REDIS_TEST_URL
- [x] Add `REDIS_TOKEN_TEST_URL=redis://localhost:6379/1` (for token store tests, DB1)
- [x] Remove `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` (these are postgres container vars, not app config)
- [x] Final `.env` should have: DB_URL, DB_TEST_URL, REDIS_URL, REDIS_TEST_URL, REDIS_TOKEN_TEST_URL, JWT_SECRET, ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS, RESET_TOKEN_EXPIRE_MINUTES, LOG_FORMAT

### Task 2: Create `.env.docker` for Docker Compose

**Files:**
- Create: `.env.docker`

- [x] Create `.env.docker` with same vars as `.env` but using Docker service names (`postgres`, `redis`) instead of `localhost`
- [x] DB_URL: `postgresql+asyncpg://auth_user:auth_password@postgres:5432/auth`
- [x] DB_TEST_URL: `postgresql+asyncpg://auth_user:auth_password@postgres:5432/auth_test`
- [x] REDIS_URL: `redis://redis:6379/0`
- [x] REDIS_TEST_URL: `redis://redis:6379/2`
- [x] REDIS_TOKEN_TEST_URL: `redis://redis:6379/1`
- [x] All other vars (JWT_SECRET, token expiry, LOG_FORMAT) same as `.env`

### Task 3: Update `docker-compose.yml` to use `.env.docker`

**Files:**
- Modify: `docker/docker-compose.yml`

- [x] Change `env_file` in `app` service from `../.env` to `../.env.docker`
- [x] Remove the entire `environment:` block from `app` service (vars are now in `.env.docker`)
- [x] Verify `volumes:` block is unchanged (keep the `pyproject.toml` mount)

### Task 4: Update `.env.example`

**Files:**
- Modify: `.env.example`

- [ ] Ensure all vars use `KEY=value` format
- [ ] Use `localhost` URLs (local dev template)
- [ ] Add `REDIS_TOKEN_TEST_URL=redis://localhost:6379/1`
- [ ] Add `REDIS_TEST_URL=redis://localhost:6379/2` (was missing)
- [ ] Remove `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` if present

### Task 5: Fix `test_infrastructure.py` — derive host/port from URL env vars

**Files:**
- Modify: `tests/smoke/test_infrastructure.py`

- [ ] Remove `POSTGRES_HOST`, `POSTGRES_PORT`, `REDIS_HOST`, `REDIS_PORT` variables
- [ ] Parse PostgreSQL host/port from `DB_URL` env var (fallback: `localhost:5432`)
- [ ] Parse Redis host/port from `REDIS_URL` env var (fallback: `localhost:6379`)
- [ ] Use parsed values in `postgres_available` and `redis_available` skip markers
- [ ] Fix `test_redis_ping`: add fallback `REDIS_URL=redis://localhost:6379/0` (currently crashes if REDIS_URL not set)
- [ ] Verify skip logic still works: when services are unreachable, tests skip; when reachable, they run

### Task 6: Fix `test_token_store.py` — use env var for Redis URL

**Files:**
- Modify: `tests/integration/test_token_store.py`

- [ ] Replace hardcoded `REDIS_URL = "redis://redis:6379/1"` with `os.environ.get("REDIS_TOKEN_TEST_URL", "redis://localhost:6379/1")`
- [ ] Add `import os` if not present
- [ ] Rename variable to avoid confusion with the app-level `REDIS_URL`

### Task 7: Verify acceptance criteria

- [ ] Run unit tests locally: `pytest tests/unit/ -v` (should pass without Docker)
- [ ] Run full suite in Docker: `docker compose -f docker/docker-compose.yml run --rm app pytest tests/ -v`
- [ ] Confirm smoke tests correctly detect service names inside Docker (not `localhost`)
- [ ] Confirm smoke tests skip gracefully outside Docker (localhost not reachable)
- [ ] Confirm integration tests connect using Docker service names
- [ ] Confirm token store tests no longer hardcode Redis URL

### Task 8: [Final] Cleanup

- [ ] Delete `docs/fixes.md` (issues addressed)
- [ ] Update CLAUDE.md if env configuration patterns changed
- [ ] Move this plan to `docs/plans/completed/`

## Technical Details

**URL env var parsing** (for test_infrastructure.py):
```python
from urllib.parse import urlparse

_db_url = os.environ.get("DB_URL", "postgresql+asyncpg://localhost:5432/auth")
_parsed_pg = urlparse(_db_url)
POSTGRES_HOST = _parsed_pg.hostname or "localhost"
POSTGRES_PORT = _parsed_pg.port or 5432

_redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
_parsed_redis = urlparse(_redis_url)
REDIS_HOST = _parsed_redis.hostname or "localhost"
REDIS_PORT = _parsed_redis.port or 6379
```

**`.env.docker` vs `.env` diff**: only `@postgres`/`@redis` vs `@localhost` in URLs.

**Redis DB allocation** (unchanged):
| Scope | Redis DB | Env var |
|---|---|---|
| App runtime | DB 0 | REDIS_URL |
| Repo + token store tests | DB 1 | REDIS_TOKEN_TEST_URL |
| GraphQL tests | DB 2 | REDIS_TEST_URL |

## Post-Completion

**Manual verification:**
- Test outside Docker: `pytest tests/unit/ -v` should pass
- Test inside Docker: `docker compose -f docker/docker-compose.yml run --rm app pytest tests/ -v` should pass with all integration tests running (not skipped)
- Verify `.env.docker` is git-ignored or committed as appropriate (likely should be committed since it contains no secrets — same creds as docker-compose already exposes)
