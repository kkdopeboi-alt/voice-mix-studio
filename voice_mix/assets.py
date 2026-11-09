"""素材扫描：视频 + 图片（含 iPhone HEIC）统一变成结构化素材池。"""

from __future__ import annotations

import json
import subprocess
from .runtime import run_process
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from .runtime import settings

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".flv", ".webm", ".m4v", ".ts", ".wmv"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".heif"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma"}

_FFMPEG_CANDIDATES = [
    r"D:\ffmpeg\win\bin",
    r"C:\ffmpeg\bin",
    r"C:\Program Files\ffmpeg\bin",
    r"D:\ffmpeg\bin",
]


def _which(name: str) -> Optional[str]:
    from shutil import which
    import os
    import sys

    custom = os.environ.get("VOICE_MIX_FFMPEG_DIR") or settings().get("ffmpeg_dir")
    extension = ".exe" if sys.platform == "win32" else ""
    for base in ([custom] if custom else []) + ["/opt/homebrew/bin", "/usr/local/bin"]:
        candidate = Path(base) / (name + extension)
        if candidate.is_file():
            return str(candidate)

    found = which(name)
    if found:
        return found
    for base in _FFMPEG_CANDIDATES:
        cand = Path(base) / f"{name}.exe"
        if cand.exists():
            return str(cand)
    return None


FFMPEG = _which("ffmpeg")
FFPROBE = _which("ffprobe")


@dataclass
class Asset:
    """一条素材（视频或图片）。"""

    path: str
    duration: float          # 图片 = 建议展示时长
    width: int
    height: int
    fps: float
    has_audio: bool
    size: int
    group: str               # 所在子目录（相对素材根）
    name: str
    is_image: bool = False

    @property
    def is_portrait(self) -> bool:
        return self.height >= self.width

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["is_portrait"] = self.is_portrait
        return d


def probe(path: str) -> Optional[Dict]:
    if not FFPROBE:
        raise RuntimeError("找不到 ffprobe，请确认 D:\\ffmpeg\\win\\bin 存在")
    cmd = [
        FFPROBE, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", path,
    ]
    try:
        out = run_process(cmd, capture_output=True, timeout=90)
    except subprocess.TimeoutExpired:
        return None
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout.decode("utf-8", "ignore"))
    except json.JSONDecodeError:
        return None


def _parse_fps(stream: Dict) -> float:
    raw = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1"
    try:
        num, den = raw.split("/")
        den_f = float(den)
        return float(num) / den_f if den_f else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0


def _image_size(path: Path) -> Optional[tuple]:
    """读图片尺寸；HEIC 用 pillow-heif 解码。"""
    try:
        from PIL import Image
        if path.suffix.lower() in {".heic", ".heif"}:
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except ImportError:
                return None
        with Image.open(path) as im:
            # iPhone HEIC 常带 EXIF 方向
            try:
                from PIL import ImageOps
                im = ImageOps.exif_transpose(im)
            except Exception:  # noqa: BLE001
                pass
            return im.size
    except Exception:  # noqa: BLE001
        return None


def scan(
    root: str,
    recursive: bool = True,
    min_dur: float = 1.0,
    max_dur: float = 300.0,
    img_display: float = 3.0,
    progress=None,
) -> List[Asset]:
    """递归扫描文件夹，返回可用素材（视频+图片）列表。"""
    root_path = Path(root).resolve()
    if not root_path.exists():
        raise FileNotFoundError(f"素材文件夹不存在: {root_path}")

    all_exts = VIDEO_EXTS | IMAGE_EXTS
    files = [
        p for p in root_path.rglob("*")
        if p.is_file() and p.suffix.lower() in all_exts
    ] if recursive or root_path.is_file() else [
        p for p in root_path.iterdir() if p.is_file() and p.suffix.lower() in all_exts
    ]
    if root_path.is_file():
        files = [root_path] if root_path.suffix.lower() in all_exts else []
    files.sort()

    assets: List[Asset] = []
    for i, p in enumerate(files):
        if progress:
            progress(i + 1, len(files), p.name)
        ext = p.suffix.lower()
        try:
            rel = p.parent.relative_to(root_path)
            group = str(rel).replace("\\", "/")
            if group == ".":
                group = ""
        except ValueError:
            group = p.parent.name

        if ext in IMAGE_EXTS:
            size = _image_size(p)
            if not size or size[0] < 200 or size[1] < 200:
                continue
            assets.append(Asset(
                path=str(p), duration=img_display,
                width=size[0], height=size[1], fps=0.0,
                has_audio=False, size=p.stat().st_size,
                group=group, name=p.name, is_image=True,
            ))
            continue

        info = probe(str(p))
        if not info:
            continue
        fmt = info.get("format", {})
        streams = info.get("streams", [])
        v = next((s for s in streams if s.get("codec_type") == "video"), None)
        a = next((s for s in streams if s.get("codec_type") == "audio"), None)
        if v is None:
            continue
        dur = float(fmt.get("duration") or v.get("duration") or 0.0)
        if dur < min_dur or dur > max_dur:
            continue
        assets.append(Asset(
            path=str(p), duration=dur,
            width=int(v.get("width") or 0), height=int(v.get("height") or 0),
            fps=_parse_fps(v), has_audio=a is not None,
            size=int(fmt.get("size") or p.stat().st_size),
            group=group, name=p.name,
        ))
    return assets


def group_by(assets: Iterable[Asset]) -> Dict[str, List[Asset]]:
    out: Dict[str, List[Asset]] = {}
    for a in assets:
        out.setdefault(a.group, []).append(a)
    return out


def scan_audio(root: str, recursive: bool = True) -> List[str]:
    root_path = Path(root).resolve()
    if not root_path.exists():
        return []
    files = [p for p in root_path.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTS]
    return sorted(str(p) for p in files)
