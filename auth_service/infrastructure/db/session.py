import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_DB_URL = os.environ.get("DB_URL", "postgresql+asyncpg://auth_user:auth_password@localhost:5432/auth")

engine = create_async_engine(_DB_URL, echo=False, pool_pre_ping=True)

async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)
