import os

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# SQLAlchemy's asyncpg dialect needs postgresql+asyncpg://, but Postgres
# hosts (Neon, Render, etc.) hand out plain postgresql:// URLs — rewrite
# it so either form works as DB_URL.
_raw_url = os.environ["DB_URL"]
if _raw_url.startswith("postgresql://"):
    _raw_url = _raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
elif _raw_url.startswith("postgres://"):
    _raw_url = _raw_url.replace("postgres://", "postgresql+asyncpg://", 1)

engine = create_async_engine(_raw_url, pool_pre_ping=True, pool_size=5, max_overflow=5)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session():
    async with SessionLocal() as session:
        yield session
