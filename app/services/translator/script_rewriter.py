"""중국어 원본 자막 → 한국 시청자용 리뷰 대본 재작성"""

import logging
from openai import AsyncOpenAI

log = logging.getLogger(__name__)

REWRITE_PROMPT = """당신은 한국 유튜브 쇼핑 리뷰 전문 작가입니다.

중국어 제품 리뷰 자막을 한국 시청자가 자연스럽게 시청할 수 있는 리뷰 대본으로 재작성하세요.

규칙:
1. 직역이 아니라, 한국 유튜브 리뷰어가 직접 말하는 것처럼 자연스럽게
2. "~거든요" "~더라고요" "~잖아요" 구어체 사용
3. 가격은 한국 원화로 환산 (대략 1위안 = 190원)
4. 중국 특유의 표현은 한국식으로 바꾸기 (예: "太好用了" → "이거 진짜 미쳤어요")
5. 제품의 장단점을 솔직하게 유지
6. 구매를 자연스럽게 유도 (강요 금지, "링크는 설명란에" 정도)
7. 타임스탬프를 유지하되, 문장을 자연스럽게 재구성
8. SRT 형식 유지 (번호, 타임스탬프, 텍스트)

입력: 중국어 SRT 자막의 직역본 (한국어)
출력: 한국 시청자용으로 재작성된 한국어 SRT"""


async def rewrite_script(
    translated_srt: str,
    api_key: str,
    product_name: str = "",
    coupang_link: str = "",
    model: str = "gpt-4o",
) -> str:
    """번역된 SRT를 한국 시청자용 리뷰 대본으로 재작성.

    Args:
        translated_srt: 직역된 한국어 SRT
        api_key: OpenAI API 키
        product_name: 제품명 (있으면 대본에 포함)
        coupang_link: 쿠팡 링크 (있으면 마지막에 언급)
        model: 사용할 모델

    Returns:
        재작성된 한국어 SRT
    """
    if not translated_srt or not translated_srt.strip():
        return ""

    extra = ""
    if product_name:
        extra += f"\n제품명: {product_name}"
    if coupang_link:
        extra += f"\n마지막 자막에 '구매 링크는 설명란 확인!' 을 자연스럽게 넣어주세요."

    client = AsyncOpenAI(api_key=api_key)

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": REWRITE_PROMPT + extra},
            {"role": "user", "content": translated_srt},
        ],
        temperature=0.7,
        max_tokens=4096,
    )

    result = (response.choices[0].message.content or "").strip()
    log.info(f"대본 재작성 완료: {len(result)}자")
    return result
