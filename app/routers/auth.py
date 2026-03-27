"""관리자 인증 라우터"""
import time
from collections import defaultdict
from datetime import datetime, timedelta

import bcrypt
from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from jose import jwt, JWTError

from config import settings

router = APIRouter()

templates = Jinja2Templates(directory="app/templates")

ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24
COOKIE_NAME = "commerce_token"

# 비밀번호 해시 (시작 시 1회)
_ADMIN_PW_HASH: bytes = bcrypt.hashpw(settings.ADMIN_PASSWORD.encode(), bcrypt.gensalt())

# 로그인 속도 제한 — IP별 최근 시도 타임스탬프
_login_attempts: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT_MAX = 5
_RATE_LIMIT_WINDOW = 60  # 초


def create_token() -> str:
    """JWT 토큰을 생성합니다."""
    expire = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {"sub": "admin", "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> bool:
    """JWT 토큰을 검증합니다."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub") == "admin"
    except JWTError:
        return False


def require_auth(request: Request) -> bool:
    """인증 여부를 확인합니다. 인증되지 않으면 False를 반환합니다."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return False
    return verify_token(token)


@router.get("/login")
async def login_page(request: Request):
    """로그인 페이지를 렌더링합니다."""
    if require_auth(request):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


def _check_rate_limit(ip: str) -> bool:
    """IP 기반 속도 제한. 초과 시 True 반환."""
    now = time.time()
    attempts = _login_attempts[ip]
    _login_attempts[ip] = [t for t in attempts if now - t < _RATE_LIMIT_WINDOW]
    return len(_login_attempts[ip]) >= _RATE_LIMIT_MAX


@router.post("/login")
async def login(request: Request):
    """비밀번호를 확인하고 JWT 쿠키를 설정합니다."""
    client_ip = request.client.host if request.client else "unknown"

    if _check_rate_limit(client_ip):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "로그인 시도가 너무 많습니다. 잠시 후 다시 시도하세요.",
        })

    form = await request.form()
    password = form.get("password", "")

    if not bcrypt.checkpw(password.encode(), _ADMIN_PW_HASH):
        _login_attempts[client_ip].append(time.time())
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "비밀번호가 올바르지 않습니다.",
        })

    # 성공 시 시도 기록 초기화
    _login_attempts.pop(client_ip, None)

    token = create_token()
    response = RedirectResponse(url="/", status_code=302)
    is_https = request.url.scheme == "https"
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=is_https,
        max_age=TOKEN_EXPIRE_HOURS * 3600,
        samesite="lax",
    )
    return response


@router.post("/logout")
async def logout_post():
    """POST 로그아웃 (폼 제출)."""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response


@router.get("/logout")
async def logout():
    """GET 로그아웃 (링크 클릭)."""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response
