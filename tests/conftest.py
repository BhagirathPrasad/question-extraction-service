import pytest
import pytest_asyncio
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool

from app.config import settings
from app.main import app as fastapi_app
from app.database import Base, get_db
import app.models

# Isolated engine with NullPool so asyncpg doesn't reuse connections across event loops
test_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
TestSessionLocal = async_sessionmaker(bind=test_engine, expire_on_commit=False, class_=AsyncSession)

async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

fastapi_app.dependency_overrides[get_db] = override_get_db

@pytest_asyncio.fixture(autouse=True)
async def cleanup_tables():
    """Clean all tables before each test to ensure test isolation."""
    async with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
    yield

@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://test"
    ) as ac:
        yield ac
