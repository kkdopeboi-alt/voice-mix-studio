"""配音驱动的混剪方案生成。

与随机槽位混剪不同：这里每条成片的时长由「配音时长/目标时长」决定，
片段按节奏铺满整条时间轴，配音与画面天然对齐。
核心仍是跨变体去重：N 条视频要真的不一样。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .assets import Asset
from .config import JobConfig


@dataclass
class ClipSpec:
    """一个片段的最终规格。"""

    src: str
    start: float              # 素材内入点（图片恒为 0）
    dur: float                # 截取时长（= 时间轴时长，speed 恒为 1 保证对齐配音）
    mirror: bool = False
    slot: str = "body"
    index: int = 0
    motion: str = "in"        # 图片运镜：in | out | left | right（视频无效）

    @property
    def key(self) -> Tuple[str, float, float]:
        return (self.src, round(self.start, 2), round(self.dur, 2))


@dataclass
class Variant:
    """一条成片的完整方案。"""

    index: int
    clips: List[ClipSpec]
    narration: str = ""            # 该条使用的配音音频路径
    narration_dur: float = 0.0
    voice: str = ""
    total_dur: float = 0.0         # 成片目标时长
    subs: List[Dict] = field(default_factory=list)   # [{text,start,end}] 实测时间窗
    title: str = ""
    seed: int = 0
    overlap: Optional[float] = None
    title_end: Optional[float] = None

    @property
    def signature(self) -> Tuple:
        return tuple(c.key for c in self.clips)

    def to_dict(self) -> Dict:
        return {
            "index": self.index,
            "narration": self.narration,
            "narration_dur": self.narration_dur,
            "voice": self.voice,
            "total_dur": self.total_dur,
            "title": self.title,
            "overlap": self.overlap,
            "title_end": self.title_end,
            "subs": self.subs,
            "clips": [
                {
                    "src": c.src, "start": c.start,
                    "dur": c.dur, "mirror": c.mirror, "slot": c.slot, "motion": c.motion,
                }
                for c in self.clips
            ],
        }


# 各节奏的片段时长范围（秒）
PACE_RANGES: Dict[str, Tuple[Tuple[float, float], Tuple[float, float]]] = {
    #        (hook 范围, body 范围)
    "normal": ((1.5, 3.0), (2.5, 5.5)),
    "fast":   ((1.0, 2.0), (1.2, 2.8)),
}


class MaterialsExhausted(RuntimeError):
    pass


class Planner:
    """按配音时长生成 N 条互不相同的片段方案。"""

    def __init__(self, cfg: JobConfig, assets: Sequence[Asset], used=()):
        self.cfg = cfg
        self.assets = list(assets)
        self._use_count: Dict[str, int] = dict.fromkeys(used, 1)
        self._seen_sig: set = set()

    def _fill_timeline(self, rng, target, sentences=()):
        cfg = self.cfg
        fps = cfg.fps
        remaining = math.ceil(target * fps)
        pool = [(a, math.floor((max(1, cfg.img_dur) if a.is_image else a.duration) * fps))
                for a in self.assets]
        pool = [(a, cap) for a, cap in pool if cap >= 2]
        if not pool:
            raise RuntimeError("没有可用素材")
        overlap = min(round(cfg.trans_dur * fps), math.floor(min(c for _, c in pool) * 0.45))
        minimum = max(2, math.ceil(overlap / 0.45))
        clips = []
        used = set()
        last_image = True
        while remaining > 0:
            if clips and remaining < round(0.8 * fps):
                last = clips[-1]
                source = next(a for a in self.assets if a.path == last.src)
                if source.is_image or last.start + last.dur + remaining / fps <= source.duration:
                    last.dur += remaining / fps
                    break
            fresh = [(a, cap) for a, cap in pool if a.path not in used
                     and not self._use_count.get(a.path)]
            candidates = fresh or (pool if cfg.allow_reuse or cfg.reuse_fallback else [])
            if not candidates:
                raise MaterialsExhausted("无可用新素材铺满时间轴，是否使用老素材？")
            asset, cap = min(candidates, key=lambda item: (
                bool(clips) and item[0].path == clips[-1].src,
                item[0].path in used, self._use_count.get(item[0].path, 0),
                item[0].is_image == last_image, rng.random()))
            last_image = asset.is_image
            contribution = overlap if clips else 0
            want = cap
            if not asset.is_image and (cfg.allow_reuse or cfg.reuse_fallback):
                span = PACE_RANGES[cfg.pace][bool(clips)]
                want = round(rng.uniform(*span) * fps)
            if cfg.sentence_cuts and (cfg.allow_reuse or cfg.reuse_fallback):
                elapsed = math.ceil(target * fps) - remaining
                low = fps if asset.is_image else max(minimum, round(1.2 * fps))
                high = min(cap, want + round(0.9 * fps))
                boundaries = [round(((a["end"] + b["start"]) / 2 + cfg.narration_delay) * fps)
                              for a, b in zip(sentences, sentences[1:])]
                lengths = [point - elapsed + contribution + round(overlap / 2) for point in boundaries]
                choices = [length for length in lengths if low <= length <= high]
                if choices:
                    want = min(choices, key=lambda length: abs(length - want))
            frames = min(cap, max(fps if asset.is_image else minimum, minimum, min(want, remaining + contribution)))
            clips.append(ClipSpec(
                src=asset.path, start=0 if asset.is_image else rng.randint(0, cap - frames) / fps,
                dur=frames / fps, index=len(clips),
                mirror=not asset.is_image and rng.random() < cfg.mirror_prob,
                slot="body" if clips else "hook",
                motion="center" if asset.is_image else "in",
            ))
            used.add(asset.path)
            remaining -= frames - contribution
        return clips, overlap / fps

    def build_variant(
        self,
        index: int,
        seed: int,
        target_dur: float,
        narration_path: str,
        narration_dur: float,
        voice: str,
        subs: List[Dict],
        title: str,
        sentences=None,
    ) -> Optional[Variant]:
        rng = random.Random(seed)

        clips, overlap = self._fill_timeline(rng, target_dur, sentences or subs)
        final_len = target_dur
        if clips[-1].motion == "center":
            # Keep a short final image from being truncated by the output limit.
            end = sum(c.dur for c in clips) - overlap * (len(clips) - 1)
            final_len = max(target_dur, end - clips[-1].dur + 1)


        v = Variant(
            index=index, clips=clips,
            narration=narration_path, narration_dur=narration_dur,
            voice=voice, total_dur=round(final_len, 2),
            subs=subs, title=title, seed=seed, overlap=overlap,
        )
        return v

    # ------------------------------------------------------------------
    def build(
        self,
        count: int,
        narration_paths: Sequence[str],
        narration_durs: Sequence[float],
        voices: Sequence[str],
        subs: List[List[Dict]],   # 每条视频各自的字幕时间窗（按变体下标取）
        titles: Sequence[str],
        progress=None,
        timing_subs=None,
    ) -> List[Variant]:
        out: List[Variant] = []
        for i in range(count):
            seed = self.cfg.seed + i * 7919
            target = self.cfg.target_duration(narration_durs[i])
            my_subs = subs[i] if i < len(subs) else []
            sentences = timing_subs[i] if timing_subs is not None else my_subs
            v = self.build_variant(
                index=i, seed=seed, target_dur=target,
                narration_path=narration_paths[i],
                narration_dur=narration_durs[i],
                voice=voices[i], subs=my_subs, title=titles[i], sentences=sentences,
            )
            if self.cfg.dedup and self.cfg.allow_reuse and v.signature in self._seen_sig:
                v = self.build_variant(i, seed + 104729, target, narration_paths[i],
                                       narration_durs[i], voices[i], my_subs, titles[i], sentences)
            if self.cfg.show_title and not self.cfg.title.strip() and sentences:
                v.title_end = sentences[0]["end"] + self.cfg.narration_delay
            self._seen_sig.add(v.signature)
            for clip in v.clips:
                self._use_count[clip.src] = self._use_count.get(clip.src, 0) + 1
            out.append(v)
            if progress:
                progress(len(out), count, v)
        return out
