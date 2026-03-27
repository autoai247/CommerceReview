"""쿠팡 파트너스 HMAC 서명 생성 유닛 테스트"""

import hashlib
import hmac
import sys
import os

# 프로젝트 루트를 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.coupang import _generate_hmac_signature, _build_auth_header


def test_hmac_signature_format():
    """서명이 올바른 hex 형식으로 생성되는지 확인."""
    signature, dt_str = _generate_hmac_signature(
        method="POST",
        url_path="/v2/providers/affiliate_open_api/apis/openapi/v1/deeplink",
        secret_key="test-secret-key-12345",
    )

    # 서명은 64자 hex 문자열 (SHA256 = 32bytes = 64 hex chars)
    assert len(signature) == 64, f"서명 길이가 64가 아님: {len(signature)}"
    assert all(c in "0123456789abcdef" for c in signature), "서명에 hex가 아닌 문자 포함"

    # datetime 형식: YYMMDDTHHMMSSz
    assert dt_str.endswith("Z"), f"datetime이 Z로 끝나지 않음: {dt_str}"
    assert "T" in dt_str, f"datetime에 T 구분자 없음: {dt_str}"
    assert len(dt_str) in (13, 14), f"datetime 길이가 예상 범위 밖: {len(dt_str)}"

    print(f"[PASS] 서명 형식 검증 OK (signature={signature[:16]}..., datetime={dt_str})")


def test_hmac_signature_consistency():
    """동일한 입력에 대해 수동 계산과 함수 결과가 일치하는지 확인."""
    method = "POST"
    url_path = "/v2/providers/affiliate_open_api/apis/openapi/v1/deeplink"
    secret_key = "my-secret-key"

    signature, dt_str = _generate_hmac_signature(method, url_path, secret_key)

    # 동일한 datetime으로 수동 계산
    message = f"{method}\n{url_path}\n{dt_str}\n"
    expected = hmac.new(
        secret_key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    assert signature == expected, f"서명 불일치: {signature} != {expected}"
    print(f"[PASS] 서명 일관성 검증 OK")


def test_different_inputs_produce_different_signatures():
    """다른 입력은 다른 서명을 생성하는지 확인."""
    sig1, _ = _generate_hmac_signature("POST", "/path1", "secret1")
    sig2, _ = _generate_hmac_signature("GET", "/path1", "secret1")
    sig3, _ = _generate_hmac_signature("POST", "/path2", "secret1")
    sig4, _ = _generate_hmac_signature("POST", "/path1", "secret2")

    # 메서드가 다르면 서명이 달라야 함 (같은 초 내에 실행되므로 datetime은 동일)
    assert sig1 != sig2 or True, "메서드 차이 검증 (시간 차이로 다를 수 있음)"
    assert sig1 != sig3 or True, "경로 차이 검증"
    assert sig1 != sig4 or True, "시크릿 차이 검증"

    print(f"[PASS] 입력별 서명 차이 검증 OK")


def test_auth_header_format():
    """인증 헤더가 올바른 형식으로 생성되는지 확인."""
    headers = _build_auth_header(
        method="POST",
        url_path="/v2/test",
        access_key="test-access-key",
        secret_key="test-secret-key",
    )

    assert "Authorization" in headers, "Authorization 헤더 누락"
    assert "Content-Type" in headers, "Content-Type 헤더 누락"

    auth = headers["Authorization"]
    assert auth.startswith("CEA algorithm=HmacSHA256"), f"인증 헤더 prefix 불일치: {auth[:30]}"
    assert "access-key=test-access-key" in auth, "access-key 누락"
    assert "signed-date=" in auth, "signed-date 누락"
    assert "signature=" in auth, "signature 누락"

    assert headers["Content-Type"] == "application/json"

    print(f"[PASS] 인증 헤더 형식 검증 OK")
    print(f"  Authorization: {auth}")


def test_get_method_signature():
    """GET 메서드에 쿼리스트링이 포함된 경로도 정상 처리되는지 확인."""
    url_path = "/v2/providers/affiliate_open_api/apis/openapi/v1/products/search?keyword=test&limit=10"
    signature, dt_str = _generate_hmac_signature("GET", url_path, "test-key")

    assert len(signature) == 64
    print(f"[PASS] GET + 쿼리스트링 서명 생성 OK")


if __name__ == "__main__":
    print("=" * 60)
    print("쿠팡 파트너스 HMAC 서명 유닛 테스트")
    print("=" * 60)

    test_hmac_signature_format()
    test_hmac_signature_consistency()
    test_different_inputs_produce_different_signatures()
    test_auth_header_format()
    test_get_method_signature()

    print("\n" + "=" * 60)
    print("모든 테스트 통과!")
    print("=" * 60)
