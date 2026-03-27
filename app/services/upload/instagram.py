"""Instagram Graph API 릴스 업로드 서비스

Instagram Graph API 플로우:
1. POST /{ig-user-id}/media — 미디어 컨테이너 생성 (REELS)
2. 처리 완료 대기 (polling)
3. POST /{ig-user-id}/media_publish — 게시

주의: Instagram은 영상을 공개 URL로 접근할 수 있어야 합니다.
서버에 호스팅된 영상의 경우, 앱의 임시 URL을 통해 제공합니다.
"""

import asyncio
import logging
import os

import httpx

log = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v19.0"

# 처리 대기 설정
MAX_POLL_ATTEMPTS = 30
POLL_INTERVAL_SEC = 5


async def _create_media_container(
    ig_user_id: str,
    access_token: str,
    video_url: str,
    caption: str,
) -> str:
    """릴스 미디어 컨테이너 생성.

    Returns:
        creation_id (컨테이너 ID)
    """
    url = f"{GRAPH_API_BASE}/{ig_user_id}/media"
    params = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "access_token": access_token,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, params=params)

    if resp.status_code != 200:
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        error_msg = data.get("error", {}).get("message", resp.text[:300])
        raise RuntimeError(f"Instagram 미디어 컨테이너 생성 실패: {error_msg}")

    data = resp.json()
    creation_id = data.get("id", "")
    if not creation_id:
        raise RuntimeError("Instagram 응답에 컨테이너 ID가 없습니다.")

    return creation_id


async def _wait_for_processing(
    creation_id: str,
    access_token: str,
) -> None:
    """미디어 처리 완료까지 대기 (polling)."""
    url = f"{GRAPH_API_BASE}/{creation_id}"
    params = {
        "fields": "status_code",
        "access_token": access_token,
    }

    for attempt in range(MAX_POLL_ATTEMPTS):
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params)

        if resp.status_code != 200:
            log.warning(f"Instagram 상태 확인 실패 (시도 {attempt + 1}): HTTP {resp.status_code}")
            await asyncio.sleep(POLL_INTERVAL_SEC)
            continue

        data = resp.json()
        status = data.get("status_code", "")

        if status == "FINISHED":
            log.info("Instagram 미디어 처리 완료")
            return
        elif status == "ERROR":
            raise RuntimeError("Instagram 미디어 처리 중 오류가 발생했습니다.")
        elif status == "EXPIRED":
            raise RuntimeError("Instagram 미디어 처리 시간이 초과되었습니다.")

        log.info(f"Instagram 미디어 처리 중... (상태: {status}, 시도 {attempt + 1}/{MAX_POLL_ATTEMPTS})")
        await asyncio.sleep(POLL_INTERVAL_SEC)

    raise RuntimeError(
        f"Instagram 미디어 처리 대기 시간 초과 ({MAX_POLL_ATTEMPTS * POLL_INTERVAL_SEC}초). "
        "영상이 너무 크거나 Instagram 서버 문제일 수 있습니다."
    )


async def _publish_media(
    ig_user_id: str,
    access_token: str,
    creation_id: str,
) -> str:
    """미디어 게시.

    Returns:
        media_id
    """
    url = f"{GRAPH_API_BASE}/{ig_user_id}/media_publish"
    params = {
        "creation_id": creation_id,
        "access_token": access_token,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, params=params)

    if resp.status_code != 200:
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        error_msg = data.get("error", {}).get("message", resp.text[:300])
        raise RuntimeError(f"Instagram 게시 실패: {error_msg}")

    data = resp.json()
    media_id = data.get("id", "")
    if not media_id:
        raise RuntimeError("Instagram 게시 응답에 media ID가 없습니다.")

    return media_id


async def _get_media_permalink(media_id: str, access_token: str) -> str:
    """게시된 미디어의 퍼마링크 조회."""
    url = f"{GRAPH_API_BASE}/{media_id}"
    params = {
        "fields": "permalink",
        "access_token": access_token,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params)

        if resp.status_code == 200:
            data = resp.json()
            return data.get("permalink", "")
    except Exception as e:
        log.warning(f"Instagram 퍼마링크 조회 실패: {e}")

    return ""


async def upload_to_instagram(
    video_path: str,
    caption: str,
    access_token: str = "",
    ig_user_id: str = "",
    video_public_url: str = "",
) -> dict:
    """Instagram Graph API로 릴스 업로드.

    Args:
        video_path: 업로드할 영상 파일 경로 (존재 확인용)
        caption: 게시물 캡션
        access_token: Instagram Graph API access token
        ig_user_id: Instagram 비즈니스 계정 ID
        video_public_url: 영상의 공개 접근 가능 URL
            (Instagram은 직접 파일 업로드를 지원하지 않으므로,
             서버에서 임시로 호스팅한 URL을 전달해야 함)

    Returns:
        {"media_id": str, "url": str}
    """
    # 파일 검증
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"영상 파일을 찾을 수 없습니다: {video_path}")

    if not access_token:
        raise ValueError("Instagram access token이 필요합니다. 설정에서 등록해주세요.")

    if not ig_user_id:
        raise ValueError("Instagram 사용자 ID가 필요합니다. 설정에서 등록해주세요.")

    if not video_public_url:
        raise ValueError(
            "Instagram 업로드에는 영상의 공개 URL이 필요합니다. "
            "서버 도메인이 설정되어 있는지 확인해주세요."
        )

    log.info(f"Instagram 릴스 업로드 시작: {caption[:50]}...")

    # 1) 미디어 컨테이너 생성
    creation_id = await _create_media_container(
        ig_user_id=ig_user_id,
        access_token=access_token,
        video_url=video_public_url,
        caption=caption,
    )
    log.info(f"Instagram 컨테이너 생성됨: {creation_id}")

    # 2) 처리 완료 대기
    await _wait_for_processing(creation_id, access_token)

    # 3) 게시
    media_id = await _publish_media(ig_user_id, access_token, creation_id)
    log.info(f"Instagram 게시 완료: media_id={media_id}")

    # 4) 퍼마링크 조회
    permalink = await _get_media_permalink(media_id, access_token)

    return {
        "media_id": media_id,
        "url": permalink or f"https://www.instagram.com/reel/{media_id}/",
    }


async def post_comment(
    media_id: str,
    comment_text: str,
    access_token: str,
) -> dict:
    """인스타그램 게시물에 댓글 작성 (프로필 링크 안내 등).

    Returns:
        {"comment_id": str}
    """
    url = f"{GRAPH_API_BASE}/{media_id}/comments"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, data={
            "message": comment_text,
            "access_token": access_token,
        })

    if resp.status_code not in (200, 201):
        log.warning(f"Instagram 댓글 작성 실패 (HTTP {resp.status_code}): {resp.text[:300]}")
        return {"comment_id": "", "error": resp.text[:300]}

    data = resp.json()
    comment_id = data.get("id", "")
    log.info(f"Instagram 댓글 작성 완료: {comment_id}")
    return {"comment_id": comment_id}
