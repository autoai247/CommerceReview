"""CommerceReview — 중국 커머스 리뷰 영상 번역 플랫폼"""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from config import settings
from database import init_db
from app.routers import auth as auth_router
from app.routers import pages as pages_router
from app.routers import jobs as jobs_router
from app.routers import settings as settings_router
from app.routers import upload as upload_router
from app.routers.auth import require_auth


@asynccontextmanager
async def lifespan(app: FastAPI):
    # data 디렉토리 보장
    os.makedirs(settings.DATA_DIR, exist_ok=True)
    os.makedirs(os.path.join(settings.DATA_DIR, "downloads"), exist_ok=True)
    os.makedirs(os.path.join(settings.DATA_DIR, "output"), exist_ok=True)
    os.makedirs(os.path.join(settings.DATA_DIR, "temp"), exist_ok=True)
    os.makedirs(os.path.join(settings.DATA_DIR, "jobs"), exist_ok=True)
    await init_db()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

# 인증 미들웨어: /login, /static 외 모든 경로에서 인증 필요
EXCLUDE_PATHS = ("/login", "/static", "/docs", "/openapi.json")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if not any(path.startswith(p) for p in EXCLUDE_PATHS):
        if not require_auth(request):
            return RedirectResponse(url="/login", status_code=302)
    return await call_next(request)


# 라우터 등록
app.include_router(auth_router.router, tags=["인증"])
app.include_router(pages_router.router, tags=["페이지"])
app.include_router(jobs_router.router, tags=["작업"])
app.include_router(settings_router.router, tags=["설정"])
app.include_router(upload_router.router, tags=["업로드"])
