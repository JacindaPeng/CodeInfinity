"""语音转文字（Whisper 本地识别，供对话语音输入）。"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from ..config import settings
from ..utils.ffmpeg_path import ensure_ffmpeg_on_path, resolve_ffmpeg


def whisper_available() -> bool:
    try:
        import whisper  # noqa: F401
        return True
    except ImportError:
        return False


def ffmpeg_available() -> bool:
    return resolve_ffmpeg(settings.ffmpeg_path or None) is not None


def speech_available() -> bool:
    return whisper_available() and ffmpeg_available()


def _prepare_runtime() -> None:
    ensure_ffmpeg_on_path(settings.ffmpeg_path or None)
    if not ffmpeg_available():
        raise RuntimeError(
            "未找到 ffmpeg。请安装后重启后端（winget install Gyan.FFmpeg），"
            "或在 .env 中设置 FFMPEG_PATH 指向 ffmpeg.exe"
        )
    if not whisper_available():
        raise RuntimeError("未安装 Whisper，请执行: pip install -r requirements_video.txt")


def _to_wav(src: str) -> str:
    ffmpeg = resolve_ffmpeg(settings.ffmpeg_path or None)
    if not ffmpeg or src.lower().endswith(".wav"):
        return src
    out = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    out.close()
    cmd = [
        ffmpeg, "-y", "-i", src,
        "-ar", "16000", "-ac", "1", "-f", "wav", out.name,
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        err = (e.stderr or b"").decode("utf-8", errors="replace")[-400:]
        raise RuntimeError(f"ffmpeg 无法解析录音: {err or e}") from e
    return out.name


def transcribe_audio_file(path: str) -> str:
    """将音频文件转为中文文本。"""
    _prepare_runtime()
    from .video_service import normalize_subtitle, transcribe

    wav_path = _to_wav(path)
    try:
        segs = transcribe(wav_path)
        text = normalize_subtitle("".join(s["text"] for s in segs)).strip()
        if not text:
            from .video_service import _get_whisper_model
            model = _get_whisper_model()
            result = model.transcribe(wav_path, language="zh", verbose=False, temperature=0.0)
            text = normalize_subtitle((result.get("text") or "").strip())
        if not text:
            raise ValueError("未识别到有效语音内容")
        return text
    finally:
        if wav_path != path:
            try:
                os.unlink(wav_path)
            except OSError:
                pass

async def transcribe_upload(raw: bytes, filename: str) -> str:
    suffix = Path(filename).suffix.lower() or ".webm"
    if suffix not in {".webm", ".wav", ".mp3", ".m4a", ".ogg", ".mp4"}:
        suffix = ".webm"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(raw)
        tmp.close()
        return transcribe_audio_file(tmp.name)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
