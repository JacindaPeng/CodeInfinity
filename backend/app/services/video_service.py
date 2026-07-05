"""视频处理：ffmpeg 抽音频 → whisper 转写 → 按 N 秒分段。

输出: list[(start_sec, end_sec, text)]，并返回纯文本切片（带时间戳元数据）。
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..config import settings

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=400, chunk_overlap=40,
    separators=["\n\n", "\n", "。", "；", " ", ""],
)

# 跳过 whisper import 直至真正需要，避免冷启动慢
_whisper_model = None


def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        import whisper
        # tiny 中文也能用，速度快、体积小；可改 base 提升精度
        _whisper_model = whisper.load_model("tiny")
    return _whisper_model


def extract_audio(video_path: str) -> str:
    """用 ffmpeg 抽取 16k 单声道 wav。"""
    out = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    out.close()
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-ar", "16000", "-ac", "1", "-f", "wav", out.name,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out.name


def transcribe(audio_path: str) -> list[dict]:
    """返回 [{"start": float, "end": float, "text": str}]。"""
    model = _get_whisper_model()
    result = model.transcribe(audio_path, language="zh", verbose=False)
    segs = []
    for s in result.get("segments", []):
        text = (s.get("text") or "").strip()
        if text:
            segs.append({"start": float(s["start"]), "end": float(s["end"]), "text": text})
    return segs


def segments_to_chunks(segs: list[dict], chunk_seconds: int = 30) -> list[tuple[str, dict]]:
    """将连续字幕按 chunk_seconds 聚合为带时间戳的文本切片。"""
    out: list[tuple[str, dict]] = []
    if not segs:
        return out

    cur_start = int(segs[0]["start"])
    cur_end = cur_start
    cur_texts: list[str] = []

    def flush(start: int, end: int, texts: list[str]) -> None:
        text = " ".join(texts).strip()
        if not text:
            return
        # 进一步按 splitter 切分长聚合段
        for piece in _splitter.split_text(text):
            if piece.strip():
                out.append((piece, {"start_sec": start, "end_sec": end}))

    for s in segs:
        s_start = int(s["start"]); s_end = int(s["end"])
        if s_start - cur_start >= chunk_seconds and cur_texts:
            flush(cur_start, cur_end, cur_texts)
            cur_start = s_start; cur_texts = []
        cur_texts.append(s["text"])
        cur_end = s_end
    flush(cur_start, cur_end, cur_texts)
    return out


def process_video(video_path: str, base_meta: dict[str, Any]) -> dict:
    """完整流程：抽音频 → 转写 → 分段 → 切片。
    返回 {"segments": [VideoSegment dict...], "chunks": [(text, meta)...]}。
    """
    audio = extract_audio(video_path)
    try:
        segs = transcribe(audio)
    finally:
        try: os.unlink(audio)
        except OSError: pass

    chunks = segments_to_chunks(segs)
    # 给每个 chunk 加上 base_meta（material_id/chapter_id 等）
    enriched = [(t, {**base_meta, **m}) for t, m in chunks]
    return {"segments": segs, "chunks": enriched}
