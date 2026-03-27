"""FFmpeg 기반 자막 번인 (한국어 자막 하드코딩)"""

import asyncio
import os


async def burn_subtitles(
    video_path: str,
    srt_path: str,
    output_path: str,
    font_name: str = "Noto Sans CJK KR",
    font_size: int = 24,
    primary_colour: str = "&HFFFFFF",
    outline_colour: str = "&H000000",
    outline: int = 2,
    bold: int = 1,
    margin_v: int = 30,
) -> str:
    """한국어 자막을 영상에 하드코딩 (burn-in).

    Args:
        video_path: 입력 영상 경로
        srt_path: 한국어 SRT 자막 파일 경로
        output_path: 출력 영상 경로
        font_name: 자막 폰트 (기본: Noto Sans CJK KR)
        font_size: 폰트 크기
        primary_colour: 자막 텍스트 색상 (ASS 형식)
        outline_colour: 자막 외곽선 색상
        outline: 외곽선 두께
        bold: 굵기 (0 또는 1)
        margin_v: 하단 여백(px)

    Returns:
        output_path (성공 시)

    Raises:
        RuntimeError: ffmpeg 실행 실패
        FileNotFoundError: 입력 파일 없음
    """
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"입력 영상을 찾을 수 없습니다: {video_path}")
    if not os.path.isfile(srt_path):
        raise FileNotFoundError(f"자막 파일을 찾을 수 없습니다: {srt_path}")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    # SRT 경로의 특수문자 이스케이프 (ffmpeg subtitles 필터용)
    escaped_srt = srt_path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")

    # force_style 옵션 구성
    force_style = (
        f"FontName={font_name},"
        f"FontSize={font_size},"
        f"PrimaryColour={primary_colour},"
        f"OutlineColour={outline_colour},"
        f"Outline={outline},"
        f"Bold={bold},"
        f"MarginV={margin_v}"
    )

    vf_filter = f"subtitles='{escaped_srt}':force_style='{force_style}'"

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", vf_filter,
        "-c:a", "copy",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        output_path,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode(errors="replace")
        raise RuntimeError(f"FFmpeg 자막 번인 실패 (code={proc.returncode}): {error_msg}")

    if not os.path.isfile(output_path):
        raise RuntimeError("FFmpeg 완료되었으나 출력 파일이 생성되지 않았습니다.")

    return output_path
