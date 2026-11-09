"""一键生成流水线：逐句配音 → 扫描 → 方案 → 渲染 → 封面，带进度回调。"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from dataclasses import replace
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .assets import scan as scan_assets
from .config import JobConfig
from .planner import Planner
from .render import render_batch, render_cover
from .tts import VOICE_LIST, split_sentences, synth, synth_narration
from .runtime import DATA_DIR


def _material_history(used=()):
    # Keyed by canonical asset path so a folder and its individual files share history.
    db = DATA_DIR / "_material_usage.sqlite3"
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute("CREATE TABLE IF NOT EXISTS used (path TEXT PRIMARY KEY)")
        conn.executemany("INSERT OR IGNORE INTO used VALUES (?)",
                         ((os.path.normcase(str(Path(p).resolve())),) for p in used))
        return {path for (path,) in conn.execute("SELECT path FROM used")}


class Pipeline:
    """单次生成任务的执行器。"""

    def __init__(self, cfg: JobConfig, on_progress: Optional[Callable] = None, preview_only: bool = False, used_paths=()):
        self.cfg = cfg
        self.on_progress = on_progress or (lambda *a, **k: None)
        self.cancelled = False
        self.preview_only = preview_only
        self.used_paths = set(used_paths)

    def _emit(self, phase: str, pct: float, detail: str = "") -> None:
        self.on_progress(phase=phase, pct=pct, detail=detail)

    def _check_cancel(self) -> None:
        if self.cancelled:
            raise RuntimeError("任务已取消")

    # ------------------------------------------------------------------
    def run(self) -> Dict:
        cfg = self.cfg
        t_start = time.perf_counter()

        errs = cfg.validate()
        if errs:
            raise RuntimeError("；".join(errs))

        out_root = Path(cfg.out_dir).resolve()
        out_root.mkdir(parents=True, exist_ok=True)
        videos_dir = out_root / "videos"
        covers_dir = out_root / "covers"
        parts_dir = out_root / "parts"
        tts_dir = out_root / "tts"
        videos_dir.mkdir(exist_ok=True)

        # ---- 1. 文案 → 句子 ----
        self._emit("tts", 2, "切分文案 ...")
        sentences = split_sentences(cfg.script)
        if not sentences:
            raise RuntimeError("文案切分结果为空")

        # ---- 2. 逐句配音（精确计时，字幕零漂移）----
        narrations: List[str] = []
        nar_durs: List[float] = []
        all_subs: List[List[Dict]] = []
        voices: List[str] = []
        for i in range(cfg.count):
            self._check_cancel()
            if cfg.voice_vary:
                import random as _r
                pool = [v for v, _ in VOICE_LIST if v != cfg.voice]
                rng = _r.Random(cfg.seed + i)
                voice = rng.choice(pool) if rng.random() < 0.5 else cfg.voice
            else:
                voice = cfg.voice
            nar_path = tts_dir / f"narration_{i:05d}.mp3"
            self._emit("tts", 2 + 22 * (i + 1) / max(1, cfg.count),
                       f"逐句配音 {i + 1}/{cfg.count}（{voice.split('-')[-1].replace('Neural', '')}）")
            subs, dur = synth_narration(sentences, voice, str(nar_path), rate=cfg.rate,
                                        pause_style=cfg.pause_style)
            narrations.append(str(nar_path))
            nar_durs.append(dur)
            all_subs.append(subs)
            voices.append(voice)

        self._check_cancel()
        self._emit("scan", 26, f"扫描素材: {cfg.src_dir}")

        # ---- 3. 扫描素材 ----
        assets = scan_assets(
            cfg.src_dir, recursive=True,
            min_dur=cfg.min_asset_dur, max_dur=cfg.max_asset_dur,
            img_display=cfg.img_display,
        )
        if not assets:
            raise RuntimeError("素材文件夹里没有可用素材（视频或图片）")
        n_img = sum(1 for a in assets if a.is_image)
        self._emit("scan", 31,
                   f"素材 {len(assets)} 条（视频 {len(assets) - n_img} / 图片 {n_img}）")
        asset_map = {a.path: (a.has_audio, a.is_image) for a in assets}

        # ---- 4. 标题与字幕分工（避免同句上下重复）----
        # 带标题模板：标题 = 第一句（或用户指定），字幕从第二句开始
        show_title = cfg.show_title
        custom_title = cfg.title.strip()
        subs_for_video: List[List[Dict]] = []
        titles: List[str] = []
        for i in range(cfg.count):
            subs = all_subs[i]
            if show_title:
                title = custom_title or (subs[0]["text"] if subs else "")
                if not custom_title and subs:
                    subs = subs[1:]          # 标题已用第一句，字幕跳过
            else:
                title = custom_title or ""
            titles.append(title)
            subs_for_video.append(subs)

        # ---- 5. 方案 ----
        self._emit("plan", 33, "生成混剪方案 ...")
        history = _material_history() if not cfg.allow_reuse else set()
        planner = Planner(cfg, assets, used=[a.path for a in assets if a.path in self.used_paths and not cfg.allow_reuse] + [
            a.path for a in assets if os.path.normcase(str(Path(a.path).resolve())) in history
        ])
        variants = planner.build(
            cfg.count, narrations, nar_durs, voices, subs_for_video, titles,
            timing_subs=all_subs,
            progress=lambda i, n, v: self._emit("plan", 33 + 7 * i / max(1, n),
                                                f"方案 {i}/{n}"),
        )
        if not variants:
            raise RuntimeError("无法生成混剪方案（素材可能过少）")
        self._check_cancel()

        # ---- 6. 渲染 ----
        # xfade 单次编码内存占用较高，并行度保守（低内存机器上过多并行会 OOM）
        n_jobs = max(1, min(2, (os.cpu_count() or 4) // 2))
        self._emit("render", 40, f"开始渲染 {len(variants)} 条（{n_jobs} 并行）")
        render_cfg = replace(cfg, width=360, height=640, preset="ultrafast", crf=28) if self.preview_only else cfg
        results = render_batch(
            render_cfg, variants, videos_dir, parts_dir, asset_map,
            jobs=n_jobs, overwrite=True,
            progress=lambda i, n, r: self._emit(
                "render", 40 + 52 * i / max(1, n),
                f"渲染 {i}/{n}" + ("" if r["ok"] else f"  ← 失败: {r['error'][:80]}"),
            ),
        )

        # ---- 7. 封面 ----
        covers: Dict[int, str] = {}
        if not self.preview_only and cfg.cover_template not in ("none", ""):
            ok_items = [r for r in results if r["ok"]]
            for j, r in enumerate(ok_items):
                v = next((vv for vv in variants if vv.index == r["index"]), None)
                if v is None:
                    continue
                self._emit("cover", 92 + 6 * (j + 1) / max(1, len(ok_items)),
                           f"生成封面 {j + 1}/{len(ok_items)}")
                cpath = render_cover(cfg, v, Path(r["path"]), covers_dir)
                if cpath:
                    covers[r["index"]] = str(cpath)

        # ---- 8. 清单 ----
        ok_results = [r for r in results if r["ok"]]
        successful = {r["index"] for r in ok_results}
        if successful and not self.preview_only:
            _material_history((c.src for v in variants if v.index in successful for c in v.clips))
        if not ok_results:
            raise RuntimeError(results[0]["error"] if results else "渲染失败")
        for r in ok_results:
            r["cover"] = covers.get(r["index"], "")
        manifest = {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "script": cfg.script,
            "template": cfg.template,
            "voice": cfg.voice,
            "count": len(variants),
            "ok": len(ok_results),
            "assets": len(assets),
            "images": n_img,
            "results": results,
            "variants": [v.to_dict() for v in variants],
            "config": cfg.to_dict(),
        }
        import json
        (out_root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        dt = time.perf_counter() - t_start
        self._emit("done", 100,
                   f"完成 {len(ok_results)}/{len(results)} 条，用时 {dt / 60:.1f} 分钟")
        return {
            "out_dir": str(out_root),
            "videos_dir": str(videos_dir),
            "initial_preview": self.preview_only,
            "ok": len(ok_results),
            "total": len(results),
            "seconds": round(dt, 1),
            "results": results,
            "variants": [v.to_dict() for v in variants if v.index in successful],
            "narration_dur": round(nar_durs[0], 2) if nar_durs else 0,
        }
