"""Integration tests for RedisTokenStore against a real Redis instance."""
import uuid
import pytest
import pytest_asyncio
import redis.asyncio as aioredis

from auth_service.infrastructure.redis.redis_token_store import RedisTokenStore

REDIS_URL = "redis://localhost:6379/1"  # use DB 1 to avoid polluting default DB

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def redis_client():
    client = aioredis.from_url(REDIS_URL, decode_responses=False)
    # Verify connectivity; skip entire module if Redis is unavailable
    try:
        await client.ping()
    except Exception:
        await client.aclose()
        pytest.skip("Redis not available — skipping integration tests")
    yield client
    await client.flushdb()  # clean up test DB
    await client.aclose()


@pytest_asyncio.fixture
async def store(redis_client):
    return RedisTokenStore(redis_client)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ids():
    return uuid.uuid4(), uuid.uuid4()  # user_id, session_id


ACCESS_TTL = 900    # 15 min
REFRESH_TTL = 2592000  # 30 days


async def _create(store, user_id, session_id, access_jti, refresh_token, device=None):
    await store.create_session(
        session_id=session_id,
        user_id=user_id,
        access_jti=access_jti,
        refresh_token=refresh_token,
        device_info=device,
        access_ttl=ACCESS_TTL,
        refresh_ttl=REFRESH_TTL,
    )


# ---------------------------------------------------------------------------
# create_session / is_access_jti_valid
# ---------------------------------------------------------------------------

async def test_create_session_access_jti_valid(store):
    user_id, session_id = _make_ids()
    jti = str(uuid.uuid4())
    refresh = "refresh-token-abc"
    await _create(store, user_id, session_id, jti, refresh)
    assert await store.is_access_jti_valid(jti) is True


async def test_create_session_unknown_jti_invalid(store):
    assert await store.is_access_jti_valid("nonexistent-jti") is False


async def test_get_session_returns_metadata(store):
    user_id, session_id = _make_ids()
    jti = str(uuid.uuid4())
    await _create(store, user_id, session_id, jti, "rt1", device="iPhone")
    data = await store.get_session(session_id)
    assert data is not None
    assert data["user_id"] == str(user_id)
    assert data["device_info"] == "iPhone"
    assert data["current_jti"] == jti


async def test_get_session_missing_returns_none(store):
    assert await store.get_session(uuid.uuid4()) is None


async def test_get_session_by_refresh_token(store):
    user_id, session_id = _make_ids()
    jti = str(uuid.uuid4())
    refresh = "my-refresh-token"
    await _create(store, user_id, session_id, jti, refresh)
    data = await store.get_session_by_refresh_token(refresh)
    assert data is not None
    assert data["user_id"] == str(user_id)
    assert data["session_id"] == str(session_id)


async def test_get_session_by_refresh_token_missing_returns_none(store):
    assert await store.get_session_by_refresh_token("nonexistent") is None


# ---------------------------------------------------------------------------
# rotate_session
# ---------------------------------------------------------------------------

async def test_rotate_session_old_refresh_rejected(store):
    user_id, session_id = _make_ids()
    old_jti = str(uuid.uuid4())
    old_refresh = "old-refresh"
    await _create(store, user_id, session_id, old_jti, old_refresh)

    new_jti = str(uuid.uuid4())
    new_refresh = "new-refresh"
    await store.rotate_session(
        session_id=session_id,
        old_refresh_token=old_refresh,
        new_access_jti=new_jti,
        new_refresh_token=new_refresh,
        access_ttl=ACCESS_TTL,
        refresh_ttl=REFRESH_TTL,
    )

    assert await store.get_session_by_refresh_token(old_refresh) is None


async def test_rotate_session_new_jti_valid(store):
    user_id, session_id = _make_ids()
    old_jti = str(uuid.uuid4())
    await _create(store, user_id, session_id, old_jti, "old-rt")

    new_jti = str(uuid.uuid4())
    await store.rotate_session(
        session_id=session_id,
        old_refresh_token="old-rt",
        new_access_jti=new_jti,
        new_refresh_token="new-rt",
        access_ttl=ACCESS_TTL,
        refresh_ttl=REFRESH_TTL,
    )

    assert await store.is_access_jti_valid(new_jti) is True
    assert await store.is_access_jti_valid(old_jti) is False


async def test_rotate_session_new_refresh_valid(store):
    user_id, session_id = _make_ids()
    await _create(store, user_id, session_id, str(uuid.uuid4()), "old-rt2")
    new_jti = str(uuid.uuid4())
    await store.rotate_session(
        session_id=session_id,
        old_refresh_token="old-rt2",
        new_access_jti=new_jti,
        new_refresh_token="new-rt2",
        access_ttl=ACCESS_TTL,
        refresh_ttl=REFRESH_TTL,
    )
    data = await store.get_session_by_refresh_token("new-rt2")
    assert data is not None
    assert data["session_id"] == str(session_id)


# ---------------------------------------------------------------------------
# revoke_session
# ---------------------------------------------------------------------------

async def test_revoke_session_jti_no_longer_valid(store):
    user_id, session_id = _make_ids()
    jti = str(uuid.uuid4())
    await _create(store, user_id, session_id, jti, "rt-revoke")
    await store.revoke_session(session_id)
    assert await store.is_access_jti_valid(jti) is False


async def test_revoke_session_refresh_gone(store):
    user_id, session_id = _make_ids()
    jti = str(uuid.uuid4())
    await _create(store, user_id, session_id, jti, "rt-revoke2")
    await store.revoke_session(session_id)
    assert await store.get_session_by_refresh_token("rt-revoke2") is None


async def test_revoke_session_metadata_gone(store):
    user_id, session_id = _make_ids()
    await _create(store, user_id, session_id, str(uuid.uuid4()), "rt-meta")
    await store.revoke_session(session_id)
    assert await store.get_session(session_id) is None


async def test_revoke_session_idempotent(store):
    user_id, session_id = _make_ids()
    await _create(store, user_id, session_id, str(uuid.uuid4()), "rt-idem")
    await store.revoke_session(session_id)
    # second revoke must not raise
    await store.revoke_session(session_id)


# ---------------------------------------------------------------------------
# revoke_all_user_sessions
# ---------------------------------------------------------------------------

async def test_revoke_all_user_sessions(store):
    user_id = uuid.uuid4()
    session_ids = [uuid.uuid4() for _ in range(3)]
    jtis = [str(uuid.uuid4()) for _ in range(3)]
    for sid, jti, rt in zip(session_ids, jtis, ["rt-a", "rt-b", "rt-c"]):
        await _create(store, user_id, sid, jti, rt)

    await store.revoke_all_user_sessions(user_id)

    for sid, jti in zip(session_ids, jtis):
        assert await store.is_access_jti_valid(jti) is False
        assert await store.get_session(sid) is None
    for rt in ["rt-a", "rt-b", "rt-c"]:
        assert await store.get_session_by_refresh_token(rt) is None


async def test_revoke_all_user_sessions_no_sessions_does_not_raise(store):
    await store.revoke_all_user_sessions(uuid.uuid4())
