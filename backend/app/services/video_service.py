"""视频处理：ffmpeg 抽音频 → Whisper 转写 → 按时间/静音间隙聚合切片。

输出: list[(start_sec, end_sec, text)]，并返回纯文本切片（带时间戳元数据）。
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..config import settings
from ..utils.ffmpeg_path import ensure_ffmpeg_on_path, resolve_ffmpeg

logger = logging.getLogger(__name__)

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=400, chunk_overlap=40,
    separators=["\n\n", "\n", "。", "！", "？", "；", " ", ""],
)

# 跳过 whisper import 直至真正需要，避免冷启动慢
_whisper_model = None
_whisper_model_name: str | None = None

_SENTENCE_END = "。！？；!?;"


def _get_whisper_model():
    """按配置加载 Whisper；切换 WHISPER_MODEL 后会重新加载。"""
    global _whisper_model, _whisper_model_name
    name = (settings.whisper_model or "base").strip() or "base"
    if _whisper_model is None or _whisper_model_name != name:
        import whisper
        logger.info("Loading Whisper model: %s", name)
        _whisper_model = whisper.load_model(name)
        _whisper_model_name = name
    return _whisper_model


def extract_audio(video_path: str) -> str:
    """用 ffmpeg 抽取 16k 单声道 wav。"""
    ffmpeg = resolve_ffmpeg(settings.ffmpeg_path or None)
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg，请安装后重启后端")
    ensure_ffmpeg_on_path(settings.ffmpeg_path or None)
    out = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    out.close()
    cmd = [
        ffmpeg, "-y", "-i", video_path,
        "-ar", "16000", "-ac", "1", "-f", "wav", out.name,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out.name


def _use_fp16() -> bool:
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def transcribe(audio_path: str) -> list[dict]:
    """返回 [{"start": float, "end": float, "text": str}]。"""
    model = _get_whisper_model()
    lang = (settings.whisper_language or "zh").strip() or "zh"
    prompt = (settings.whisper_initial_prompt or "").strip() or None

    # temperature=0 + beam 提升稳定性；initial_prompt 压课件术语
    kwargs: dict[str, Any] = {
        "language": lang,
        "verbose": False,
        "temperature": 0.0,
        "condition_on_previous_text": True,
        "fp16": _use_fp16(),
    }
    if prompt:
        kwargs["initial_prompt"] = prompt
    # tiny 资源紧，少用 beam；base/small 可用 beam 提准
    model_name = (settings.whisper_model or "base").lower()
    if model_name not in ("tiny", "tiny.en"):
        kwargs["beam_size"] = 5
        kwargs["best_of"] = 5

    result = model.transcribe(audio_path, **kwargs)
    segs = []
    for s in result.get("segments", []):
        text = normalize_subtitle((s.get("text") or "").strip())
        if text:
            segs.append({"start": float(s["start"]), "end": float(s["end"]), "text": text})
    return segs


def normalize_subtitle(text: str) -> str:
    """轻度规范化，减少全角/空白导致的检索漏匹配。"""
    if not text:
        return ""
    # 常见全角字母数字 → 半角
    out = []
    for ch in text:
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        elif ch in "\u3000\xa0":
            out.append(" ")
        else:
            out.append(ch)
    return " ".join("".join(out).split())


def segments_to_chunks(
    segs: list[dict],
    chunk_seconds: int | None = None,
    gap_sec: float | None = None,
    overlap_sec: int | None = None,
) -> list[tuple[str, dict]]:
    """按时长上限 + 静音间隙 + 句末优先聚合；可选时间重叠提高边界召回。"""
    out: list[tuple[str, dict]] = []
    if not segs:
        return out

    max_dur = int(chunk_seconds if chunk_seconds is not None else settings.video_chunk_seconds)
    max_dur = max(10, max_dur)
    gap = float(gap_sec if gap_sec is not None else settings.video_chunk_gap_sec)
    overlap = int(overlap_sec if overlap_sec is not None else settings.video_chunk_overlap_sec)
    overlap = max(0, min(overlap, max_dur // 2))

    # 工作区保存原始字幕条目，便于算 overlap 窗口
    cur: list[dict] = []
    pending: list[dict] = []

    def _emit_from(items: list[dict]) -> None:
        if not items:
            return
        text = " ".join(normalize_subtitle(s.get("text") or "") for s in items).strip()
        if not text:
            return
        s_i = int(float(items[0]["start"]))
        e_i = int(max(float(items[-1]["end"]), float(items[0]["start"])))
        for piece in _splitter.split_text(text):
            if piece.strip():
                out.append((piece, {"start_sec": s_i, "end_sec": e_i}))

    def _flush() -> None:
        nonlocal cur, pending
        if not cur:
            return
        _emit_from(cur)
        if overlap > 0:
            cutoff = float(cur[-1]["end"]) - overlap
            pending = [
                s for s in cur
                if float(s["end"]) > cutoff and (s.get("text") or "").strip()
            ]
        else:
            pending = []
        cur = []

    for s in segs:
        text = normalize_subtitle((s.get("text") or "").strip())
        if not text:
            continue
        item = {"start": float(s["start"]), "end": float(s["end"]), "text": text}

        if not cur and pending:
            cur = list(pending)
            pending = []

        if cur:
            gap_hit = item["start"] - float(cur[-1]["end"]) >= gap
            dur_hit = item["start"] - float(cur[0]["start"]) >= max_dur
            last_t = cur[-1]["text"]
            sentence_hit = (
                item["start"] - float(cur[0]["start"]) >= max_dur * 0.6
                and last_t
                and last_t[-1] in _SENTENCE_END
            )
            if gap_hit or dur_hit or sentence_hit:
                _flush()
                if pending:
                    cur = list(pending)
                    pending = []

        cur.append(item)

    _flush()
    return out


def process_video(video_path: str, base_meta: dict[str, Any]) -> dict:
    """完整流程：抽音频 → 转写 → 分段 → 切片。
    返回 {"segments": [VideoSegment dict...], "chunks": [(text, meta)...]}。
    """
    audio = extract_audio(video_path)
    try:
        segs = transcribe(audio)
    finally:
        try:
            os.unlink(audio)
        except OSError:
            pass

    chunks = segments_to_chunks(segs)
    enriched = [(t, {**base_meta, **m}) for t, m in chunks]
    return {"segments": segs, "chunks": enriched}
