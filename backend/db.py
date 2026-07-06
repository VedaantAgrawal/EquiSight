import os
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# SQLAlchemy's asyncpg dialect needs postgresql+asyncpg://, but Postgres
# hosts (Neon, Render, etc.) hand out plain postgresql:// URLs — rewrite
# it so either form works as DB_URL.
_raw_url = os.environ["DB_URL"]
if _raw_url.startswith("postgresql://"):
    _raw_url = _raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
elif _raw_url.startswith("postgres://"):
    _raw_url = _raw_url.replace("postgres://", "postgresql+asyncpg://", 1)

# libpq/psycopg-style query params (sslmode, channel_binding — what Neon's
# connection string ships by default) aren't understood by asyncpg's
# connect(), which raises a hard TypeError on them. Strip them from the
# URL and pass the SSL requirement through SQLAlchemy's own connect_args
# instead, in the form asyncpg actually expects.
_parsed = urlparse(_raw_url)
_query = parse_qs(_parsed.query)
_query.pop("sslmode", None)
_query.pop("channel_binding", None)
_raw_url = urlunparse(_parsed._replace(query=urlencode(_query, doseq=True)))

engine = create_async_engine(
    _raw_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    connect_args={"ssl": "require"},
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session():
    async with SessionLocal() as session:
        yield session
