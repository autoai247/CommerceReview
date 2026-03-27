"""CommerceReview 설정"""
import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    APP_NAME: str = "CommerceReview"
    VERSION: str = "0.1.0"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/commerce.db"
    DATA_DIR: str = os.getenv("DATA_DIR", "./data")
    WHISPER_MODE: str = os.getenv("WHISPER_MODE", "api")  # api or local

    class Config:
        env_file = ".env"


settings = Settings()

# 프로덕션 환경(Docker/Railway)에서는 반드시 환경변수 설정 필요
_is_production = bool(os.getenv("PORT") or os.getenv("RAILWAY_ENVIRONMENT"))

if _is_production:
    settings.DATA_DIR = os.getenv("DATA_DIR", "/app/data")
    settings.DATABASE_URL = f"sqlite+aiosqlite:///{settings.DATA_DIR}/commerce.db"

if not settings.SECRET_KEY:
    if _is_production:
        raise RuntimeError("SECRET_KEY 환경변수가 설정되지 않았습니다 (프로덕션)")
    settings.SECRET_KEY = "change-me-on-first-login"

if not settings.ADMIN_PASSWORD:
    if _is_production:
        raise RuntimeError("ADMIN_PASSWORD 환경변수가 설정되지 않았습니다 (프로덕션)")
    settings.ADMIN_PASSWORD = "admin"
