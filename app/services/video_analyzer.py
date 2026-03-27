"""Gemini 3.1 Pro 영상 분석 — 영상을 직접 보고 한국어 대본 생성

더우인/샤오홍슈/1688 영상을 Gemini에 넣으면:
1. 무슨 제품인지 자동 파악
2. 중국어 음성 이해
3. 화면 속 제품/사용 장면 분석
4. 한국어 리뷰 대본 + SRT 자막 생성
→ 4단계가 1단계로 줄어듦
"""

import logging
import os
import json
import asyncio
import subprocess

import httpx

log = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com"


async def analyze_video(
    video_path: str,
    api_key: str,
    coupang_link: str = "",
    model: str = "gemini-3.1-pro-preview",
) -> dict:
    """영상을 Gemini에 직접 입력해서 한국어 리뷰 대본 생성.

    Args:
        video_path: 영상 파일 경로
        api_key: Google AI API 키
        coupang_link: 쿠팡 파트너스 링크 (있으면 대본에 포함)
        model: Gemini 모델명

    Returns:
        {
            "product_name": str,      # 제품명
            "product_category": str,  # 카테고리
            "original_text": str,     # 원본 중국어 텍스트
            "script_ko": str,         # 한국어 대본
            "subtitle_srt": str,      # 한국어 SRT 자막
            "summary": str,           # 영상 요약
            "pros": list[str],        # 장점
            "cons": list[str],        # 단점
        }
    """
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"영상 파일 없음: {video_path}")

    file_size = os.path.getsize(video_path)
    log.info(f"영상 분석 시작: {video_path} ({file_size // 1024}KB)")

    # Step 1: 영상 파일 업로드 (Gemini File API)
    file_uri = await _upload_file(video_path, api_key)
    log.info(f"파일 업로드 완료: {file_uri}")

    # Step 2: 영상 처리 완료 대기
    await _wait_for_processing(file_uri, api_key)

    # Step 3: 영상 분석 + 대본 생성
    coupang_note = ""
    if coupang_link:
        coupang_note = f"\n마지막에 '구매 링크는 설명란에서 확인하세요' 를 자연스럽게 넣어주세요."

    prompt = f"""이 영상은 중국 온라인 쇼핑몰의 제품 리뷰/시연 영상입니다.

영상을 보고 다음을 분석해주세요:

1. 제품명과 카테고리
2. 영상 속 중국어 음성 내용 (원문)
3. 한국 유튜브 시청자를 위한 리뷰 대본
4. SRT 자막

★★★ 한국어 리뷰 대본 규칙 ★★★
- 한국 유튜버가 직접 제품을 리뷰하는 톤으로 작성
- "~거든요" "~더라고요" "~잖아요" 구어체
- 장점과 단점을 솔직하게
- 영상에 보이는 장면을 구체적으로 묘사 ("영상 보시면 여기서 ~ 하는데요")
- 가격은 한국 원화로 대략 환산 (1위안 ≈ 190원)
- 직역이 아니라 자연스러운 한국어{coupang_note}

아래 JSON 형식으로 출력:
{{
    "product_name": "제품명 (한국어)",
    "product_category": "카테고리",
    "original_text": "중국어 음성 원문 전체",
    "script_ko": "한국어 리뷰 대본 전체 (구어체, 100어절 이상)",
    "subtitle_srt": "한국어 SRT 자막 (타임스탬프 포함, 5초 단위)",
    "summary": "영상 한 줄 요약",
    "pros": ["장점1", "장점2", ...],
    "cons": ["단점1", "단점2", ...]
}}"""

    result = await _generate_with_video(file_uri, prompt, api_key, model)
    log.info(f"영상 분석 완료: {len(result)}자")

    # JSON 파싱
    parsed = _parse_json(result)
    return parsed


async def _upload_file(file_path: str, api_key: str) -> str:
    """Gemini File API로 영상 업로드. Returns file URI."""
    file_size = os.path.getsize(file_path)
    mime_type = "video/mp4"

    # Resumable upload 시작
    async with httpx.AsyncClient(timeout=60) as client:
        # 1. Upload 세션 시작
        resp = await client.post(
            f"{GEMINI_API_BASE}/upload/v1beta/files",
            params={"key": api_key},
            headers={
                "X-Goog-Upload-Protocol": "resumable",
                "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(file_size),
                "X-Goog-Upload-Header-Content-Type": mime_type,
                "Content-Type": "application/json",
            },
            json={"file": {"display_name": os.path.basename(file_path)}},
        )

        if resp.status_code != 200:
            raise RuntimeError(f"파일 업로드 시작 실패 (HTTP {resp.status_code}): {resp.text[:300]}")

        upload_url = resp.headers.get("X-Goog-Upload-URL")
        if not upload_url:
            raise RuntimeError("업로드 URL을 받지 못했습니다.")

        # 2. 파일 데이터 전송
        with open(file_path, "rb") as f:
            file_data = f.read()

        resp2 = await client.put(
            upload_url,
            headers={
                "X-Goog-Upload-Command": "upload, finalize",
                "X-Goog-Upload-Offset": "0",
                "Content-Length": str(file_size),
            },
            content=file_data,
            timeout=300,  # 큰 파일 대비
        )

        if resp2.status_code != 200:
            raise RuntimeError(f"파일 업로드 실패 (HTTP {resp2.status_code}): {resp2.text[:300]}")

        data = resp2.json()
        file_uri = data.get("file", {}).get("uri", "")
        if not file_uri:
            raise RuntimeError(f"파일 URI 없음: {data}")

        return file_uri


async def _wait_for_processing(file_uri: str, api_key: str, max_wait: int = 120):
    """업로드된 파일이 처리될 때까지 대기."""
    file_name = file_uri.split("/")[-1] if "/" in file_uri else file_uri

    for attempt in range(max_wait // 5):
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{GEMINI_API_BASE}/v1beta/files/{file_name}",
                params={"key": api_key},
            )

        if resp.status_code == 200:
            data = resp.json()
            state = data.get("state", "")
            if state == "ACTIVE":
                return
            elif state == "FAILED":
                raise RuntimeError(f"파일 처리 실패: {data}")

        await asyncio.sleep(5)

    raise RuntimeError(f"파일 처리 타임아웃 ({max_wait}초)")


async def _generate_with_video(
    file_uri: str,
    prompt: str,
    api_key: str,
    model: str,
) -> str:
    """Gemini에 영상 + 프롬프트 전송."""
    url = f"{GEMINI_API_BASE}/v1beta/models/{model}:generateContent"

    body = {
        "contents": [
            {
                "parts": [
                    {"file_data": {"mime_type": "video/mp4", "file_uri": file_uri}},
                    {"text": prompt},
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 8192,
            "responseMimeType": "application/json",
        },
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, params={"key": api_key}, json=body)

    if resp.status_code != 200:
        raise RuntimeError(f"Gemini 생성 실패 (HTTP {resp.status_code}): {resp.text[:500]}")

    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"Gemini 응답 없음: {data}")

    text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
    return text


def _parse_json(text: str) -> dict:
    """Gemini 출력에서 JSON 파싱."""
    import re

    # ```json 블록 추출
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    # JSON 객체 추출
    text = text.strip()
    if not text.startswith("{"):
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            text = match.group(0)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 기본 구조 반환
        return {
            "product_name": "",
            "product_category": "",
            "original_text": "",
            "script_ko": text,
            "subtitle_srt": "",
            "summary": "",
            "pros": [],
            "cons": [],
            "parse_error": True,
        }
