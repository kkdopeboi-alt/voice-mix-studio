"""Platform paths shared by the desktop app, API and renderer."""
from __future__ import annotations

import json
import os
import sys
import subprocess
from pathlib import Path

VERSION = "1.5.0"
PACKAGE_DIR = Path(__file__).resolve().parent


def run_process(*args, **kwargs):
    if sys.platform == "win32":
        kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
    return subprocess.run(*args, **kwargs)


def user_data_dir() -> Path:
    override = os.environ.get("VOICE_MIX_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "VoiceMix"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/VoiceMix"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "voice-mix"


# Keep existing development projects compatible. Frozen applications use a writable
# location outside the installation and never modify their signed application bundle.
DATA_DIR = user_data_dir() if getattr(sys, "frozen", False) else Path(os.environ.get("VOICE_MIX_DATA_DIR", PACKAGE_DIR))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def settings() -> dict:
    try:
        return json.loads((user_data_dir() / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def default_output() -> str:
    if os.environ.get('VOICE_MIX_OUTPUT_DIR'):
        return os.environ['VOICE_MIX_OUTPUT_DIR']
    return str(Path.home() / "Movies/VoiceMix" if sys.platform == "darwin" else Path.home() / "Videos/VoiceMix")


def font_candidates():
    candidates = [
        ("C:/Windows/Fonts/msyhbd.ttc", "微软雅黑 · 粗体"),
        ("C:/Windows/Fonts/msyh.ttc", "微软雅黑"),
        ("C:/Windows/Fonts/simhei.ttf", "黑体"),
        ("C:/Windows/Fonts/simkai.ttf", "楷体"),
        ("C:/Windows/Fonts/simfang.ttf", "仿宋"),
        ("C:/Windows/Fonts/Dengb.ttf", "等线 · 粗体"),
        ("C:/Windows/Fonts/Deng.ttf", "等线"),
        ("C:/Windows/Fonts/STZHONGS.TTF", "华文中宋"),
        ("C:/Windows/Fonts/STKAITI.TTF", "华文楷体"),
        ("/System/Library/Fonts/PingFang.ttc", "苹方"),
        ("/System/Library/Fonts/STHeiti Medium.ttc", "黑体"),
        ("/System/Library/Fonts/Supplemental/Songti.ttc", "宋体"),
        ("/System/Library/Fonts/Supplemental/Arial.ttf", "Arial"),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "Noto Sans CJK"),
    ]
    return [(path, label) for path, label in candidates if Path(path).is_file()]


def default_font() -> str:
    candidates = font_candidates()
    return candidates[0][0] if candidates else ""
