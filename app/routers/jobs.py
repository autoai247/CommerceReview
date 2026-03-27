"""작업(Job) API 라우터 — 영상 처리 파이프라인 관리"""

import os
import tempfile
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db, async_session
from app.models.job import Job
from app.models.api_key import ApiKey
from app.services.extractor.url_parser import detect_platform

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


# ──────────────────────────── Schemas ────────────────────────────

class SubtitleUpdate(BaseModel):
    subtitle_zh: Optional[str] = None
    subtitle_ko: Optional[str] = None


# ──────────────────────────── Helpers ────────────────────────────

async def _get_openai_key(db: AsyncSession) -> str:
    """DB에서 활성 OpenAI API 키 조회."""
    result = await db.execute(
        select(ApiKey).where(ApiKey.service == "openai", ApiKey.is_active == True)
    )
    row = result.scalar_one_or_none()
    if row and row.api_key:
        return row.api_key

    # 환경변수 fallback
    if settings.OPENAI_API_KEY:
        return settings.OPENAI_API_KEY

    raise HTTPException(status_code=400, detail="OpenAI API 키가 설정되지 않았습니다. 설정 페이지에서 등록하세요.")


async def _get_job_or_404(job_id: int, db: AsyncSession) -> Job:
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    return job


# ──────────────────────────── Pipeline ────────────────────────────

async def _run_pipeline(job_id: int):
    """백그라운드 파이프라인:
    download → STT(중국어) → 번역 → 대본 재작성 → TTS(한국어) → 영상 합성
    """
    import logging
    log = logging.getLogger(__name__)

    from app.services.extractor.douyin import download_douyin
    from app.services.video.whisper_stt import transcribe
    from app.services.translator.gpt_translator import translate_srt
    from app.services.translator.script_rewriter import rewrite_script
    from app.services.video.tts import generate_tts, extract_text_from_srt
    from app.services.video.renderer import burn_subtitles

    async with async_session() as db:
        result = await db.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            return

        # API 키
        api_key = ""
        key_result = await db.execute(
            select(ApiKey).where(ApiKey.service == "openai", ApiKey.is_active == True)
        )
        key_row = key_result.scalar_one_or_none()
        if key_row:
            api_key = key_row.api_key
        elif settings.OPENAI_API_KEY:
            api_key = settings.OPENAI_API_KEY

        job_dir = os.path.join(settings.DATA_DIR, "jobs", str(job_id))
        os.makedirs(job_dir, exist_ok=True)

        try:
            # ── Step 1: 영상 다운로드 ──
            job.status = "downloading"
            await db.commit()
            log.info(f"[Job {job_id}] Step 1: 다운로드")

            if job.platform == "douyin":
                dl_result = await download_douyin(job.source_url, job_dir)
            else:
                dl_result = await _download_ytdlp(job.source_url, job_dir)

            job.video_path = dl_result["video_path"]
            job.original_title = dl_result.get("title", "")
            job.original_desc = dl_result.get("description", "")
            job.duration_sec = dl_result.get("duration", 0)
            await db.commit()

            # ── Step 2: 중국어 음성 → 자막 (STT) ──
            if not api_key:
                raise RuntimeError("OpenAI API 키가 설정되지 않았습니다.")

            job.status = "transcribing"
            await db.commit()
            log.info(f"[Job {job_id}] Step 2: STT (중국어)")

            srt_zh = await transcribe(job.video_path, api_key)
            job.subtitle_zh = srt_zh
            await db.commit()

            # ── Step 3: 번역 (중→한 직역) ──
            job.status = "translating"
            await db.commit()
            log.info(f"[Job {job_id}] Step 3: 번역")

            srt_ko_raw = await translate_srt(srt_zh, api_key)
            await db.commit()

            # ── Step 4: 대본 재작성 (한국 시청자용) ──
            log.info(f"[Job {job_id}] Step 4: 대본 재작성")

            srt_ko = await rewrite_script(
                translated_srt=srt_ko_raw,
                api_key=api_key,
                product_name=job.original_title or "",
                coupang_link=job.coupang_affiliate_url or "",
            )
            job.subtitle_ko = srt_ko
            await db.commit()

            # ── Step 5: 한국어 TTS 음성 생성 ──
            job.status = "rendering"
            await db.commit()
            log.info(f"[Job {job_id}] Step 5: TTS + 렌더링")

            narration_text = extract_text_from_srt(srt_ko)
            tts_result = await generate_tts(
                text=narration_text,
                output_dir=job_dir,
                voice="sunhi",
            )
            tts_audio = tts_result["audio_path"]

            # ── Step 6: 최종 영상 합성 ──
            # 원본 영상(음소거) + 한국어 TTS 음성 + 한국어 자막
            srt_path = os.path.join(job_dir, "subtitle_ko.srt")
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(srt_ko)

            output_path = os.path.join(job_dir, "output.mp4")
            await _render_final(job.video_path, tts_audio, srt_path, output_path)

            job.output_path = output_path
            job.status = "done"
            await db.commit()
            log.info(f"[Job {job_id}] 완료: {output_path}")

        except Exception as e:
            log.error(f"[Job {job_id}] 파이프라인 실패: {e}", exc_info=True)
            job.status = "error"
            job.error_msg = str(e)[:1000]
            await db.commit()


async def _render_final(video_path: str, audio_path: str, srt_path: str, output_path: str):
    """원본 영상(음소거) + 한국어 TTS 음성 + 한국어 자막 = 최종 영상"""
    import asyncio

    # FFmpeg: 원본 비디오 + 새 오디오 + 자막 하드코딩
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,       # 원본 영상
        "-i", audio_path,       # 한국어 TTS 음성
        "-map", "0:v",          # 영상은 원본에서
        "-map", "1:a",          # 오디오는 TTS에서
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-vf", f"subtitles={srt_path}:force_style='FontName=Noto Sans CJK KR,FontSize=22,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,Outline=2,Bold=1,Alignment=2,MarginV=30'",
        "-shortest",            # 짧은 쪽에 맞춤
        "-movflags", "+faststart",
        output_path,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"최종 렌더링 실패: {stderr.decode(errors='replace')[-500:]}")

    if not os.path.exists(output_path) or os.path.getsize(output_path) < 10000:
        raise RuntimeError("최종 영상 파일이 생성되지 않았습니다.")


async def _download_ytdlp(url: str, output_dir: str) -> dict:
    """yt-dlp를 사용한 범용 다운로드 (샤오홍슈, 1688 등)."""
    import asyncio
    import json

    output_template = os.path.join(output_dir, "%(id)s.%(ext)s")
    info_file = os.path.join(output_dir, "info.json")

    cmd = [
        "yt-dlp",
        "--no-check-certificates",
        "--write-info-json",
        "-o", output_template,
        "--print-json",
        url,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp 다운로드 실패: {stderr.decode(errors='replace')[:500]}")

    # stdout에서 JSON 파싱
    try:
        info = json.loads(stdout.decode())
    except json.JSONDecodeError:
        info = {}

    # 다운로드된 파일 찾기
    video_path = ""
    for f in os.listdir(output_dir):
        if f.endswith((".mp4", ".webm", ".mkv", ".flv")):
            video_path = os.path.join(output_dir, f)
            break

    if not video_path:
        raise RuntimeError("다운로드된 영상 파일을 찾을 수 없습니다.")

    return {
        "video_path": video_path,
        "title": info.get("title", ""),
        "description": info.get("description", ""),
        "duration": info.get("duration", 0),
    }


async def _run_rerender(job_id: int):
    """수정된 자막으로 재렌더링."""
    from app.services.video.renderer import burn_subtitles

    async with async_session() as db:
        result = await db.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job or not job.video_path or not job.subtitle_ko:
            return

        job_dir = os.path.dirname(job.video_path)

        try:
            job.status = "rendering"
            await db.commit()

            srt_path = os.path.join(job_dir, "subtitle_ko.srt")
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(job.subtitle_ko)

            output_path = os.path.join(job_dir, "output.mp4")
            # 기존 출력 파일이 있으면 삭제
            if os.path.exists(output_path):
                os.remove(output_path)

            await burn_subtitles(job.video_path, srt_path, output_path)

            job.output_path = output_path
            job.status = "done"
            job.error_msg = None
            await db.commit()

        except Exception as e:
            job.status = "error"
            job.error_msg = str(e)[:1000]
            await db.commit()


# ──────────────────────────── Endpoints ────────────────────────────

@router.post("")
async def create_job(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    url: str = Form(default=""),
    file: Optional[UploadFile] = File(default=None),
):
    """새 작업 생성 (URL 또는 파일 업로드)."""
    url = url.strip()

    if not url and (not file or not file.filename):
        raise HTTPException(status_code=400, detail="URL을 입력하거나 파일을 업로드하세요.")

    platform = ""
    source_url = url

    if url:
        platform = detect_platform(url) or "unknown"
    else:
        platform = "upload"
        source_url = file.filename

    # 작업 생성
    job = Job(source_url=source_url, platform=platform, status="pending")
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # 파일 업로드 처리
    if file and file.filename:
        job_dir = os.path.join(settings.DATA_DIR, "jobs", str(job.id))
        os.makedirs(job_dir, exist_ok=True)
        file_path = os.path.join(job_dir, file.filename)
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
        job.video_path = file_path
        job.status = "pending"
        await db.commit()

    # 백그라운드 파이프라인 시작
    background_tasks.add_task(_run_pipeline, job.id)

    return {"id": job.id, "status": job.status}


@router.get("/{job_id}/status")
async def job_status(job_id: int, db: AsyncSession = Depends(get_db)):
    """작업 상태 조회 (폴링용)."""
    job = await _get_job_or_404(job_id, db)
    return {
        "id": job.id,
        "status": job.status,
        "error_message": job.error_msg,
    }


@router.put("/{job_id}/subtitle")
async def update_subtitle(
    job_id: int,
    data: SubtitleUpdate,
    db: AsyncSession = Depends(get_db),
):
    """자막 수정 저장."""
    job = await _get_job_or_404(job_id, db)

    if data.subtitle_zh is not None:
        job.subtitle_zh = data.subtitle_zh
    if data.subtitle_ko is not None:
        job.subtitle_ko = data.subtitle_ko

    await db.commit()
    return {"ok": True}


@router.post("/{job_id}/rerender")
async def rerender_job(
    job_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """수정된 자막으로 재렌더링."""
    job = await _get_job_or_404(job_id, db)

    if not job.video_path:
        raise HTTPException(status_code=400, detail="원본 영상이 없습니다.")
    if not job.subtitle_ko:
        raise HTTPException(status_code=400, detail="한국어 자막이 없습니다.")

    background_tasks.add_task(_run_rerender, job.id)
    return {"ok": True, "status": "rendering"}


@router.get("/{job_id}/download")
async def download_output(job_id: int, db: AsyncSession = Depends(get_db)):
    """완성 영상 다운로드."""
    job = await _get_job_or_404(job_id, db)

    if not job.output_path or not os.path.isfile(job.output_path):
        raise HTTPException(status_code=404, detail="완성 영상이 아직 없습니다.")

    filename = f"commerce_review_{job_id}.mp4"
    return FileResponse(
        path=job.output_path,
        filename=filename,
        media_type="video/mp4",
    )


@router.get("/{job_id}/video")
async def serve_video(job_id: int, db: AsyncSession = Depends(get_db)):
    """원본 영상 서빙 (video 태그용)."""
    job = await _get_job_or_404(job_id, db)

    if not job.video_path or not os.path.isfile(job.video_path):
        raise HTTPException(status_code=404, detail="영상 파일이 없습니다.")

    return FileResponse(
        path=job.video_path,
        media_type="video/mp4",
    )


@router.get("")
async def list_jobs(db: AsyncSession = Depends(get_db)):
    """모든 작업 목록 조회 (API)."""
    result = await db.execute(select(Job).order_by(Job.created_at.desc()))
    jobs = result.scalars().all()
    return [
        {
            "id": j.id,
            "source_url": j.source_url,
            "platform": j.platform,
            "status": j.status,
            "original_title": j.original_title,
            "translated_title": j.translated_title,
            "created_at": j.created_at.isoformat() if j.created_at else None,
        }
        for j in jobs
    ]


@router.delete("/{job_id}")
async def delete_job(job_id: int, db: AsyncSession = Depends(get_db)):
    """작업 삭제."""
    job = await _get_job_or_404(job_id, db)
    await db.delete(job)
    await db.commit()
    return {"ok": True}
