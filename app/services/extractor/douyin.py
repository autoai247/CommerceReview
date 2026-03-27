"""더우인(Douyin) 영상 다운로드 — Playwright 기반 전체 구현"""

import asyncio
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import httpx


async def download_douyin(url: str, output_dir: str) -> dict:
    """Playwright로 더우인 영상 다운로드.

    핵심 로직:
    1. Playwright headless 브라우저 시작 (Chromium)
    2. douyin.com 메인 접속 → 쿠키 자동 획득
    3. 영상 페이지 로드
    4. network response에서 douyinvod/bytevod URL 캡처 (video+audio)
    5. httpx로 전체 다운로드 (쿠키 + Referer 헤더 포함)
    6. ffmpeg로 video+audio merge → 최종 mp4

    Args:
        url: 더우인 영상 URL (short link or full link)
        output_dir: 다운로드 결과 저장 디렉터리

    Returns:
        {
            "video_path": str,     # 최종 mp4 경로
            "title": str,          # 영상 제목
            "description": str,    # 영상 설명
            "duration": float,     # 영상 길이(초), 추출 가능 시
        }
    """
    from playwright.async_api import async_playwright

    os.makedirs(output_dir, exist_ok=True)

    video_urls: list[str] = []
    audio_urls: list[str] = []
    title = ""
    description = ""

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        # navigator.platform 스푸핑 (필수: 'Win32'로 설정해야 차단 안 됨)
        await context.add_init_script("""
            Object.defineProperty(navigator, 'platform', {
                get: () => 'Win32'
            });
            Object.defineProperty(navigator, 'webdriver', {
                get: () => false
            });
        """)

        page = await context.new_page()

        # --- Step 1: douyin.com 메인 접속으로 쿠키 획득 ---
        try:
            await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
        except Exception:
            # 메인 페이지 로드 실패해도 계속 진행
            pass

        # --- Step 2: response 이벤트로 video/audio URL 캡처 ---
        def on_response(response):
            resp_url = response.url
            content_type = response.headers.get("content-type", "")

            # douyinvod, bytevod 등에서 비디오/오디오 스트림 캡처
            is_vod = any(
                domain in resp_url
                for domain in [
                    "douyinvod.com",
                    "bytevcloudcdn.com",
                    "bytevc1.com",
                    "bytevc2.com",
                    "bytedns.net",
                    "byteicdn.com",
                    "douyincdn.com",
                ]
            )

            if is_vod:
                if "video/" in content_type or "video" in resp_url.lower():
                    if resp_url not in video_urls:
                        video_urls.append(resp_url)
                elif "audio/" in content_type or "audio" in resp_url.lower():
                    if resp_url not in audio_urls:
                        audio_urls.append(resp_url)
                else:
                    # content-type 불분명해도 일단 video_urls에 추가
                    if resp_url not in video_urls:
                        video_urls.append(resp_url)

        page.on("response", on_response)

        # --- Step 3: 영상 페이지 로드 ---
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass

        # 페이지가 완전히 로드될 때까지 대기 + 영상 재생 시작 대기
        await page.wait_for_timeout(5000)

        # 영상 재생 트리거: video 요소 클릭 시도
        try:
            video_el = await page.query_selector("video")
            if video_el:
                await video_el.click()
                await page.wait_for_timeout(3000)
        except Exception:
            pass

        # --- Step 4: 메타데이터 추출 ---
        try:
            # 제목 추출
            title_el = await page.query_selector(
                '[data-e2e="video-desc"], .video-info-detail, '
                'meta[name="description"], title'
            )
            if title_el:
                tag_name = await title_el.evaluate("el => el.tagName.toLowerCase()")
                if tag_name == "meta":
                    title = await title_el.get_attribute("content") or ""
                elif tag_name == "title":
                    title = await title_el.inner_text()
                else:
                    title = await title_el.inner_text()
            if not title:
                title = await page.title()
        except Exception:
            title = await page.title() if page else ""

        description = title  # 더우인은 제목 ≈ 설명

        # --- Step 5: video src에서 직접 URL 가져오기 (fallback) ---
        if not video_urls:
            try:
                video_src = await page.evaluate("""
                    () => {
                        const v = document.querySelector('video');
                        if (v) {
                            // source 태그에서
                            const source = v.querySelector('source');
                            if (source && source.src) return source.src;
                            if (v.src) return v.src;
                        }
                        return null;
                    }
                """)
                if video_src:
                    video_urls.append(video_src)
            except Exception:
                pass

        # 추가 대기 후 재시도
        if not video_urls:
            await page.wait_for_timeout(5000)

        # 쿠키 추출
        cookies = await context.cookies()
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)

        await browser.close()

    if not video_urls:
        raise RuntimeError(
            "더우인 영상 URL을 캡처하지 못했습니다. "
            "URL이 올바른지 확인하거나 잠시 후 다시 시도하세요."
        )

    # --- Step 6: httpx로 다운로드 ---
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.douyin.com/",
        "Cookie": cookie_str,
    }

    timestamp = int(time.time())
    video_file = os.path.join(output_dir, f"video_{timestamp}.mp4")
    audio_file = os.path.join(output_dir, f"audio_{timestamp}.m4a")
    output_file = os.path.join(output_dir, f"douyin_{timestamp}.mp4")

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(120.0),
        headers=headers,
    ) as client:
        # 비디오 다운로드 — 가장 큰 파일을 선택하기 위해 첫 번째 URL 사용
        video_url = video_urls[0]
        resp = await client.get(video_url)
        resp.raise_for_status()
        with open(video_file, "wb") as f:
            f.write(resp.content)

        # 오디오가 별도로 있는 경우 다운로드
        has_separate_audio = False
        if audio_urls:
            audio_url = audio_urls[0]
            resp = await client.get(audio_url)
            resp.raise_for_status()
            with open(audio_file, "wb") as f:
                f.write(resp.content)
            has_separate_audio = True

    # --- Step 7: ffmpeg merge (video+audio가 분리된 경우) ---
    if has_separate_audio:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_file,
            "-i", audio_file,
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            output_file,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg merge 실패: {stderr.decode()}")

        # 임시 파일 삭제
        try:
            os.remove(video_file)
            os.remove(audio_file)
        except OSError:
            pass
    else:
        # video만 있으면 그대로 사용
        os.rename(video_file, output_file)

    # 영상 길이 추출
    duration = 0.0
    try:
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json",
            output_file,
        ]
        proc = await asyncio.create_subprocess_exec(
            *probe_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            probe = json.loads(stdout.decode())
            duration = float(probe.get("format", {}).get("duration", 0))
    except Exception:
        pass

    return {
        "video_path": output_file,
        "title": title.strip()[:200] if title else "",
        "description": description.strip()[:500] if description else "",
        "duration": duration,
    }
