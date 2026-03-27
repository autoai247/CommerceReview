"""API 키 모델"""
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, func
from database import Base


class ApiKey(Base):
    """API 키 관리 (OpenAI, Google 등)"""
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    service = Column(String(50), nullable=False)  # openai, youtube, tiktok, instagram
    api_key = Column(Text, nullable=False)  # 암호화된 키
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
