"""GPT-4o 기반 중국어 → 한국어 SRT 자막 번역"""

import re
from typing import Optional

from openai import AsyncOpenAI


SYSTEM_PROMPT = """당신은 중국어 상품 리뷰 영상의 전문 자막 번역가입니다.

규칙:
1. 중국어 자막을 자연스러운 한국어로 번역합니다.
2. SRT 포맷의 타임스탬프(시간 코드)는 절대 수정하지 마세요. 텍스트 부분만 번역합니다.
3. 제품명, 브랜드명은 원문(중국어/영어) 그대로 유지합니다.
4. 가격, 수량, 사이즈 등 숫자 정보는 정확히 유지합니다.
5. 구어체/판매 화법은 한국어 쇼핑 방송 톤으로 자연스럽게 번역합니다.
6. 번역 결과만 출력합니다. 설명이나 주석은 포함하지 마세요.

입력: SRT 형식의 중국어 자막
출력: 동일 SRT 형식의 한국어 자막 (타임스탬프 그대로, 텍스트만 번역)"""


def _split_srt_into_chunks(srt_text: str, max_entries: int = 20) -> list[str]:
    """SRT를 max_entries 단위로 분할.

    각 SRT 엔트리는 빈 줄로 구분됨:
      1
      00:00:01,000 --> 00:00:03,000
      텍스트

    약 30초 분량 = 약 15~20 엔트리로 추정.
    """
    # 빈 줄 2개 이상을 구분자로 정규화
    srt_text = srt_text.strip()
    # 엔트리를 번호 기준으로 분리
    entries = re.split(r"\n\n+", srt_text)

    chunks = []
    for i in range(0, len(entries), max_entries):
        chunk = "\n\n".join(entries[i : i + max_entries])
        if chunk.strip():
            chunks.append(chunk)

    return chunks if chunks else [srt_text]


async def translate_srt(
    srt_text: str,
    api_key: str,
    model: str = "gpt-4o",
    max_entries_per_chunk: int = 20,
) -> str:
    """중국어 SRT 자막을 한국어로 번역.

    Args:
        srt_text: 원본 중국어 SRT 텍스트
        api_key: OpenAI API 키
        model: 사용할 모델 (기본 gpt-4o)
        max_entries_per_chunk: 한 번에 번역할 최대 SRT 엔트리 수

    Returns:
        번역된 한국어 SRT 텍스트
    """
    if not srt_text or not srt_text.strip():
        return ""

    client = AsyncOpenAI(api_key=api_key)
    chunks = _split_srt_into_chunks(srt_text, max_entries_per_chunk)
    translated_chunks: list[str] = []

    for chunk in chunks:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": chunk},
            ],
            temperature=0.3,
            max_tokens=4096,
        )

        translated = response.choices[0].message.content
        if translated:
            translated_chunks.append(translated.strip())

    return "\n\n".join(translated_chunks)


async def translate_text(
    text: str,
    api_key: str,
    source_lang: str = "Chinese",
    target_lang: str = "Korean",
    model: str = "gpt-4o",
) -> str:
    """일반 텍스트 번역 (제목/설명 등).

    Args:
        text: 원문
        api_key: OpenAI API 키
        source_lang: 원본 언어
        target_lang: 번역 대상 언어

    Returns:
        번역된 텍스트
    """
    if not text or not text.strip():
        return ""

    client = AsyncOpenAI(api_key=api_key)

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    f"{source_lang}을(를) {target_lang}으로 번역하세요. "
                    "상품 리뷰/커머스 맥락입니다. "
                    "제품명과 브랜드명은 원문 유지. 번역 결과만 출력."
                ),
            },
            {"role": "user", "content": text},
        ],
        temperature=0.3,
        max_tokens=1024,
    )

    return (response.choices[0].message.content or "").strip()
