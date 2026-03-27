"""URL 파싱: 플랫폼 감지 및 영상/제품 ID 추출"""

import re
from urllib.parse import urlparse


def detect_platform(url: str) -> str | None:
    """URL에서 플랫폼 감지.

    Returns:
        'douyin', 'xiaohongshu', '1688', or None
    """
    if not url:
        return None

    url_lower = url.lower().strip()

    # 더우인 (Douyin)
    if any(d in url_lower for d in ["douyin.com", "v.douyin.com", "iesdouyin.com"]):
        return "douyin"

    # 샤오홍슈 (Xiaohongshu / RED)
    if any(d in url_lower for d in ["xiaohongshu.com", "xhslink.com", "xhs.cn"]):
        return "xiaohongshu"

    # 1688
    if "1688.com" in url_lower:
        return "1688"

    return None


def extract_video_id(url: str, platform: str) -> str | None:
    """URL에서 영상/제품 ID 추출.

    Args:
        url: 원본 URL
        platform: detect_platform() 결과

    Returns:
        ID 문자열 or None
    """
    if not url or not platform:
        return None

    try:
        parsed = urlparse(url)
    except Exception:
        return None

    if platform == "douyin":
        # https://v.douyin.com/xxxxx/ (short link)
        # https://www.douyin.com/video/7123456789012345678
        # /note/ 패턴도 지원
        match = re.search(r"/video/(\d+)", url)
        if match:
            return match.group(1)
        match = re.search(r"/note/(\d+)", url)
        if match:
            return match.group(1)
        # Short link — ID는 path 전체
        if "v.douyin.com" in url or "iesdouyin.com" in url:
            path = parsed.path.strip("/")
            if path:
                return path
        return None

    elif platform == "xiaohongshu":
        # https://www.xiaohongshu.com/explore/65xxxxxx
        # https://www.xiaohongshu.com/discovery/item/65xxxxxx
        # https://xhslink.com/xxxxx
        match = re.search(r"/explore/([a-f0-9]+)", url)
        if match:
            return match.group(1)
        match = re.search(r"/item/([a-f0-9]+)", url)
        if match:
            return match.group(1)
        match = re.search(r"/discovery/item/([a-f0-9]+)", url)
        if match:
            return match.group(1)
        # Short link
        if "xhslink.com" in url or "xhs.cn" in url:
            path = parsed.path.strip("/")
            if path:
                return path
        return None

    elif platform == "1688":
        # https://detail.1688.com/offer/123456789.html
        match = re.search(r"/offer/(\d+)", url)
        if match:
            return match.group(1)
        # https://m.1688.com/offer/123456789.html
        match = re.search(r"offerId[=:](\d+)", url)
        if match:
            return match.group(1)
        return None

    return None
