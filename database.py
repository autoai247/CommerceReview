"""데이터베이스 설정"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    import app.models  # noqa: F401 — 모든 모델 import하여 테이블 생성 보장
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 기존 테이블에 새 컬럼 자동 추가 (마이그레이션)
    await _auto_migrate()


async def _auto_migrate():
    """기존 DB에 누락된 컬럼 자동 추가"""
    import logging
    log = logging.getLogger(__name__)

    migrations = [
        # (테이블, 컬럼, 타입)
        ("jobs", "thumbnail_url", "VARCHAR(500)"),
        ("jobs", "duration_sec", "FLOAT"),
        ("jobs", "upload_youtube", "VARCHAR(50) DEFAULT 'none'"),
        ("jobs", "upload_tiktok", "VARCHAR(50) DEFAULT 'none'"),
        ("jobs", "upload_instagram", "VARCHAR(50) DEFAULT 'none'"),
        ("jobs", "youtube_url", "VARCHAR(500)"),
        ("jobs", "tiktok_url", "VARCHAR(500)"),
        ("jobs", "instagram_url", "VARCHAR(500)"),
    ]

    async with engine.begin() as conn:
        for table, column, col_type in migrations:
            try:
                await conn.execute(
                    __import__('sqlalchemy').text(
                        f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
                    )
                )
                log.info(f"마이그레이션: {table}.{column} 추가됨")
            except Exception:
                pass  # 이미 존재하면 무시


async def get_db():
    async with async_session() as session:
        yield session
