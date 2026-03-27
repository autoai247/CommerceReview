"""페이지 라우터 — Jinja2 HTML 페이지 렌더링"""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.routers.auth import require_auth, COOKIE_NAME
from database import get_db
from app.models.job import Job

router = APIRouter()

templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    """메인 대시보드 — 작업 목록."""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=302)

    result = await db.execute(select(Job).order_by(Job.created_at.desc()))
    jobs_orm = result.scalars().all()

    # 템플릿에서 쓸 dict 리스트로 변환
    jobs = []
    for j in jobs_orm:
        jobs.append({
            "id": j.id,
            "title": j.original_title or j.translated_title or j.source_url or "",
            "source_url": j.source_url,
            "platform": j.platform,
            "status": j.status,
            "thumbnail_url": j.thumbnail_url,
            "created_at": j.created_at.isoformat() if j.created_at else "",
        })

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "jobs": jobs,
    })


@router.get("/new", response_class=HTMLResponse)
async def new_job_page(request: Request):
    """새 작업 생성 페이지."""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse("new_job.html", {"request": request})


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: int, db: AsyncSession = Depends(get_db)):
    """작업 상세 페이지."""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=302)

    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        return RedirectResponse(url="/", status_code=302)

    job_dict = {
        "id": job.id,
        "title": job.original_title or job.translated_title or job.source_url or "",
        "source_url": job.source_url,
        "platform": job.platform,
        "status": job.status,
        "error_message": job.error_msg,
        "video_path": job.video_path,
        "output_path": job.output_path,
        "subtitle_zh": job.subtitle_zh or "",
        "subtitle_ko": job.subtitle_ko or "",
        "thumbnail_url": job.thumbnail_url,
        "duration_sec": job.duration_sec,
        "created_at": job.created_at.isoformat() if job.created_at else "",
    }

    return templates.TemplateResponse("job_detail.html", {
        "request": request,
        "job": job_dict,
    })


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: AsyncSession = Depends(get_db)):
    """API 키 설정 페이지."""
    if not require_auth(request):
        return RedirectResponse(url="/login", status_code=302)

    from app.models.api_key import ApiKey

    # 저장된 OpenAI 키 조회 (마스킹)
    openai_key = ""
    result = await db.execute(
        select(ApiKey).where(ApiKey.service == "openai", ApiKey.is_active == True)
    )
    key_row = result.scalar_one_or_none()
    if key_row and key_row.api_key:
        raw = key_row.api_key
        if len(raw) > 10:
            openai_key = raw[:7] + "..." + raw[-4:]
        else:
            openai_key = "****"

    return templates.TemplateResponse("settings.html", {
        "request": request,
        "openai_key": openai_key,
    })
