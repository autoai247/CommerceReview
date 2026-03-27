"""설정 API 라우터 — API 키 관리"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from app.models.api_key import ApiKey

router = APIRouter(prefix="/api/settings", tags=["settings"])


class ApiKeyPayload(BaseModel):
    openai_api_key: str


class PlatformKeyPayload(BaseModel):
    service: str  # youtube, tiktok, instagram
    api_key: str


@router.post("")
async def save_settings(data: ApiKeyPayload, db: AsyncSession = Depends(get_db)):
    """OpenAI API 키 저장."""
    key_value = data.openai_api_key.strip()
    if not key_value:
        raise HTTPException(status_code=400, detail="API 키를 입력해주세요.")

    # 기존 키가 있으면 업데이트, 없으면 생성
    result = await db.execute(select(ApiKey).where(ApiKey.service == "openai"))
    existing = result.scalar_one_or_none()

    if existing:
        existing.api_key = key_value
        existing.is_active = True
    else:
        new_key = ApiKey(service="openai", api_key=key_value, is_active=True)
        db.add(new_key)

    await db.commit()
    return {"ok": True}


@router.get("")
async def get_settings(db: AsyncSession = Depends(get_db)):
    """저장된 API 키 조회 (마스킹)."""
    result = await db.execute(
        select(ApiKey).where(ApiKey.service == "openai", ApiKey.is_active == True)
    )
    row = result.scalar_one_or_none()

    openai_key_masked = ""
    if row and row.api_key:
        raw = row.api_key
        if len(raw) > 10:
            openai_key_masked = raw[:7] + "..." + raw[-4:]
        else:
            openai_key_masked = "****"

    return {"openai_api_key": openai_key_masked}


@router.post("/platform")
async def save_platform_key(data: PlatformKeyPayload, db: AsyncSession = Depends(get_db)):
    """플랫폼별 인증 정보 저장 (YouTube, TikTok, Instagram)."""
    service = data.service.strip().lower()
    key_value = data.api_key.strip()

    if service not in ("youtube", "tiktok", "instagram", "coupang"):
        raise HTTPException(status_code=400, detail="지원하지 않는 서비스입니다. (youtube, tiktok, instagram, coupang)")

    if not key_value:
        raise HTTPException(status_code=400, detail="인증 정보를 입력해주세요.")

    # 기존 키가 있으면 업데이트, 없으면 생성
    result = await db.execute(select(ApiKey).where(ApiKey.service == service))
    existing = result.scalar_one_or_none()

    if existing:
        existing.api_key = key_value
        existing.is_active = True
    else:
        new_key = ApiKey(service=service, api_key=key_value, is_active=True)
        db.add(new_key)

    await db.commit()
    return {"ok": True}


@router.post("/test")
async def test_connection(data: ApiKeyPayload):
    """OpenAI API 연결 테스트."""
    key_value = data.openai_api_key.strip()

    # 마스킹된 키가 들어오면 DB에서 실제 키 조회
    if "..." in key_value or key_value == "****":
        raise HTTPException(
            status_code=400,
            detail="실제 API 키를 입력해주세요. 마스킹된 키로는 테스트할 수 없습니다.",
        )

    if not key_value.startswith("sk-"):
        raise HTTPException(status_code=400, detail="올바른 OpenAI API 키 형식이 아닙니다. (sk-로 시작)")

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=key_value)
        # 간단한 모델 목록 조회로 연결 테스트
        models = await client.models.list()
        model_ids = [m.id for m in models.data[:5]]

        return {
            "ok": True,
            "message": f"연결 성공! 사용 가능 모델: {', '.join(model_ids)}...",
        }

    except Exception as e:
        error_msg = str(e)
        if "authentication" in error_msg.lower() or "api key" in error_msg.lower():
            return {"ok": False, "detail": "API 키가 유효하지 않습니다."}
        return {"ok": False, "detail": f"연결 실패: {error_msg[:200]}"}
