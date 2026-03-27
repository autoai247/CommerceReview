"""쿠팡 파트너스 API 라우터 — 딥링크 생성 및 상품 검색"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Form, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from app.models.api_key import ApiKey
from app.models.job import Job

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/coupang", tags=["coupang"])


# ──────────────────────────── Helpers ────────────────────────────

async def _get_coupang_credentials(db: AsyncSession) -> tuple[str, str]:
    """DB에서 쿠팡 파트너스 인증 정보(ACCESS_KEY, SECRET_KEY) 조회."""
    result = await db.execute(
        select(ApiKey).where(ApiKey.service == "coupang", ApiKey.is_active == True)  # noqa: E712
    )
    row = result.scalar_one_or_none()
    if not row or not row.api_key:
        raise HTTPException(
            status_code=400,
            detail="쿠팡 파트너스 인증 정보가 설정되지 않았습니다. 설정 페이지에서 등록해주세요.",
        )

    try:
        creds = json.loads(row.api_key)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=400,
            detail="쿠팡 파트너스 인증 정보 JSON 형식이 올바르지 않습니다.",
        )

    access_key = creds.get("access_key", "")
    secret_key = creds.get("secret_key", "")

    if not access_key or not secret_key:
        raise HTTPException(
            status_code=400,
            detail="쿠팡 파트너스 ACCESS KEY 또는 SECRET KEY가 비어있습니다.",
        )

    return access_key, secret_key


# ──────────────────────────── 딥링크 생성 ────────────────────────────

@router.post("/deeplink")
async def create_deeplink(
    product_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """상품번호로 어필리에이트 딥링크 생성."""
    from app.services.coupang import generate_affiliate_link

    access_key, secret_key = await _get_coupang_credentials(db)

    try:
        result = await generate_affiliate_link(product_id, access_key, secret_key)
        return {"ok": True, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ──────────────────────────── 상품 검색 ────────────────────────────

@router.get("/search")
async def search(
    keyword: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """키워드로 쿠팡 상품 검색."""
    from app.services.coupang import search_products

    access_key, secret_key = await _get_coupang_credentials(db)

    try:
        products = await search_products(keyword, access_key, secret_key, limit)
        return {"ok": True, "products": products, "count": len(products)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ──────────────────────────── 작업에 링크 연결 ────────────────────────────

@router.post("/jobs/{job_id}/link")
async def attach_link_to_job(
    job_id: int,
    product_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """작업에 쿠팡 어필리에이트 링크 연결 (영상 설명에 포함용)."""
    from app.services.coupang import generate_affiliate_link

    # 작업 조회
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")

    # 쿠팡 인증 정보 조회
    access_key, secret_key = await _get_coupang_credentials(db)

    # 딥링크 생성
    try:
        link_data = await generate_affiliate_link(product_id, access_key, secret_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    # 작업에 저장
    job.coupang_product_id = product_id
    job.coupang_affiliate_url = link_data.get("short_url") or link_data.get("affiliate_url", "")
    await db.commit()

    return {
        "ok": True,
        "product_id": product_id,
        "affiliate_url": job.coupang_affiliate_url,
        "original_url": link_data.get("original_url", ""),
        "short_url": link_data.get("short_url", ""),
    }


# ──────────────────────────── 연결 테스트 ────────────────────────────

@router.post("/test")
async def test_coupang_connection(
    db: AsyncSession = Depends(get_db),
):
    """쿠팡 파트너스 API 연결 테스트."""
    from app.services.coupang import test_connection

    access_key, secret_key = await _get_coupang_credentials(db)

    result = await test_connection(access_key, secret_key)
    if not result["ok"]:
        return {"ok": False, "detail": result["message"]}

    return {"ok": True, "message": result["message"]}
