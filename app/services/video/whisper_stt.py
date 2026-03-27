"""OpenAI Whisper API 기반 음성인식 (중국어 → SRT)"""

import asyncio
import os
import tempfile

from openai import AsyncOpenAI


async def extract_audio(video_path: str, output_path: str | None = None) -> str:
    """영상에서 오디오 추출 (ffmpeg).

    Args:
        video_path: 입력 영상 경로
        output_path: 출력 오디오 경로 (None이면 자동 생성)

    Returns:
        오디오 파일 경로 (.mp3)
    """
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"영상 파일을 찾을 수 없습니다: {video_path}")

    if output_path is None:
        base = os.path.splitext(video_path)[0]
        output_path = f"{base}_audio.mp3"

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",                      # 비디오 제거
        "-acodec", "libmp3lame",    # MP3 인코딩
        "-ar", "16000",             # 16kHz (Whisper 최적)
        "-ac", "1",                 # 모노
        "-b:a", "64k",             # 비트레이트 (API 전송 최적화)
        output_path,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"오디오 추출 실패: {stderr.decode(errors='replace')}")

    if not os.path.isfile(output_path):
        raise RuntimeError("ffmpeg 완료되었으나 오디오 파일이 생성되지 않았습니다.")

    return output_path


async def transcribe(
    video_path: str,
    api_key: str,
    language: str = "zh",
    model: str = "whisper-1",
) -> str:
    """OpenAI Whisper API로 중국어 음성 → SRT 자막.

    Args:
        video_path: 입력 영상 경로
        api_key: OpenAI API 키
        language: 음성 언어 코드 (기본: zh = 중국어)
        model: Whisper 모델명

    Returns:
        SRT 형식 자막 문자열
    """
    # 1. 오디오 추출
    audio_path = await extract_audio(video_path)

    try:
        # 2. 파일 크기 확인 (Whisper API 제한: 25MB)
        file_size = os.path.getsize(audio_path)
        if file_size > 25 * 1024 * 1024:
            # 25MB 초과 시 분할 처리
            return await _transcribe_large_file(audio_path, api_key, language, model)

        # 3. Whisper API 호출
        client = AsyncOpenAI(api_key=api_key)

        with open(audio_path, "rb") as audio_file:
            transcript = await client.audio.transcriptions.create(
                model=model,
                file=audio_file,
                response_format="srt",
                language=language,
            )

        return transcript if isinstance(transcript, str) else str(transcript)

    finally:
        # 임시 오디오 파일 정리
        try:
            os.remove(audio_path)
        except OSError:
            pass


async def _transcribe_large_file(
    audio_path: str,
    api_key: str,
    language: str,
    model: str,
    chunk_duration: int = 600,  # 10분 단위
) -> str:
    """25MB 초과 오디오를 분할하여 Whisper API 호출.

    Args:
        audio_path: 오디오 파일 경로
        api_key: OpenAI API 키
        language: 언어 코드
        model: 모델명
        chunk_duration: 분할 단위 (초)

    Returns:
        전체 SRT 자막 (타임스탬프 보정됨)
    """
    import re

    # ffmpeg로 분할
    with tempfile.TemporaryDirectory() as tmp_dir:
        chunk_pattern = os.path.join(tmp_dir, "chunk_%03d.mp3")
        cmd = [
            "ffmpeg", "-y",
            "-i", audio_path,
            "-f", "segment",
            "-segment_time", str(chunk_duration),
            "-c", "copy",
            chunk_pattern,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        # 청크 파일 목록
        chunks = sorted(
            [f for f in os.listdir(tmp_dir) if f.startswith("chunk_") and f.endswith(".mp3")]
        )

        if not chunks:
            raise RuntimeError("오디오 분할에 실패했습니다.")

        client = AsyncOpenAI(api_key=api_key)
        all_srt_parts: list[str] = []
        entry_offset = 0
        time_offset_ms = 0

        for i, chunk_name in enumerate(chunks):
            chunk_path = os.path.join(tmp_dir, chunk_name)

            with open(chunk_path, "rb") as f:
                transcript = await client.audio.transcriptions.create(
                    model=model,
                    file=f,
                    response_format="srt",
                    language=language,
                )

            srt_text = transcript if isinstance(transcript, str) else str(transcript)

            if i > 0 and srt_text.strip():
                # 타임스탬프 오프셋 보정
                srt_text = _offset_srt_timestamps(srt_text, time_offset_ms, entry_offset)

            if srt_text.strip():
                # 현재 청크의 마지막 엔트리 번호 계산
                entries = re.findall(r"^(\d+)\s*$", srt_text, re.MULTILINE)
                if entries:
                    entry_offset = int(entries[-1])

                all_srt_parts.append(srt_text.strip())

            time_offset_ms += chunk_duration * 1000

        return "\n\n".join(all_srt_parts)


def _offset_srt_timestamps(srt_text: str, offset_ms: int, entry_offset: int) -> str:
    """SRT 타임스탬프에 오프셋을 더하고 엔트리 번호를 보정.

    Args:
        srt_text: SRT 텍스트
        offset_ms: 더할 시간(ms)
        entry_offset: 엔트리 번호 오프셋

    Returns:
        보정된 SRT 텍스트
    """
    import re

    def _add_offset(match):
        h, m, s, ms = int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4))
        total_ms = h * 3600000 + m * 60000 + s * 1000 + ms + offset_ms
        new_h = total_ms // 3600000
        total_ms %= 3600000
        new_m = total_ms // 60000
        total_ms %= 60000
        new_s = total_ms // 1000
        new_ms = total_ms % 1000
        return f"{new_h:02d}:{new_m:02d}:{new_s:02d},{new_ms:03d}"

    # 타임스탬프 보정
    result = re.sub(
        r"(\d{2}):(\d{2}):(\d{2}),(\d{3})",
        _add_offset,
        srt_text,
    )

    # 엔트리 번호 보정
    def _fix_entry_num(match):
        return str(int(match.group(1)) + entry_offset)

    result = re.sub(r"^(\d+)\s*$", _fix_entry_num, result, flags=re.MULTILINE)

    return result
