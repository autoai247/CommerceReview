"""업로드 API 라우터 — YouTube / TikTok / Instagram 업로드"""

import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, async_session
from app.models.job import Job
from app.models.api_key import ApiKey

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/upload", tags=["upload"])


# ──────────────────────────── Schemas ────────────────────────────

class UploadRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    privacy: Optional[str] = "private"  # YouTube 전용


# ──────────────────────────── Helpers ────────────────────────────

async def _get_job_or_404(job_id: int, db: AsyncSession) -> Job:
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
    return job


async def _get_api_key(db: AsyncSession, service: str) -> Optional[str]:
    """DB에서 해당 서비스의 활성 API 키/인증 정보 조회."""
    result = await db.execute(
        select(ApiKey).where(ApiKey.service == service, ApiKey.is_active == True)  # noqa: E712
    )
    row = result.scalar_one_or_none()
    return row.api_key if row else None


def _build_title(job: Job) -> str:
    """작업 정보로 기본 제목 생성."""
    return job.translated_title or job.original_title or f"CommerceReview #{job.id}"


def _build_description(job: Job) -> str:
    """작업 정보로 기본 설명 생성."""
    parts = []
    if job.translated_desc:
        parts.append(job.translated_desc)
    elif job.original_desc:
        parts.append(job.original_desc)
    parts.append("\n#CommerceReview #커머스리뷰")
    return "\n\n".join(parts)


# ──────────────────────────── Background Tasks ────────────────────────────

async def _bg_upload_youtube(job_id: int, title: str, description: str, tags: list[str], privacy: str):
    """백그라운드: YouTube 업로드."""
    from app.services.upload.youtube import upload_to_youtube

    async with async_session() as db:
        result = await db.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            return

        try:
            job.upload_youtube = "uploading"
            await db.commit()

            credentials_json = await _get_api_key(db, "youtube")
            if not credentials_json:
                raise ValueError("YouTube 인증 정보가 설정되지 않았습니다. 설정 페이지에서 등록해주세요.")

            result_data = await upload_to_youtube(
                video_path=job.output_path,
                title=title,
                description=description,
                tags=tags,
                privacy=privacy,
                credentials_json=credentials_json,
            )

            job.upload_youtube = "done"
            job.youtube_url = result_data.get("url", "")
            await db.commit()

        except Exception as e:
            log.error(f"YouTube 업로드 실패 (job {job_id}): {e}")
            job.upload_youtube = "error"
            job.error_msg = f"YouTube 업로드 실패: {str(e)[:500]}"
            await db.commit()


async def _bg_upload_tiktok(job_id: int, title: str):
    """백그라운드: TikTok 업로드."""
    from app.services.upload.tiktok import upload_to_tiktok

    async with async_session() as db:
        result = await db.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            return

        try:
            job.upload_tiktok = "uploading"
            await db.commit()

            access_token = await _get_api_key(db, "tiktok")
            if not access_token:
                raise ValueError("TikTok access token이 설정되지 않았습니다. 설정 페이지에서 등록해주세요.")

            result_data = await upload_to_tiktok(
                video_path=job.output_path,
                title=title,
                access_token=access_token,
            )

            job.upload_tiktok = "done"
            job.tiktok_url = result_data.get("publish_id", "")
            await db.commit()

        except Exception as e:
            log.error(f"TikTok 업로드 실패 (job {job_id}): {e}")
            job.upload_tiktok = "error"
            job.error_msg = f"TikTok 업로드 실패: {str(e)[:500]}"
            await db.commit()


async def _bg_upload_instagram(job_id: int, caption: str, request_base_url: str):
    """백그라운드: Instagram 업로드."""
    from app.services.upload.instagram import upload_to_instagram

    async with async_session() as db:
        result = await db.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            return

        try:
            job.upload_instagram = "uploading"
            await db.commit()

            creds_json = await _get_api_key(db, "instagram")
            if not creds_json:
                raise ValueError("Instagram 인증 정보가 설정되지 않았습니다. 설정 페이지에서 등록해주세요.")

            # Instagram 인증 정보 파싱 (JSON: access_token + ig_user_id)
            try:
                creds = json.loads(creds_json)
            except json.JSONDecodeError:
                raise ValueError("Instagram 인증 정보 JSON 형식이 올바르지 않습니다.")

            access_token = creds.get("access_token", "")
            ig_user_id = creds.get("ig_user_id", "")

            if not access_token or not ig_user_id:
                raise ValueError("Instagram access_token 및 ig_user_id가 모두 필요합니다.")

            # 서버 URL로 영상 제공 (Instagram은 공개 URL 필요)
            video_public_url = f"{request_base_url}/api/jobs/{job_id}/download"

            result_data = await upload_to_instagram(
                video_path=job.output_path,
                caption=caption,
                access_token=access_token,
                ig_user_id=ig_user_id,
                video_public_url=video_public_url,
            )

            job.upload_instagram = "done"
            job.instagram_url = result_data.get("url", "")
            await db.commit()

        except Exception as e:
            log.error(f"Instagram 업로드 실패 (job {job_id}): {e}")
            job.upload_instagram = "error"
            job.error_msg = f"Instagram 업로드 실패: {str(e)[:500]}"
            await db.commit()


# ──────────────────────────── Endpoints ────────────────────────────

@router.post("/{job_id}/youtube")
async def upload_youtube_endpoint(
    job_id: int,
    background_tasks: BackgroundTasks,
    body: UploadRequest = UploadRequest(),
    db: AsyncSession = Depends(get_db),
):
    """YouTube에 완성 영상 업로드."""
    job = await _get_job_or_404(job_id, db)

    if not job.output_path or not os.path.isfile(job.output_path):
        raise HTTPException(status_code=400, detail="완성 영상이 없습니다. 먼저 렌더링을 완료해주세요.")

    if job.upload_youtube == "uploading":
        raise HTTPException(status_code=409, detail="이미 YouTube 업로드가 진행 중입니다.")

    title = body.title or _build_title(job)
    description = body.description or _build_description(job)
    tags = body.tags or ["커머스리뷰", "상품리뷰"]
    privacy = body.privacy or "private"

    background_tasks.add_task(_bg_upload_youtube, job_id, title, description, tags, privacy)

    return {"ok": True, "message": "YouTube 업로드가 시작되었습니다."}


@router.post("/{job_id}/tiktok")
async def upload_tiktok_endpoint(
    job_id: int,
    background_tasks: BackgroundTasks,
    body: UploadRequest = UploadRequest(),
    db: AsyncSession = Depends(get_db),
):
    """TikTok에 완성 영상 업로드."""
    job = await _get_job_or_404(job_id, db)

    if not job.output_path or not os.path.isfile(job.output_path):
        raise HTTPException(status_code=400, detail="완성 영상이 없습니다. 먼저 렌더링을 완료해주세요.")

    if job.upload_tiktok == "uploading":
        raise HTTPException(status_code=409, detail="이미 TikTok 업로드가 진행 중입니다.")

    title = body.title or _build_title(job)

    background_tasks.add_task(_bg_upload_tiktok, job_id, title)

    return {"ok": True, "message": "TikTok 업로드가 시작되었습니다."}


@router.post("/{job_id}/instagram")
async def upload_instagram_endpoint(
    job_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    body: UploadRequest = UploadRequest(),
    db: AsyncSession = Depends(get_db),
):
    """Instagram에 완성 영상 (릴스) 업로드."""
    job = await _get_job_or_404(job_id, db)

    if not job.output_path or not os.path.isfile(job.output_path):
        raise HTTPException(status_code=400, detail="완성 영상이 없습니다. 먼저 렌더링을 완료해주세요.")

    if job.upload_instagram == "uploading":
        raise HTTPException(status_code=409, detail="이미 Instagram 업로드가 진행 중입니다.")

    caption = body.title or _build_title(job)
    if body.description:
        caption += f"\n\n{body.description}"

    # 서버 base URL (Instagram이 영상을 가져올 수 있는 공개 URL)
    base_url = str(request.base_url).rstrip("/")

    background_tasks.add_task(_bg_upload_instagram, job_id, caption, base_url)

    return {"ok": True, "message": "Instagram 업로드가 시작되었습니다."}


@router.post("/{job_id}/all")
async def upload_all_endpoint(
    job_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    body: UploadRequest = UploadRequest(),
    db: AsyncSession = Depends(get_db),
):
    """3개 플랫폼(YouTube, TikTok, Instagram)에 동시 업로드."""
    job = await _get_job_or_404(job_id, db)

    if not job.output_path or not os.path.isfile(job.output_path):
        raise HTTPException(status_code=400, detail="완성 영상이 없습니다. 먼저 렌더링을 완료해주세요.")

    title = body.title or _build_title(job)
    description = body.description or _build_description(job)
    tags = body.tags or ["커머스리뷰", "상품리뷰"]
    privacy = body.privacy or "private"
    base_url = str(request.base_url).rstrip("/")

    caption = title
    if description:
        caption += f"\n\n{description}"

    # 진행 중이 아닌 플랫폼만 업로드
    started = []

    if job.upload_youtube != "uploading":
        background_tasks.add_task(_bg_upload_youtube, job_id, title, description, tags, privacy)
        started.append("YouTube")

    if job.upload_tiktok != "uploading":
        background_tasks.add_task(_bg_upload_tiktok, job_id, title)
        started.append("TikTok")

    if job.upload_instagram != "uploading":
        background_tasks.add_task(_bg_upload_instagram, job_id, caption, base_url)
        started.append("Instagram")

    if not started:
        raise HTTPException(status_code=409, detail="모든 플랫폼에서 이미 업로드가 진행 중입니다.")

    return {
        "ok": True,
        "message": f"{', '.join(started)} 업로드가 시작되었습니다.",
    }


@router.get("/{job_id}/status")
async def upload_status(job_id: int, db: AsyncSession = Depends(get_db)):
    """업로드 상태 조회."""
    job = await _get_job_or_404(job_id, db)
    return {
        "youtube": {"status": job.upload_youtube or "none", "url": job.youtube_url},
        "tiktok": {"status": job.upload_tiktok or "none", "url": job.tiktok_url},
        "instagram": {"status": job.upload_instagram or "none", "url": job.instagram_url},
    }
