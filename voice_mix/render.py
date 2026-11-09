"""FFmpeg 渲染器（配音驱动版）。

两阶段、单次成片编码：
  A. 归一化片段 —— 视频裁 9:16 统一编码；图片做 Ken Burns 运镜（推/拉/平移）；
     按内容哈希缓存，跨条复用。
  B+C. 合成 —— xfade 交叉转场拼接（跨片段软过渡）+ acrossfade 原声溶解，
     再叠加配音/BGM/逐句字幕/响度统一，一次性编码，
     消除 concat -c copy 拼接的帧与音频时间误差累积（跳帧/跳音）。
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from .runtime import run_process
import time
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .assets import FFMPEG
from .config import JobConfig
from .planner import ClipSpec, Variant
from .tts import split_sentences


class RenderError(RuntimeError):
    pass


_CACHE_PUBLISH_LOCK = threading.Lock()
_PART_LOCKS = [threading.Lock() for _ in range(64)]


def esc_filter_path(p: str) -> str:
    s = str(p).replace("\\", "/")
    s = s.replace(":", r"\:")
    s = s.replace("'", r"\'")
    return s


def _run(cmd: List[str], timeout: int = 1800) -> Tuple[int, str, str]:
    proc = run_process(cmd, capture_output=True, timeout=timeout)
    return proc.returncode, proc.stdout.decode("utf-8", "ignore"), proc.stderr.decode("utf-8", "ignore")


def _encoder_args(cfg: JobConfig) -> List[str]:
    if cfg.encoder == "h264_mf":
        return ["-c:v", "h264_mf", "-b:v", "6M", "-profile:v", "high"]
    if cfg.encoder == "h264_amf":
        return ["-c:v", "h264_amf", "-quality", "speed", "-rc", "cqp", "-qp_i", "22", "-qp_p", "22"]
    args = ["-c:v", "libx264", "-preset", cfg.preset, "-crf", str(cfg.crf)]
    if cfg.threads > 0:
        args += ["-threads", str(cfg.threads)]
    return args


# ----------------------------------------------------------------------
# A. 归一化
# ----------------------------------------------------------------------
def _video_filter(cfg: JobConfig, clip: ClipSpec) -> str:
    W, H = cfg.width, cfg.height
    parts: List[str] = []
    if cfg.scale_mode == "blur":
        parts.append(
            f"split=2[bgsrc][fgsrc];"
            f"[bgsrc]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},gblur=sigma=18,eq=brightness=-0.06[bg];"
            f"[fgsrc]scale={W}:{H}:force_original_aspect_ratio=decrease[fgs]"
        )
        parts.append("[bg][fgs]overlay=(W-w)/2:(H-h)/2")
    elif cfg.scale_mode == "fit":
        parts.append(
            f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
    else:  # crop
        parts.append(f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}")
    if clip.mirror:
        parts.append("hflip")
    parts.append(f"setsar=1,fps={cfg.fps},format=yuv420p")
    return ",".join(parts)


def _image_filter(cfg: JobConfig, dur: float, motion: str = "in") -> str:
    """用居中铺满的画面展示图片，保持构图直到转场。"""
    return (
        f"scale={cfg.width}:{cfg.height}:force_original_aspect_ratio=increase,"
        f"crop={cfg.width}:{cfg.height},setsar=1,fps={cfg.fps},format=yuv420p"
    )


def _part_key(cfg: JobConfig, clip: ClipSpec, has_audio: bool, is_image: bool) -> str:
    try:
        stat = Path(clip.src).stat()
        mtime = f"{stat.st_mtime_ns}:{stat.st_size}"
    except OSError:
        mtime = "0"
    raw = "|".join([
        clip.src, mtime, f"{clip.start:.3f}", f"{clip.dur:.3f}",
        str(clip.mirror), str(has_audio), str(is_image),
        "center-v2" if is_image else "",
        f"{cfg.width}x{cfg.height}", str(cfg.fps), cfg.encoder, cfg.preset,
        str(cfg.crf), cfg.scale_mode,
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _resolve_image(src: str, cache_dir: Path) -> str:
    """HEIC/HEIF 苹果照片：ffmpeg 通常不支持，先经 pillow-heif 转成 JPEG（带缓存）。"""
    p = Path(src)
    if p.suffix.lower() not in {".heic", ".heif"}:
        return src
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / (hashlib.sha1(src.encode("utf-8")).hexdigest()[:20] + ".jpg")
    if out.exists() and out.stat().st_size > 1024:
        return str(out)
    import pillow_heif
    from PIL import Image, ImageOps
    pillow_heif.register_heif_opener()
    with Image.open(p) as im:
        im = ImageOps.exif_transpose(im)
        im.convert("RGB").save(out, "JPEG", quality=92)
    return str(out)


def normalize_clip(
    cfg: JobConfig, clip: ClipSpec, parts_dir: Path,
    has_audio: bool, is_image: bool, overwrite: bool = False,
) -> Path:
    key=_part_key(cfg,clip,has_audio,is_image)
    # Coalesce identical work requested by parallel variants without more RAM use.
    with _PART_LOCKS[int(key,16)%len(_PART_LOCKS)]:
        return _normalize_clip(cfg,clip,parts_dir,has_audio,is_image,overwrite)


def _normalize_clip(
    cfg: JobConfig, clip: ClipSpec, parts_dir: Path,
    has_audio: bool, is_image: bool, overwrite: bool = False,
) -> Path:
    parts_dir.mkdir(parents=True, exist_ok=True)
    key = _part_key(cfg, clip, has_audio, is_image)
    out = parts_dir / f"{key}.mp4"
    if out.exists() and out.stat().st_size > 1024 and not overwrite:
        return out

    tmp = out.with_name(f"{out.stem}.{uuid.uuid4().hex}.tmp.mp4")
    cmd: List[str] = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-filter_threads", "2"]

    # ---- 输入先全部声明（输出选项不能出现在第二个输入之前）----
    if is_image:
        cmd += ["-loop", "1", "-framerate", str(cfg.fps), "-i", _resolve_image(clip.src, parts_dir)]
    else:
        cmd += ["-ss", f"{clip.start:.3f}", "-t", f"{clip.dur:.3f}", "-i", clip.src]

    if is_image or not has_audio:
        cmd += ["-f", "lavfi", "-t", f"{clip.dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]

    # ---- 输出选项 ----
    if is_image:
        cmd += ["-vf", _image_filter(cfg, clip.dur, clip.motion)]
        cmd += ["-frames:v", str(max(1, int(round(clip.dur * cfg.fps))))]
    else:
        cmd += ["-vf", _video_filter(cfg, clip)]

    # ---- 映射 ----
    if is_image or not has_audio:
        cmd += ["-map", "0:v:0", "-map", "1:a:0", "-shortest"]
    else:
        cmd += ["-map", "0:v:0", "-map", "0:a:0"]
        cmd += ["-af", "aresample=48000"]

    cmd += _encoder_args(cfg)
    cmd += ["-c:a", "aac", "-b:a", cfg.audio_bitrate, "-ar", "48000", "-ac", "2"]
    cmd += ["-video_track_timescale", "90000", "-movflags", "+faststart", str(tmp)]

    code, _, err = _run(cmd)
    if code != 0 or not tmp.exists() or tmp.stat().st_size < 1024:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise RenderError(f"片段归一化失败: {clip.src}\n{err[-1500:]}")
    # A parallel render may already be decoding the published cache file.
    with _CACHE_PUBLISH_LOCK:
        if out.exists() and not overwrite:
            tmp.unlink()
        else:
            os.replace(tmp, out)
    return out


# ----------------------------------------------------------------------
# 字幕 / 标题滤镜
# ----------------------------------------------------------------------
def _fit_fontsize(cfg: JobConfig, size_ratio: float, text: str) -> int:
    """按实际字体宽度缩放，低清预览也遵守相同画面比例。"""
    from PIL import ImageFont
    size = max(1, int(cfg.height * size_ratio))
    font = ImageFont.truetype(cfg.sub_font, size)
    width = max((font.getlength(line) for line in text.splitlines()), default=1)
    return max(1, min(size, int(size * cfg.width * 0.86 / max(1, width))))


def _subtitle_text(cfg: JobConfig, text: str) -> str:
    from PIL import ImageFont
    text = " ".join(text.split())
    font = ImageFont.truetype(cfg.sub_font, max(1, int(cfg.height * cfg.sub_size_ratio)))
    if font.getlength(text) <= cfg.width * 0.86 or len(text) < 2:
        return text
    candidates = range(1, len(text))
    split = min(candidates, key=lambda i: (
        max(font.getlength(text[:i]), font.getlength(text[i:]))
        + (cfg.width * 0.06 if text[i] in "，。！？；、,.!?;" else 0)
    ))
    return text[:split].rstrip() + "\n" + text[split:].lstrip()


# 字幕纵向位置（画面高度比例）
SUB_POS_Y = {"top": 0.08, "middle": 0.50, "lower": 0.68, "bottom": 0.80}
SUB_COLOR_MAP = {"white": "white", "yellow": "#FFD54A", "black": "black", "cyan": "#62E8EF", "pink": "#FFA9CB", "green": "#C2F970"}


def _drawtext(
    font: str, text_path: Path, cfg: JobConfig,
    fontsize: int, top_ratio: float, color: str,
    enable: str = "",
) -> str:
    esc = esc_filter_path(text_path)
    base = (
        f"fontfile='{esc_filter_path(font)}':"
        f"textfile='{esc}':expansion=none:"
        f"x=(w-tw)/2:y={int(cfg.height * top_ratio)}:fontsize={fontsize}:fontcolor={color}"
    )
    if cfg.sub_style == "box":
        mask = {"black": "black", "white": "white", "navy": "#172844", "rose": "#7A2046"}.get(cfg.sub_box_color, "black")
        base += f":box=1:boxcolor={mask}@{max(0.0, min(1.0, cfg.sub_opacity)):.2f}:boxborderw={max(1, round(cfg.width * 16 / 1080))}"
    elif cfg.sub_style == "stroke":
        base += f":borderw={max(1, round(cfg.width * 5 / 1080))}:bordercolor=black@0.9"
    base += f":line_spacing={max(1, round(cfg.height * 10 / 1920))}"
    if enable:
        base += f":enable='{enable}'"
    return f"drawtext={base}"


def _write_text(dir_path: Path, name: str, text: str) -> Path:
    p = dir_path / name
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text.strip())
    return p


def _subtitle_chain(
    cfg: JobConfig, variant: Variant, text_dir: Path
) -> Tuple[str, List[Path]]:
    """逐句字幕：实测时间窗 + narration_delay 偏移，与语音严格对齐。"""
    files: List[Path] = []
    subs = [s for s in (variant.subs or []) if s.get("text", "").strip()]
    if not cfg.show_subs or not subs:
        return "", files

    pos_y = SUB_POS_Y.get(cfg.sub_pos, SUB_POS_Y["bottom"])
    color = SUB_COLOR_MAP.get(cfg.sub_color, "white")
    filters: List[str] = []
    for i, s in enumerate(subs):
        text = _subtitle_text(cfg, s["text"])
        tf = _write_text(text_dir, f"_sub_{variant.index:05d}_{i:02d}.txt", text)
        files.append(tf)
        st = s["start"] + cfg.narration_delay
        en = s["end"] + cfg.narration_delay
        enable = f"between(t,{st:.2f},{en:.2f})"
        fontsize = _fit_fontsize(cfg, cfg.sub_size_ratio, text)
        filters.append(_drawtext(cfg.sub_font, tf, cfg, fontsize, pos_y, color, enable))
    return ",".join(filters), files


def _title_filter(cfg: JobConfig, variant: Variant, text_dir: Path) -> Tuple[str, Optional[Path]]:
    if not cfg.show_title or not variant.title:
        return "", None
    tf = _write_text(text_dir, f"_title_{variant.index:05d}.txt", variant.title)
    end = cfg.title_duration if variant.title_end is None else variant.title_end
    enable = f"between(t,0,{end:.3f})"
    from dataclasses import replace
    fontsize = _fit_fontsize(replace(cfg, sub_font=cfg.title_font), cfg.title_size_ratio, variant.title)
    esc = esc_filter_path(tf)
    base = (
        f"fontfile='{esc_filter_path(cfg.title_font)}':"
        f"textfile='{esc}':expansion=none:"
        f"x=(w-tw)/2:y={int(cfg.height * cfg.title_top)}:fontsize={fontsize}:"
        f"fontcolor={cfg.title_color}:"
        f"box=1:boxcolor={cfg.title_box}:boxborderw={max(1, round(cfg.width * 14 / 1080))}:"
        f"enable='{enable}'"
    )
    return f"drawtext={base}", tf


def probe_video_duration(path: str) -> float:
    """ffprobe 读媒体时长（秒）。"""
    from .assets import FFPROBE
    try:
        out = run_process(
            [FFPROBE, "-v", "error", "-print_format", "json",
             "-show_format", str(path)],
            capture_output=True, timeout=60,
        )
        import json
        info = json.loads(out.stdout.decode("utf-8", "ignore"))
        return float(info.get("format", {}).get("duration") or 0.0)
    except Exception:  # noqa: BLE001
        return 0.0


# ----------------------------------------------------------------------
# B + C. 转场拼接 + 合成（单次编码，消除 copy 拼接的帧/音频误差累积）
# ----------------------------------------------------------------------
def render_variant(
    cfg: JobConfig,
    variant: Variant,
    out_path: Path,
    parts_dir: Path,
    asset_map: Dict[str, Tuple[bool, bool]],   # path -> (has_audio, is_image)
    overwrite: bool = False,
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists() and out_path.stat().st_size > 1024 and not overwrite:
        return out_path

    text_dir = parts_dir / "_texts" / uuid.uuid4().hex
    text_dir.mkdir(parents=True,exist_ok=True)

    # ---- A. 归一化片段（带缓存）----
    part_paths: List[Path] = []
    for c in variant.clips:
        has_audio, is_image = asset_map.get(c.src, (True, False))
        part_paths.append(normalize_clip(cfg, c, parts_dir, has_audio, is_image))

    n = len(part_paths)
    durs = [c.dur for c in variant.clips]
    if any(d <= 0.05 for d in durs):
        bad = [str(p) for p, d in zip(part_paths, durs) if d <= 0.05]
        raise RenderError(f"片段时长异常: {bad[:3]}")

    # 转场时长夹紧：不超过最短片段的 40%
    D = 0.0
    if n > 1:
        overlap = cfg.trans_dur if variant.overlap is None else variant.overlap
        D = min(overlap, 0.45 * min(durs))

    # ---- 输入 ----
    # 线程限制是关键：多路解码器默认各开满线程，1080p 下内存会爆
    # （表现为 "Could not open encoder before EOF" / EINVAL），必须压到 2。
    cmd: List[str] = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-filter_threads", "2", "-filter_complex_threads", "2",
    ]
    for p in part_paths:
        cmd += ["-threads", "2", "-i", str(p)]
    if not variant.narration or not Path(variant.narration).exists():
        raise RenderError(f"配音文件缺失: {variant.narration}")
    cmd += ["-threads", "2", "-i", str(variant.narration)]     # 输入 n
    nar_idx = n
    bgm_idx = -1
    if cfg.bgm_file and Path(cfg.bgm_file).exists():
        cmd += ["-stream_loop", "-1", "-threads", "2", "-i", str(cfg.bgm_file)]   # 平铺循环
        bgm_idx = n + 1

    fc: List[str] = []

    # ---- 视频：xfade 链 ----
    if n == 1:
        vsrc = "0:v"
    elif not D:
        fc.append("".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vcat]")
        vsrc = "vcat"
    else:
        prev = "0:v"
        cum = durs[0]
        for i in range(1, n):
            style = cfg.trans_style or "fade"
            if any(asset_map.get(variant.clips[j].src, (False, False))[1] for j in (i - 1, i)):
                if style not in {"fade", "smoothleft", "smoothright", "fadeblack"}:
                    style = "fade"
            off = max(0.0, cum - D)
            lab = f"vx{i}"
            fc.append(
                f"[{prev}][{i}:v]xfade=transition={style}:"
                f"duration={D:.3f}:offset={off:.3f}[{lab}]"
            )
            prev = lab
            cum = cum + durs[i] - D
        vsrc = prev

    # ---- 视频滤镜：字幕 + 标题 ----
    vf_parts: List[str] = []
    # Grade the picture before any subtitle or title is drawn.
    from .looks import grade
    vf_parts.append(grade(cfg.video_filter,cfg.filter_strength))
    sub_chain, _ = _subtitle_chain(cfg, variant, text_dir)
    if sub_chain:
        vf_parts.append(sub_chain)
    title_chain, _ = _title_filter(cfg, variant, text_dir)
    if title_chain:
        vf_parts.append(title_chain)
    # 末尾强制 format=yuv420p：xfade/drawtext 的格式协商会选出 yuv444p，
    # 普通播放器/浏览器无法解码（表现为打不开或色彩错乱）。
    vf_parts.extend(["tpad=stop_mode=clone:stop_duration=0.15", "format=yuv420p"])
    if vf_parts:
        fc.append(f"[{vsrc}]{','.join(vf_parts)}[vout]")
        vmap = "[vout]"
    else:
        vmap = f"[{vsrc}]" if n > 1 else "0:v"

    # ---- 音频：acrossfade 链（原声垫底，与画面转场同节奏）----
    gain = cfg.original_gain if cfg.keep_original else 0.0
    bed = ""
    if n == 1:
        bed = f"[0:a]volume={gain}[bed0]"
    elif not D:
        fc.append("".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[acat]")
        bed = f"[acat]volume={gain}[bed0]"
    else:
        prev_a = "0:a"
        for i in range(1, n):
            lab = f"ax{i}"
            fc.append(f"[{prev_a}][{i}:a]acrossfade=d={D:.3f}[{lab}]")
            prev_a = lab
        bed = f"[{prev_a}]volume={gain}[bed0]"
    delay = int(cfg.narration_delay * 1000)
    narration_filter = f"[{nar_idx}:a]aresample=48000,adelay={delay}|{delay}"
    duck = bgm_idx >= 0 and cfg.bgm_duck and cfg.bgm_gain > 0
    fc.append(bed)
    if duck:
        fc.append(narration_filter + ",asplit=2[nar][speech]")
    else:
        fc.append(narration_filter + "[nar]")
    fc.append("[bed0][nar]amix=inputs=2:duration=longest:normalize=0,apad[m1]")
    aout = "m1"
    if bgm_idx >= 0:
        fade = min(0.6, variant.total_dur / 3)
        fc.append(f"[{bgm_idx}:a]aresample=48000,volume={cfg.bgm_gain},"
                  f"afade=t=in:d={fade:.3f},afade=t=out:st={variant.total_dur - fade:.3f}:d={fade:.3f}[bg]")
        if duck:
            fc.append("[speech]apad[sidechain]")
            fc.append("[bg][sidechain]sidechaincompress=threshold=0.025:ratio=8:attack=18:release=350[ducked]")
        bg = "ducked" if duck else "bg"
        fc.append(f"[m1][{bg}]amix=inputs=2:duration=first:normalize=0[m2]")
        aout = "m2"
    if cfg.loudnorm and variant.total_dur >= 3.0:
        fc.append(f"[{aout}]loudnorm=I=-16:TP=-1.5:LRA=11[afinal]")
        aout = "afinal"

    cmd += ["-filter_complex", ";".join(fc)]
    cmd += ["-map", vmap, "-map", f"[{aout}]"]
    cmd += _encoder_args(cfg)
    cmd += ["-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "aac", "-b:a", cfg.audio_bitrate, "-ar", "48000", "-ac", "2"]
    cmd += ["-movflags", "+faststart", "-t", str(variant.total_dur), "-r", str(cfg.fps), str(out_path)]

    code, _, err = _run(cmd, timeout=3600)
    if code != 0 or not out_path.exists() or out_path.stat().st_size < 1024:
        try:
            if out_path.exists():
                out_path.unlink()
        except OSError:
            pass
        raise RenderError(f"合成失败: variant {variant.index}\n{err[-2500:]}")
    return out_path


# ----------------------------------------------------------------------
# 封面
# ----------------------------------------------------------------------
def _avg_luminance(path: Path) -> float:
    """图片平均亮度（0~255），用于避开黑场帧。"""
    try:
        from PIL import Image
        with Image.open(path).convert("L").resize((32, 56)) as im:
            pixels = list(im.getdata())
            return sum(pixels) / max(1, len(pixels))
    except Exception:  # noqa: BLE001
        return 0.0


def render_cover(
    cfg: JobConfig,
    variant: Variant,
    video_path: Path,
    covers_dir: Path,
    frame_time: Optional[float] = None,
) -> Optional[Path]:
    """从成片抽帧（选在字幕空档处，画面干净）+ 模板样式生成封面 jpg。"""
    tpl = cfg.cover_template
    if tpl in ("none", ""):
        return None
    covers_dir.mkdir(parents=True, exist_ok=True)
    out = covers_dir / f"cover_{variant.index:05d}.jpg"
    sentences = split_sentences(cfg.script)
    fallback_title = sentences[0].text if sentences else ""
    title = (cfg.cover_title.strip() or variant.title or fallback_title).strip()
    subtitle = ""
    if variant.subs:
        # 取第二句作封面副文案（第一句通常就是标题）
        rest = [s["text"] for s in variant.subs
                if s["text"].strip("。！？，,.；; ") != title.strip("。！？，,.；; ")]
        if rest:
            subtitle = rest[0]

    # 候选抽帧时刻：字幕空档 + 字幕句尾后沿（画面无字幕、无标题）
    # 字幕窗口与成片时间轴一致（+ narration_delay 偏移）
    delay = cfg.narration_delay
    subs = sorted(
        ({"text": s["text"], "start": s["start"] + delay, "end": s["end"] + delay}
         for s in (variant.subs or [])),
        key=lambda s: s["start"],
    )
    cands: List[float] = []
    if cfg.show_title and variant.title:
        cands.append((cfg.title_duration if variant.title_end is None else variant.title_end) + 0.15)
    for i in range(len(subs)):
        if i > 0:
            cands.append((subs[i - 1]["end"] + subs[i]["start"]) / 2)   # 句间空档中点
        cands.append(subs[i]["end"] + 0.08)                              # 句尾刚结束
    if not cands:
        cands = [min(cfg.cover_time, max(0.3, variant.total_dur * 0.4))]

    def _clean(t: float) -> bool:
        """时刻必须不在任何字幕窗口和标题窗口内。"""
        title_end = cfg.title_duration if variant.title_end is None else variant.title_end
        if cfg.show_title and variant.title and t <= title_end + 0.06:
            return False
        for s in subs:
            if s["start"] - 0.06 <= t <= s["end"] + 0.06:
                return False
        return True

    cands = [c for c in cands if 0.1 <= c <= variant.total_dur - 0.15 and _clean(c)]
    if not cands:
        cands = [max(0.1, variant.total_dur * 0.4)]
    cands = [frame_time] if frame_time is not None else sorted(set(round(c, 2) for c in cands))

    # 逐个抽帧，挑最亮的一张（避开黑场/渐入）
    best_path: Optional[Path] = None
    best_lum = -1.0
    for j, t in enumerate(cands[:6]):
        cand = covers_dir / f"_frame_{variant.index:05d}_{j}.jpg"
        code, _, _ = _run([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{t:.2f}", "-i", str(video_path), "-frames:v", "1",
            "-q:v", "2", str(cand),
        ])
        if code != 0 or not cand.exists():
            continue
        lum = _avg_luminance(cand)
        if lum > best_lum:
            best_lum = lum
            best_path = cand
    if best_path is None:
        return None
    tmp_frame = best_path

    filters: List[str] = []
    W, H = cfg.width, cfg.height

    def _dt(text: str, fontsize: int, y_px: int, color: str,
            border: bool = False, box_color: str = "") -> str:
        tfp = covers_dir / f"_ct_{variant.index:05d}_{abs(hash(text)) % 99999}.txt"
        with open(tfp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        esc = esc_filter_path(tfp)
        s = (
            f"fontfile='{esc_filter_path(cfg.title_font)}':textfile='{esc}':expansion=none:"
            f"x=(w-tw)/2:y={y_px}:fontsize={fontsize}:fontcolor={color}"
        )
        if border:
            s += ":borderw=6:bordercolor=black@0.9"
        if box_color:
            s += f":box=1:boxcolor={box_color}:boxborderw=22"
        return f"drawtext={s}"

    if tpl == "poster":
        filters.append(f"drawbox=x=0:y=0:w={W}:h={H}:color=black@0.28:t=fill")
        fs = max(56, int(H * 0.105))
        title_y = int(H * 0.42)
        if title:
            fit = int(W * 0.88 / max(1, len(title)))
            fs = max(40, min(fs, fit))
            filters.append(_dt(title, fs, title_y, "#FFD54A", border=True))
        if subtitle:
            sfs = max(30, min(int(H * 0.038), int(W * 0.86 / max(1, len(subtitle)))))
            sub_y = title_y + int(fs * 1.4) if title else title_y
            filters.append(_dt(subtitle, sfs, sub_y, "white", border=True))
    elif tpl == "banner":
        band_y = int(H * 0.74)
        band_h = int(H * 0.15)
        filters.append(f"drawbox=x=0:y={band_y}:w={W}:h={band_h}:color=white@0.93:t=fill")
        if title:
            fs = max(40, min(int(H * 0.062), int(W * 0.9 / max(1, len(title)))))
            filters.append(_dt(title, fs, band_y + int(band_h * 0.5 - fs * 0.62), "black"))
    elif tpl == "card":
        card_h = int(H * 0.24)
        card_y = int(H * 0.5 - card_h / 2)
        filters.append(f"drawbox=x={int(W * 0.08)}:y={card_y}:"
                       f"w={int(W * 0.84)}:h={card_h}:color=white@0.88:t=fill")
        if title:
            fs = max(40, min(int(H * 0.06), int(W * 0.8 / max(1, len(title)))))
            filters.append(_dt(title, fs, card_y + int(card_h * 0.28), "#1f2430"))
        if subtitle:
            sfs = max(26, min(int(H * 0.032), int(W * 0.78 / max(1, len(subtitle)))))
            filters.append(_dt(subtitle, sfs, card_y + int(card_h * 0.62), "#444a58"))
    # clean: 不加任何字

    if filters:
        vf = ",".join(filters)
        code, _, err = _run([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(tmp_frame), "-vf", vf,
            "-frames:v", "1", "-q:v", "2", str(out),
        ])
        if code != 0:
            for c in covers_dir.glob(f"_frame_{variant.index:05d}_*.jpg"):
                try:
                    c.unlink()
                except OSError:
                    pass
            return None
    else:
        import shutil
        shutil.copyfile(tmp_frame, out)
    for c in covers_dir.glob(f"_frame_{variant.index:05d}*.jpg"):
        try:
            c.unlink()
        except OSError:
            pass
    return out if out.exists() else None


# ----------------------------------------------------------------------
# 批量
# ----------------------------------------------------------------------
def render_batch(
    cfg: JobConfig,
    variants: Sequence[Variant],
    out_dir: Path,
    parts_dir: Path,
    asset_map: Dict[str, Tuple[bool, bool]],
    jobs: int = 4,
    overwrite: bool = False,
    progress=None,
    max_retries: int = 2,
) -> List[Dict]:
    results: List[Dict] = []
    total = len(variants)

    def job(v: Variant, retry: int = 0) -> Dict:
        out = out_dir / f"video_{v.index:05d}.mp4"
        t0 = time.perf_counter()
        try:
            render_variant(cfg, v, out, parts_dir, asset_map, overwrite=overwrite)
            ok, err = True, ""
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            transient = any(k in msg for k in (
                "malloc", "Cannot allocate", "Out of memory", "ENOMEM",
                "Killed", "std::bad_alloc",
                "Could not open encoder", "Cannot allocate memory",
            ))
            if transient and retry < max_retries:
                time.sleep(3 * (retry + 1))
                return job(v, retry + 1)
            ok, err = False, msg
        dt = time.perf_counter() - t0
        size = out.stat().st_size if out.exists() else 0
        return {
            "index": v.index, "ok": ok, "error": err, "path": str(out),
            "size_mb": round(size / 1048576, 2), "seconds": round(dt, 1),
            "duration": round(v.total_dur, 2),
        }

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        futs = {ex.submit(job, v): v for v in variants}
        done = 0
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            done += 1
            if progress:
                progress(done, total, r)
    results.sort(key=lambda r: r["index"])
    return results
