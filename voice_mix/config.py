"""任务配置：一次表单，一条任务。"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List
from .runtime import default_font


TEMPLATES: Dict[str, Dict[str, Any]] = {
    # 模板名 → 渲染行为
    "standard": {
        "label": "带货标准版（顶部标题+逐句大字幕）",
        "title": True,
        "subs": True,
    },
    "subs_only": {
        "label": "逐句字幕版（无标题）",
        "title": False,
        "subs": True,
    },
    "clean": {
        "label": "纯净混剪版（无字幕）",
        "title": False,
        "subs": False,
    },
    "fast": {
        "label": "卡点快剪版（快节奏+逐句字幕）",
        "title": False,
        "subs": True,
        "pace": "fast",
    },
}

COVER_TEMPLATES: Dict[str, str] = {
    "poster": "爆款大字报（压暗+大黄字居中）",
    "banner": "底部白条（白底黑字横幅）",
    "card": "中央白卡（半透明白卡+黑字）",
    "clean": "原图封面（不写字）",
    "none": "不要封面",
}

SUB_COLORS: Dict[str, str] = {"white": "白色", "yellow": "黄色", "black": "黑色", "cyan": "青色", "pink": "粉色", "green": "绿色"}
SUB_POSITIONS: Dict[str, str] = {"bottom": "底部", "lower": "中下", "middle": "居中", "top": "顶部"}


@dataclass
class JobConfig:
    """一次生成任务的全部参数。"""

    # ---- 内容 ----
    script: str = ""                       # 文案（配音 + 字幕来源）
    title: str = ""                        # 自定义标题；空 = 取文案第一句
    voice: str = "zh-CN-XiaoxiaoNeural"    # edge-tts 音色
    rate: str = "+0%"                      # 语速 -50% ~ +50%
    voice_vary: bool = False               # 每条视频随机换音色（增加差异化）
    pause_style: str = "natural"
    sentence_cuts: bool = True

    # ---- 结构 ----
    count: int = 5                         # 生成条数
    duration_mode: str = "auto"            # auto=跟随语音 | 数字字符串=目标秒数
    template: str = "standard"             # 模板，见 TEMPLATES

    # ---- 素材 / 输出 ----
    src_dir: str = ""                      # 素材文件夹
    out_dir: str = ""                      # 输出文件夹
    img_display: float = 3.0               # 单张图片默认展示秒数

    # ---- 音频 ----
    keep_original: bool = True             # 保留素材原声（低音量垫底）
    original_gain: float = 0.30
    bgm_file: str = ""                     # BGM 音频文件路径（空 = 不加，自动平铺循环）
    bgm_duck: bool = False
    bgm_gain: float = 0.25                 # BGM 音量 0~1
    narration_delay: float = 0.2           # 配音起始延迟（秒）

    video_filter: str = "none"
    filter_strength: float = 0.7

    # ---- 画面 ----
    width: int = 1080
    height: int = 1920
    fps: int = 30
    scale_mode: str = "crop"               # crop | blur | fit
    mirror_prob: float = 0.0               # 默认保留素材中的文字和人物方向
    img_dur: float = 3.0                   # 单张图片展示时长（秒）
    trans_dur: float = 0.5                 # 片段交叉转场时长（秒，0 = 硬切）
    trans_style: str = "fade"              # fade | slideleft | circleopen | wipeleft | fadeblack

    # ---- 字幕样式 ----
    sub_font: str = field(default_factory=default_font)
    sub_size_ratio: float = 0.042          # 字幕字号 = 高 * 比例
    sub_style: str = "box"                 # box=蒙版底 | stroke=描边 | none=无
    sub_box_color: str = "black"
    sub_opacity: float = 0.45              # 蒙版浓度 0~1（仅 box 样式）
    sub_color: str = "white"               # white | yellow | black
    sub_pos: str = "bottom"                # top | middle | lower | bottom
    title_size_ratio: float = 0.05
    title_top: float = 0.10
    title_color: str = "white"
    title_box: str = "black@0.5"
    title_duration: float = 2.5
    title_font: str = field(default_factory=default_font)

    # ---- 封面 ----
    cover_template: str = "poster"         # none | poster | banner | card | clean
    cover_title: str = ""                  # 封面标题（空 = 用视频标题）
    cover_time: float = 0.8                # 封面取帧时间点（秒）

    # ---- 去重 ----
    allow_reuse: bool = True
    reuse_fallback: bool = False
    dedup: bool = True
    max_reuse: int = 3

    # ---- 编码 ----
    encoder: str = "libx264"
    preset: str = "veryfast"
    crf: int = 16
    audio_bitrate: str = "320k"
    threads: int = 4
    loudnorm: bool = True

    seed: int = field(default_factory=lambda: random.randint(1, 10**9))
    min_asset_dur: float = 1.0
    max_asset_dur: float = 300.0

    # ------------------------------------------------------------------
    def target_duration(self, narration_dur: float) -> float:
        """根据配音时长和用户选择的时长模式，算出成片目标时长。"""
        if self.duration_mode == "auto":
            return round(narration_dur + self.narration_delay, 2)
        try:
            t = float(self.duration_mode)
        except ValueError:
            return round(narration_dur + self.narration_delay, 2)
        # 成片至少要覆盖配音
        return round(max(t, narration_dur + self.narration_delay), 2) if math.isfinite(t) else narration_dur + self.narration_delay

    @property
    def pace(self) -> str:
        return TEMPLATES.get(self.template, {}).get("pace", "normal")

    @property
    def show_title(self) -> bool:
        return bool(TEMPLATES.get(self.template, {}).get("title", False))

    @property
    def show_subs(self) -> bool:
        return bool(TEMPLATES.get(self.template, {}).get("subs", False))

    def validate(self) -> List[str]:
        errs: List[str] = []
        from .assets import FFMPEG, FFPROBE
        if not FFMPEG or not FFPROBE:
            errs.append("请先安装 FFmpeg 和 ffprobe，或在桌面版选择工具目录后重启")
        if (self.show_subs and not Path(self.sub_font).is_file()) or (self.show_title and not Path(self.title_font).is_file()):
            errs.append("所选字体不可用，请重新选择本机字体")
        if self.pause_style not in {"natural", "compact", "calm"}:
            errs.append("请选择有效的配音停顿风格")
        if not self.script.strip():
            errs.append("文案不能为空")
        if not self.src_dir or not Path(self.src_dir).exists():
            errs.append(f"素材路径不存在: {self.src_dir}")
        if not self.out_dir:
            errs.append("输出文件夹未指定")
        if self.count < 1 or self.count > 200:
            errs.append("生成条数需在 1~200 之间")
        if not (0 <= self.trans_dur <= 1):
            errs.append("转场时长需在 0~1 秒之间")
        if not (1 <= self.img_dur <= 30):
            errs.append("单图时长需在 1~30 秒之间")
        if not (0 <= self.narration_delay <= 10):
            errs.append("配音延迟需在 0~10 秒之间")
        if self.bgm_file and not Path(self.bgm_file).is_file():
            errs.append("选中的配乐文件不存在")
        if self.video_filter not in {"none", "clear", "warm", "cool", "soft", "mono"}:
            errs.append("请选择有效的视频滤镜")
        if not isinstance(self.filter_strength, (int, float)) or not 0 <= self.filter_strength <= 1:
            errs.append("滤镜强度需在 0~1 之间")
        return errs

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def save(self, path: str) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "JobConfig":
        cfg = cls()
        for k, v in raw.items():
            if k in cls.__dataclass_fields__:
                setattr(cfg, k, v)
        return cfg
