"""암호화 서비스 — Fernet 기반 대칭 암호화"""
import base64
import logging

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from config import settings

log = logging.getLogger(__name__)

# SECRET_KEY로부터 Fernet 키 파생 (고정 salt — 동일 SECRET_KEY 시 동일 결과)
_SALT = b"commercereview-fernet-v1"


def _derive_key(secret: str) -> bytes:
    """SECRET_KEY를 PBKDF2로 파생하여 Fernet 호환 키 생성"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        iterations=480_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(secret.encode()))


def _get_fernet() -> Fernet:
    return Fernet(_derive_key(settings.SECRET_KEY))


def encrypt(plaintext: str) -> str:
    """평문 -> 암호문 (Fernet, base64 문자열 반환)"""
    if not plaintext:
        return ""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """암호문 -> 평문. 복호화 실패 시 원본 반환 (마이그레이션 호환)"""
    if not ciphertext:
        return ""
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, Exception):
        # 암호화되지 않은 기존 데이터 — 원본 그대로 반환
        log.debug("복호화 실패, 평문으로 간주")
        return ciphertext
