"""쿠팡 파트너스 API 연동

Coupang Partners Open API를 통한 어필리에이트 딥링크 생성 및 상품 검색.
인증: HMAC-SHA256 서명 방식 (ACCESS_KEY + SECRET_KEY)
"""

import hashlib
import hmac
import logging
import time
from datetime import datetime, timezone

import httpx

log = logging.getLogger(__name__)

# ──────────────────────────── 상수 ────────────────────────────

COUPANG_API_BASE = "https://api-gateway.coupang.com"
DEEPLINK_PATH = "/v2/providers/affiliate_open_api/apis/openapi/v1/deeplink"
SEARCH_PATH = "/v2/providers/affiliate_open_api/apis/openapi/v1/products/search"


# ──────────────────────────── HMAC 서명 ────────────────────────────

def _generate_hmac_signature(
    method: str,
    url_path: str,
    secret_key: str,
) -> tuple[str, str]:
    """HMAC-SHA256 서명 생성.

    Coupang Partners 인증 헤더에 필요한 서명과 datetime 문자열을 반환.

    Args:
        method: HTTP 메서드 (POST, GET 등)
        url_path: 요청 경로 (쿼리스트링 포함 가능)
        secret_key: 쿠팡 파트너스 SECRET KEY

    Returns:
        (signature_hex, datetime_str) 튜플
    """
    datetime_str = datetime.now(timezone.utc).strftime("%y%m%dT%H%M%SZ")

    # 서명 대상 문자열: "{METHOD}\n{PATH}\n{DATETIME}\n"
    message = f"{method}\n{url_path}\n{datetime_str}\n"

    signature = hmac.new(
        secret_key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return signature, datetime_str


def _build_auth_header(
    method: str,
    url_path: str,
    access_key: str,
    secret_key: str,
) -> dict[str, str]:
    """Coupang Partners API 인증 헤더 생성."""
    signature, datetime_str = _generate_hmac_signature(method, url_path, secret_key)

    authorization = (
        f"CEA algorithm=HmacSHA256, access-key={access_key}, "
        f"signed-date={datetime_str}, signature={signature}"
    )

    return {
        "Authorization": authorization,
        "Content-Type": "application/json",
    }


# ──────────────────────────── 딥링크 생성 ────────────────────────────

async def generate_affiliate_link(
    product_id: str,
    access_key: str,
    secret_key: str,
) -> dict:
    """쿠팡 상품번호로 파트너스 어필리에이트 링크 생성.

    Args:
        product_id: 쿠팡 상품번호 (숫자)
        access_key: 쿠팡 파트너스 ACCESS KEY
        secret_key: 쿠팡 파트너스 SECRET KEY

    Returns:
        {
            "original_url": "https://www.coupang.com/vp/products/...",
            "affiliate_url": "https://link.coupang.com/...",
            "short_url": "https://link.coupang.com/..."
        }

    Raises:
        ValueError: 잘못된 입력
        RuntimeError: API 호출 실패
    """
    # 입력 검증
    product_id = str(product_id).strip()
    if not product_id.isdigit():
        raise ValueError("상품번호는 숫자만 입력 가능합니다.")

    if not access_key or not secret_key:
        raise ValueError(
            "쿠팡 파트너스 인증 정보가 설정되지 않았습니다. "
            "설정 페이지에서 ACCESS KEY와 SECRET KEY를 등록해주세요."
        )

    # 1. 상품 URL 구성
    product_url = f"https://www.coupang.com/vp/products/{product_id}"

    # 2. 요청 바디
    request_body = {"coupangUrls": [product_url]}

    # 3. 인증 헤더 생성
    headers = _build_auth_header("POST", DEEPLINK_PATH, access_key, secret_key)

    # 4. API 호출
    url = f"{COUPANG_API_BASE}{DEEPLINK_PATH}"
    log.info(f"쿠팡 딥링크 생성 요청: product_id={product_id}")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, json=request_body)
    except httpx.RequestError as e:
        raise RuntimeError(f"쿠팡 API 서버 연결 실패: {str(e)[:200]}")

    if resp.status_code != 200:
        detail = resp.text[:300]
        log.error(f"쿠팡 딥링크 API 오류 (HTTP {resp.status_code}): {detail}")
        raise RuntimeError(
            f"쿠팡 API 호출 실패 (HTTP {resp.status_code}). "
            "ACCESS KEY와 SECRET KEY를 확인해주세요."
        )

    data = resp.json()

    # 응답 구조: {"rCode": "0", "rMessage": "", "data": [{"originalUrl": ..., "shortenUrl": ...}]}
    r_code = data.get("rCode", "")
    if str(r_code) != "0":
        r_message = data.get("rMessage", "알 수 없는 오류")
        raise RuntimeError(f"쿠팡 API 오류: {r_message}")

    link_data = data.get("data", [])
    if not link_data:
        raise RuntimeError("쿠팡 API에서 딥링크 데이터를 받지 못했습니다.")

    first = link_data[0]
    result = {
        "original_url": first.get("originalUrl", product_url),
        "affiliate_url": first.get("landingUrl", first.get("shortenUrl", "")),
        "short_url": first.get("shortenUrl", ""),
    }

    log.info(f"쿠팡 딥링크 생성 완료: {result['short_url']}")
    return result


# ──────────────────────────── 상품 검색 ────────────────────────────

async def search_products(
    keyword: str,
    access_key: str,
    secret_key: str,
    limit: int = 10,
) -> list[dict]:
    """키워드로 쿠팡 상품 검색.

    Args:
        keyword: 검색 키워드
        access_key: 쿠팡 파트너스 ACCESS KEY
        secret_key: 쿠팡 파트너스 SECRET KEY
        limit: 최대 결과 수 (기본 10, 최대 100)

    Returns:
        [{
            "product_id": str,
            "title": str,
            "price": int,
            "image_url": str,
            "rating": float,
            "review_count": int,
            "rocket_delivery": bool,
            "product_url": str,
        }]
    """
    if not keyword or not keyword.strip():
        raise ValueError("검색 키워드를 입력해주세요.")

    if not access_key or not secret_key:
        raise ValueError(
            "쿠팡 파트너스 인증 정보가 설정되지 않았습니다. "
            "설정 페이지에서 ACCESS KEY와 SECRET KEY를 등록해주세요."
        )

    limit = max(1, min(limit, 100))

    # 쿼리 파라미터 포함한 경로 구성
    query_path = f"{SEARCH_PATH}?keyword={keyword}&limit={limit}"

    # 인증 헤더
    headers = _build_auth_header("GET", query_path, access_key, secret_key)

    url = f"{COUPANG_API_BASE}{SEARCH_PATH}"
    params = {"keyword": keyword, "limit": limit}

    log.info(f"쿠팡 상품 검색: keyword={keyword}, limit={limit}")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers, params=params)
    except httpx.RequestError as e:
        raise RuntimeError(f"쿠팡 API 서버 연결 실패: {str(e)[:200]}")

    if resp.status_code != 200:
        detail = resp.text[:300]
        log.error(f"쿠팡 검색 API 오류 (HTTP {resp.status_code}): {detail}")
        raise RuntimeError(
            f"쿠팡 검색 API 호출 실패 (HTTP {resp.status_code}). "
            "ACCESS KEY와 SECRET KEY를 확인해주세요."
        )

    data = resp.json()

    r_code = data.get("rCode", "")
    if str(r_code) != "0":
        r_message = data.get("rMessage", "알 수 없는 오류")
        raise RuntimeError(f"쿠팡 검색 API 오류: {r_message}")

    raw_products = data.get("data", {}).get("productData", [])

    products = []
    for item in raw_products:
        products.append({
            "product_id": str(item.get("productId", "")),
            "title": item.get("productName", ""),
            "price": item.get("productPrice", 0),
            "image_url": item.get("productImage", ""),
            "rating": item.get("productRating", 0.0),
            "review_count": item.get("reviewCount", 0),
            "rocket_delivery": item.get("isRocket", False),
            "product_url": item.get("productUrl", ""),
        })

    log.info(f"쿠팡 검색 결과: {len(products)}개 상품")
    return products


# ──────────────────────────── 연결 테스트 ────────────────────────────

async def test_connection(access_key: str, secret_key: str) -> dict:
    """쿠팡 파트너스 API 연결 테스트.

    간단한 딥링크 생성 요청으로 인증 정보 유효성 확인.

    Returns:
        {"ok": True/False, "message": str}
    """
    try:
        # 쿠팡 대표 상품으로 테스트 (아무 상품번호나 사용)
        result = await generate_affiliate_link("7643586", access_key, secret_key)
        return {
            "ok": True,
            "message": f"연결 성공! 테스트 딥링크: {result.get('short_url', 'N/A')}",
        }
    except ValueError as e:
        return {"ok": False, "message": str(e)}
    except RuntimeError as e:
        return {"ok": False, "message": str(e)}
    except Exception as e:
        return {"ok": False, "message": f"예기치 않은 오류: {str(e)[:200]}"}
