"""YouTube Data API v3 업로드 서비스

OAuth2 refresh token을 사용하여 access token을 갱신하고,
resumable upload으로 영상을 업로드합니다.
"""

import json
import logging
import os
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

# YouTube API 상수
YOUTUBE_API_BASE = "https://www.googleapis.com"
YOUTUBE_UPLOAD_URL = f"{YOUTUBE_API_BASE}/upload/youtube/v3/videos"
YOUTUBE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# 업로드 청크 사이즈 (256KB의 배수여야 함 — Google 권장 5MB)
CHUNK_SIZE = 5 * 1024 * 1024  # 5MB


async def _refresh_access_token(credentials: dict) -> str:
    """OAuth2 refresh token으로 새 access token 발급.

    credentials에 필요한 키:
    - client_id
    - client_secret
    - refresh_token
    """
    required = ("client_id", "client_secret", "refresh_token")
    for key in required:
        if key not in credentials:
            raise ValueError(f"YouTube 인증 정보에 '{key}'가 없습니다.")

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            YOUTUBE_TOKEN_URL,
            data={
                "client_id": credentials["client_id"],
                "client_secret": credentials["client_secret"],
                "refresh_token": credentials["refresh_token"],
                "grant_type": "refresh_token",
            },
        )

    if resp.status_code != 200:
        detail = resp.text[:300]
        raise RuntimeError(f"YouTube 액세스 토큰 갱신 실패 (HTTP {resp.status_code}): {detail}")

    data = resp.json()
    access_token = data.get("access_token")
    if not access_token:
        raise RuntimeError("YouTube 토큰 응답에 access_token이 없습니다.")

    return access_token


async def _init_resumable_upload(
    access_token: str,
    title: str,
    description: str,
    tags: list[str],
    privacy: str,
    file_size: int,
) -> str:
    """Resumable upload 세션을 초기화하고 upload URI를 반환."""
    metadata = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "22",  # People & Blogs
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/mp4",
        "X-Upload-Content-Length": str(file_size),
    }

    params = {
        "uploadType": "resumable",
        "part": "snippet,status",
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            YOUTUBE_UPLOAD_URL,
            headers=headers,
            params=params,
            json=metadata,
        )

    if resp.status_code not in (200, 308):
        detail = resp.text[:500]
        raise RuntimeError(f"YouTube 업로드 세션 초기화 실패 (HTTP {resp.status_code}): {detail}")

    upload_url = resp.headers.get("Location")
    if not upload_url:
        raise RuntimeError("YouTube 응답에 업로드 URL(Location 헤더)이 없습니다.")

    return upload_url


async def _upload_file_chunked(upload_url: str, file_path: str, file_size: int) -> dict:
    """청크 단위로 파일을 업로드하고 최종 응답을 반환."""
    uploaded = 0

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

                if resp.status_code == 200 or resp.status_code == 201:
                    # 업로드 완료
                    return resp.json()
                elif resp.status_code == 308:
                    # 다음 청크 계속
                    uploaded += len(chunk)
                    log.info(f"YouTube 업로드 진행: {uploaded}/{file_size} bytes")
                else:
                    detail = resp.text[:500]
                    raise RuntimeError(
                        f"YouTube 청크 업로드 실패 (HTTP {resp.status_code}): {detail}"
                    )

    raise RuntimeError("YouTube 업로드가 완료되지 않았습니다.")


async def upload_to_youtube(
    video_path: str,
    title: str,
    description: str,
    tags: list[str],
    privacy: str = "private",
    credentials_json: str = "",
) -> dict:
    """YouTube Data API v3로 영상 업로드.

    Args:
        video_path: 업로드할 영상 파일 경로
        title: 영상 제목
        description: 영상 설명
        tags: 태그 목록
        privacy: 공개 설정 (private/public/unlisted)
        credentials_json: OAuth2 인증 정보 JSON 문자열
            필수 키: client_id, client_secret, refresh_token

    Returns:
        {"video_id": str, "url": str}
    """
    # 파일 검증
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"영상 파일을 찾을 수 없습니다: {video_path}")

    file_size = os.path.getsize(video_path)
    if file_size == 0:
        raise ValueError("영상 파일이 비어 있습니다.")

    # 인증 정보 파싱
    if not credentials_json:
        raise ValueError("YouTube OAuth2 인증 정보가 필요합니다. 설정에서 등록해주세요.")

    try:
        credentials = json.loads(credentials_json)
    except json.JSONDecodeError:
        raise ValueError("YouTube 인증 정보 JSON 파싱에 실패했습니다.")

    # privacy 검증
    if privacy not in ("private", "public", "unlisted"):
        privacy = "private"

    log.info(f"YouTube 업로드 시작: {title} ({file_size} bytes)")

    # 1) Access token 갱신
    access_token = await _refresh_access_token(credentials)

    # 2) Resumable upload 세션 초기화
    upload_url = await _init_resumable_upload(
        access_token=access_token,
        title=title,
        description=description,
        tags=tags,
        privacy=privacy,
        file_size=file_size,
    )

    # 3) 청크 업로드
    result = await _upload_file_chunked(upload_url, video_path, file_size)

    video_id = result.get("id", "")
    if not video_id:
        raise RuntimeError("YouTube 업로드 응답에 video ID가 없습니다.")

    url = f"https://youtu.be/{video_id}"
    log.info(f"YouTube 업로드 완료: {url}")

    return {"video_id": video_id, "url": url}
