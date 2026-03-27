"""모든 모델 import — init_db()에서 테이블 생성 보장"""
from app.models.job import Job  # noqa: F401
from app.models.api_key import ApiKey  # noqa: F401
