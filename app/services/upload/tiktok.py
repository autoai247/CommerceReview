"""TikTok Content Posting API v2 업로드 서비스

TikTok API 플로우:
1. POST /v2/post/publish/inbox/video/init/ — 업로드 URL 획득
2. PUT upload URL — 영상 파일 업로드
3. POST /v2/post/publish/ — 게시
"""

import logging
import os

import httpx

log = logging.getLogger(__name__)

TIKTOK_API_BASE = "https://open.tiktokapis.com"

# 청크 사이즈 (TikTok 권장: 10MB 이하)
CHUNK_SIZE = 10 * 1024 * 1024  # 10MB


async def _init_video_upload(access_token: str, file_size: int) -> dict:
    """TikTok에 영상 업로드 세션 초기화.

    Returns:
        {"upload_url": str, "publish_id": str}
    """
    url = f"{TIKTOK_API_BASE}/v2/post/publish/inbox/video/init/"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }

    body = {
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": file_size,
            "chunk_size": min(CHUNK_SIZE, file_size),
            "total_chunk_count": max(1, -(-file_size // CHUNK_SIZE)),  # ceil division
        },
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, headers=headers, json=body)

    if resp.status_code != 200:
        detail = resp.text[:500]
        raise RuntimeError(f"TikTok 업로드 초기화 실패 (HTTP {resp.status_code}): {detail}")

    data = resp.json()

    if data.get("error", {}).get("code") != "ok":
        error_msg = data.get("error", {}).get("message", "알 수 없는 오류")
        raise RuntimeError(f"TikTok 업로드 초기화 실패: {error_msg}")

    upload_url = data.get("data", {}).get("upload_url", "")
    publish_id = data.get("data", {}).get("publish_id", "")

    if not upload_url:
        raise RuntimeError("TikTok 응답에 upload_url이 없습니다.")

    return {"upload_url": upload_url, "publish_id": publish_id}


async def _upload_video_chunks(upload_url: str, file_path: str, file_size: int) -> None:
    """영상 파일을 청크 단위로 TikTok에 업로드."""
    uploaded = 0
    chunk_index = 0

    async with httpx.AsyncClient(timeout=300) as client:
        with open(file_path, "rb") as f:
            while uploaded < file_size:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break

                chunk_end = uploaded + len(chunk) - 1
                headers = {
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {uploaded}-{chunk_end}/{file_size}",
                }

                resp = await client.put(
                    upload_url,
                    headers=headers,
                    content=chunk,
                )

                if resp.status_code not in (200, 201, 206):
                    detail = resp.text[:500]
                    raise RuntimeError(
                        f"TikTok 청크 업로드 실패 (청크 {chunk_index}, HTTP {resp.status_code}): {detail}"
                    )

                uploaded += len(chunk)
                chunk_index += 1
                log.info(f"TikTok 업로드 진행: {uploaded}/{file_size} bytes (청크 {chunk_index})")


async def _publish_video(access_token: str, publish_id: str, title: str) -> dict:
    """업로드된 영상을 TikTok에 게시."""
    url = f"{TIKTOK_API_BASE}/v2/post/publish/"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }

    body = {
        "post_info": {
            "title": title[:150],  # TikTok 제목 길이 제한
            "privacy_level": "SELF_ONLY",  # 초안(비공개)으로 업로드
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_publish_id": publish_id,
        },
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, headers=headers, json=body)

    if resp.status_code != 200:
        detail = resp.text[:500]
        raise RuntimeError(f"TikTok 게시 실패 (HTTP {resp.status_code}): {detail}")

    data = resp.json()
    if data.get("error", {}).get("code") != "ok":
        error_msg = data.get("error", {}).get("message", "알 수 없는 오류")
        raise RuntimeError(f"TikTok 게시 실패: {error_msg}")

    return data.get("data", {})


async def upload_to_tiktok(
    video_path: str,
    title: str,
    access_token: str = "",
) -> dict:
    """TikTok Content Posting API로 영상 업로드.

    Args:
        video_path: 업로드할 영상 파일 경로
        title: 영상 제목/캡션
        access_token: TikTok API access token

    Returns:
        {"publish_id": str}
    """
    # 파일 검증
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"영상 파일을 찾을 수 없습니다: {video_path}")

    file_size = os.path.getsize(video_path)
    if file_size == 0:
        raise ValueError("영상 파일이 비어 있습니다.")

    if not access_token:
        raise ValueError("TikTok access token이 필요합니다. 설정에서 등록해주세요.")

    log.info(f"TikTok 업로드 시작: {title} ({file_size} bytes)")

    # 1) 업로드 세션 초기화
    init_result = await _init_video_upload(access_token, file_size)
    upload_url = init_result["upload_url"]
    publish_id = init_result["publish_id"]

    # 2) 영상 파일 업로드
    await _upload_video_chunks(upload_url, video_path, file_size)

    # 3) 게시
    await _publish_video(access_token, publish_id, title)

    log.info(f"TikTok 업로드 완료: publish_id={publish_id}")

    return {"publish_id": publish_id}
