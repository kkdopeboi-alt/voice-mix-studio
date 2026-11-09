"""TTS 语音合成（edge-tts，免 API key）+ 文案句子切分。"""

from __future__ import annotations

import asyncio
import re
import uuid
import subprocess
from .runtime import run_process
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .assets import FFPROBE

# 预置音色（中国香港 / 中国台湾为微软官方区域音色）
VOICE_LIST: List[Tuple[str, str]] = [
    ("zh-CN-XiaoxiaoNeural", "晓晓 · 女 · 温柔（推荐带货）"),
    ("zh-CN-XiaoyiNeural", "晓伊 · 女 · 活泼"),
    ("zh-CN-XiaomoNeural", "晓墨 · 女 · 沉稳"),
    ("zh-CN-XiaoxuanNeural", "晓萱 · 女 · 知性"),
    ("zh-CN-YunxiNeural", "云希 · 男 · 阳光年轻"),
    ("zh-CN-YunjianNeural", "云健 · 男 · 磁性解说"),
    ("zh-CN-YunyangNeural", "云扬 · 男 · 专业播音"),
    ("zh-CN-YunxiaNeural", "云夏 · 男 · 少年"),
    ("zh-CN-liaoning-XiaobeiNeural", "晓北 · 女 · 东北味"),
    ("zh-CN-shaanxi-XiaoniNeural", "晓妮 · 女 · 陕西味"),
    ("zh-HK-HiuMaanNeural", "曉曼 · 女 · 中国香港粤语"),
    ("zh-HK-WanLungNeural", "雲龍 · 男 · 中国香港粤语"),
    ("zh-TW-HsiaoChenNeural", "曉臻 · 女 · 中国台湾国语"),
]

_VOICES = {v: label for v, label in VOICE_LIST}


def voice_label(voice: str) -> str:
    return _VOICES.get(voice, voice)


@dataclass
class Sentence:
    """一句字幕 / 一段配音节奏单元。"""

    text: str
    chars: int


_PUNCT_SPLIT = re.compile(r"(?<=[。！？!?；;\n])")
_SOFT_SPLIT = re.compile(r"(?<=[，,、])")


def split_sentences(script: str, max_chars: int = 26) -> List[Sentence]:
    """把文案切成字幕句。

    按句号/问号/感叹号/分号/换行切分；单句超长再按逗号二次切分。
    每句限制在 max_chars 内，保证字幕一屏放得下。
    """
    script = script.strip().replace("\r\n", "\n").replace("\r", "\n")
    if not script:
        return []

    rough: List[str] = []
    for seg in _PUNCT_SPLIT.split(script):
        seg = seg.strip()
        if not seg:
            continue
        # 保留句尾标点
        if len(seg) <= max_chars:
            rough.append(seg)
        else:
            # 二次切分：按逗号聚合成 <=max_chars 的块
            parts = [p for p in _SOFT_SPLIT.split(seg) if p.strip()]
            buf = ""
            for p in parts:
                if buf and len(buf) + len(p) > max_chars:
                    rough.append(buf)
                    buf = p.strip()
                else:
                    buf += p
            if buf.strip():
                rough.append(buf.strip())

    # 太短的碎句并入前一句
    merged: List[Sentence] = []
    for s in rough:
        s = s.strip()
        if not s:
            continue
        if merged and len(s) < 4:
            merged[-1].text += s
            merged[-1].chars = len(merged[-1].text)
        else:
            merged.append(Sentence(text=s, chars=len(s)))
    return merged


def probe_audio_duration(path: str) -> float:
    """ffprobe 读音频时长（秒）。"""
    if not FFPROBE:
        raise RuntimeError("找不到 ffprobe")
    out = run_process(
        [FFPROBE, "-v", "error", "-print_format", "json",
         "-show_format", str(path)],
        capture_output=True, timeout=60,
    )
    if out.returncode != 0:
        return 0.0
    import json
    try:
        info = json.loads(out.stdout.decode("utf-8", "ignore"))
        return float(info.get("format", {}).get("duration") or 0.0)
    except Exception:  # noqa: BLE001
        return 0.0


def synth(
    text: str,
    voice: str,
    out_path: str,
    rate: str = "+0%",
    volume: str = "+0%",
    timeout: int = 120,
) -> float:
    """合成一段配音，返回音频时长（秒）。阻塞调用。"""
    text = text.strip()
    if not text:
        raise ValueError("配音文本为空")

    async def _run() -> None:
        import edge_tts
        comm = edge_tts.Communicate(text, voice=voice, rate=rate, volume=volume)
        await asyncio.wait_for(comm.save(str(tmp)), timeout=timeout)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    out = Path(out_path)
    tmp = out.with_name(f"{out.stem}.{uuid.uuid4().hex}.tmp.mp3")
    try:
        asyncio.run(_run())
        if not tmp.exists() or tmp.stat().st_size < 512:
            raise RuntimeError(f"TTS 合成失败: {out_path}")
        tmp.replace(out)
    finally:
        tmp.unlink(missing_ok=True)
    return probe_audio_duration(str(out))


def _ffmpeg_path() -> Optional[str]:
    from .assets import FFMPEG
    if not FFMPEG:
        raise RuntimeError("找不到 ffmpeg")
    return FFMPEG


def _to_wav(src: str, dst: str) -> None:
    run_process(
        [_ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
         "-i", src, "-ar", "48000", "-ac", "2", dst],
        capture_output=True, timeout=120, check=True,
    )


def _silence_wav(dst: str, dur: float) -> None:
    run_process(
        [_ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
         "-c:a", "pcm_s16le", dst],
        capture_output=True, timeout=60, check=True,
    )


def synth_narration(
    sentences: List[Sentence],
    voice: str,
    out_path: str,
    rate: str = "+0%",
    lead: float = 0.2,
    work_dir: Optional[str] = None,
    pause_style: str = "natural",
) -> Tuple[List[Dict], float]:
    """逐句合成配音并精确计时，拼接成整条旁白。

    返回 (subs, total_dur)：
      subs = [{"text": 句, "start": 开始秒, "end": 结束秒}, ...]（绝对时间轴）
    每句时长实测，字幕与语音严格对齐，不再按字数估算漂移。
    """
    if not sentences:
        raise ValueError("文案切分结果为空")

    work = Path(work_dir) if work_dir else Path(out_path).parent / "_sent"
    work.mkdir(parents=True, exist_ok=True)

    pieces: List[str] = []
    subs: List[Dict] = []
    t = lead

    lead_sil = str(work / "lead.wav")
    _silence_wav(lead_sil, lead)
    pieces.append(lead_sil)

    for i, s in enumerate(sentences):
        mp3 = work / f"s_{i:03d}.mp3"
        synth(s.text, voice, str(mp3), rate=rate)
        wav = work / f"s_{i:03d}.wav"
        _to_wav(str(mp3), str(wav))
        dur = probe_audio_duration(str(wav))
        if dur <= 0:
            raise RuntimeError(f"句子配音时长异常: {s.text[:20]}")
        subs.append({"text": s.text, "start": round(t, 3), "end": round(t + dur, 3)})
        t += dur
        pieces.append(str(wav))

        # 句间停顿：句号/问号/感叹号后长停顿，逗号结尾短停顿
        ends_hard = bool(s.text and s.text[-1] in "。！？!?；;")
        gap = 0.25 if ends_hard else 0.12
        if s.text.endswith(("？", "?")):
            gap = 0.36
        gap *= {"natural": 1.0, "compact": 0.65, "calm": 1.5}[pause_style]
        if i == len(sentences) - 1:
            gap = max(gap, 0.45)
        gap_wav = str(work / f"g_{i:03d}.wav")
        _silence_wav(gap_wav, gap)
        pieces.append(gap_wav)
        t += gap

    # 拼接 → 整条旁白 wav → 压成 mp3
    lst = work / "concat.txt"
    with open(lst, "w", encoding="utf-8", newline="\n") as f:
        for p in pieces:
            safe = str(p).replace("'", r"'\''")
            f.write(f"file '{safe}'\n")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    joined_wav = out.with_suffix(".wav")
    run_process(
        [_ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined_wav)],
        capture_output=True, timeout=300, check=True,
    )
    run_process(
        [_ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(joined_wav), "-c:a", "libmp3lame", "-b:a", "128k", str(out)],
        capture_output=True, timeout=300, check=True,
    )
    try:
        joined_wav.unlink()
    except OSError:
        pass

    total = probe_audio_duration(str(out))
    return subs, total
