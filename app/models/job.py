"""작업(Job) 모델 — 리뷰 영상 처리 단위"""
from sqlalchemy import Column, Integer, String, DateTime, Text, Float, func
from database import Base


class Job(Base):
    """리뷰 영상 다운로드·번역·자막 작업"""
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_url = Column(String(500), nullable=False)
    platform = Column(String(50), nullable=False)  # douyin, xiaohongshu, 1688
    status = Column(
        String(50), nullable=False, default="pending"
    )  # pending / downloading / transcribing / translating / rendering / done / error
    error_msg = Column(Text, nullable=True)

    # 원본 정보
    original_title = Column(String(500), nullable=True)
    original_desc = Column(Text, nullable=True)

    # 번역 결과
    translated_title = Column(String(500), nullable=True)
    translated_desc = Column(Text, nullable=True)

    # 파일 경로
    video_path = Column(String(500), nullable=True)
    output_path = Column(String(500), nullable=True)

    # 자막 (SRT 텍스트)
    subtitle_zh = Column(Text, nullable=True)
    subtitle_ko = Column(Text, nullable=True)

    # 메타데이터
    duration_sec = Column(Float, nullable=True)
    thumbnail_url = Column(String(500), nullable=True)

    # 타임스탬프
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
