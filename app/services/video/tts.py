"""한국어 TTS — Edge TTS 기반 (무료, API 키 불필요)"""

import logging
import os
import uuid

log = logging.getLogger(__name__)

# Edge TTS 한국어 음성
VOICES = {
    "sunhi": "ko-KR-SunHiNeural",   # 여성, 밝은
    "injoon": "ko-KR-InJoonNeural",  # 남성, 깊은
}


async def generate_tts(
    text: str,
    output_dir: str,
    voice: str = "sunhi",
    speed: float = 1.0,
) -> dict:
    """SRT 텍스트에서 나레이션 음성 생성.

    Args:
        text: 나레이션 텍스트 (SRT에서 텍스트만 추출하여 전달)
        output_dir: 출력 디렉토리
        voice: 음성 키 (sunhi/injoon)
        speed: 재생 속도

    Returns:
        {"audio_path": str, "duration": float}
    """
    import edge_tts

    voice_id = VOICES.get(voice, VOICES["sunhi"])
    os.makedirs(output_dir, exist_ok=True)

    uid = uuid.uuid4().hex[:8]
    audio_path = os.path.join(output_dir, f"tts_{uid}.mp3")

    rate = f"{int((speed - 1) * 100):+d}%"
    communicate = edge_tts.Communicate(text, voice_id, rate=rate)
    await communicate.save(audio_path)

    # 오디오 길이 확인
    duration = 0.0
    try:
        import subprocess
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
            capture_output=True, text=True, timeout=10,
        )
        duration = float(result.stdout.strip())
    except Exception:
        pass

    log.info(f"TTS 생성: {audio_path} ({duration:.1f}초)")
    return {"audio_path": audio_path, "duration": duration}


def extract_text_from_srt(srt_text: str) -> str:
    """SRT에서 타임스탬프 제거, 텍스트만 추출."""
    import re
    lines = srt_text.strip().split("\n")
    text_lines = []
    for line in lines:
        line = line.strip()
        # 번호 줄 건너뛰기
        if re.match(r"^\d+$", line):
            continue
        # 타임스탬프 줄 건너뛰기
        if re.match(r"\d{2}:\d{2}:\d{2}", line):
            continue
        if line:
            text_lines.append(line)
    return " ".join(text_lines)
