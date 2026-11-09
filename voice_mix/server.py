"""本地 Web 服务：四步流程 GUI 的后端。

  GET  /                    → GUI 页面
  GET  /api/voices          → 音色列表
  POST /api/preview         → 配音试听（返回音频 URL + 时长）
  POST /api/scan            → 扫描素材文件夹
  POST /api/generate        → 启动一键生成任务
  GET  /api/job/<id>        → 轮询任务进度
  GET  /api/media?path=...  → 播放已生成的视频/试听音频
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import replace
from math import isfinite
import time
import uuid
from pathlib import Path
from urllib.parse import quote
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .assets import scan as scan_assets
from .config import COVER_TEMPLATES, SUB_COLORS, SUB_POSITIONS, JobConfig, TEMPLATES
from .pipeline import Pipeline, _material_history
from .planner import ClipSpec, MaterialsExhausted, Variant
from .render import render_batch, render_cover, probe_video_duration
from .assets import probe, IMAGE_EXTS
from .tts import VOICE_LIST, probe_audio_duration, synth
from .runtime import DATA_DIR, VERSION, default_output, font_candidates

app = FastAPI(title="voice-mix")
app.state.instance_id = uuid.uuid4().hex
app.state.ui_ready = threading.Event()


@app.get('/api/health')
async def api_health():
    return {'app': 'VoiceMix Studio', 'version': VERSION, 'instance': app.state.instance_id,
            'browser_mode': getattr(app.state,'browser_mode',False)}


class UIReadyRequest(BaseModel):
    instance: str


@app.post('/api/desktop/ready')
def api_ui_ready(req: UIReadyRequest):
    if req.instance != app.state.instance_id:
        raise HTTPException(409,'工作台实例已更新')
    if not app.state.ui_ready.is_set():
        app.state.ui_ready.set()
        callback=getattr(app.state,'page_ready_callback',None)
        if callback:callback()
    return {'ok':True}


@app.post('/api/desktop/exit')
def api_desktop_exit():
    callback = getattr(app.state,'browser_exit',None)
    if not callback:
        raise HTTPException(400,'请使用窗口关闭按钮')
    from .mv_api import TASKS, LOCK
    with _JOBS_LOCK:
        busy = any(j['status'] in {'running','cancelling'} for j in _JOBS.values())
    with LOCK:
        busy = busy or any(j['status'] in {'running','queued'} for j in TASKS.values())
    if busy:
        raise HTTPException(409,'仍有任务运行，请先取消或等待任务结束')
    callback()
    return {'ok': True}


@app.middleware("http")
async def local_origin_only(request: Request, call_next):
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
        return JSONResponse({"detail": "请在本机工作台中操作"}, status_code=403)
    response = await call_next(request)
    # Desktop profiles survive upgrades; never reuse an older HTML/JS shell.
    if request.url.path == '/' or request.url.path.endswith(('.js','.css','.html')):
        response.headers['Cache-Control'] = 'no-store'
    response.headers['X-VoiceMix-Version'] = VERSION
    return response

_STATIC = Path(__file__).parent / "static"
_BGM_DIR = DATA_DIR / "_bgm"
_BGM_DIR.mkdir(exist_ok=True)

# 任务注册表（内存）
_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_RENDER_LOCK = threading.Lock()
_JOB_STORE = DATA_DIR / "_saved_jobs"


def _save_job(state):
    _JOB_STORE.mkdir(exist_ok=True)
    path = _JOB_STORE / (state["id"] + ".json")
    data = dict(state, config=state["config"].to_dict())
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _get_job(job_id):
    if not re.fullmatch(r"[0-9a-f]{12}", job_id):
        return None
    with _JOBS_LOCK:
        if job_id in _JOBS:
            return _JOBS[job_id]
        path = _JOB_STORE / (job_id + ".json")
        if not path.is_file():
            return None
        state = json.loads(path.read_text(encoding="utf-8"))
        state["config"] = JobConfig.from_dict(state["config"])
        _MEDIA_ROOTS.add(state["config"].out_dir)
        _JOBS[job_id] = state
        return state
# 允许通过 /api/media 访问的目录（输出目录 + 试听/背景音目录）
_MEDIA_ROOTS: set = set()

FONT_CANDIDATES = [
    (r"C:\Windows\Fonts\msyhbd.ttc", "微软雅黑·粗（推荐）"),
    (r"C:\Windows\Fonts\msyh.ttc", "微软雅黑"),
    (r"C:\Windows\Fonts\simhei.ttf", "黑体"),
    (r"C:\Windows\Fonts\simkai.ttf", "楷体"),
    (r"C:\Windows\Fonts\simfang.ttf", "仿宋"),
    (r"C:\Windows\Fonts\Dengb.ttf", "等线·粗"),
    (r"C:\Windows\Fonts\Deng.ttf", "等线"),
    (r"C:\Windows\Fonts\STZHONGS.TTF", "华文中宋"),
    (r"C:\Windows\Fonts\STKAITI.TTF", "华文楷体"),
]


def _list_fonts():
    return [{"path": p, "label": label}
            for p, label in font_candidates()]


def _list_bgm():
    items = []
    for p in sorted(_BGM_DIR.glob("*")):
        if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}:
            items.append({
                "name": p.stem,
                "path": str(p.resolve()),
                "url": f"/api/media?path={quote(str(p.resolve()), safe='')}",
                "size_mb": round(p.stat().st_size / 1048576, 2),
            })
    return items


class PreviewReq(BaseModel):
    script: str
    voice: str = "zh-CN-XiaoxiaoNeural"
    rate: str = "+0%"


class ScanReq(BaseModel):
    src_dir: str


class GenerateReq(BaseModel):
    config: Dict[str, Any]
    preview_only: bool = False


class ProjectsReq(BaseModel):
    projects: list[dict]


@app.get("/api/projects")
def api_projects():
    path = DATA_DIR / "projects.json"
    with _JOBS_LOCK:
        if not path.is_file():
            return {"projects": []}
        return {"projects": json.loads(path.read_text(encoding="utf-8"))}


@app.put("/api/projects")
def api_save_projects(req: ProjectsReq):
    if len(req.projects) > 1000:
        raise HTTPException(400, "项目数量超过上限")
    data = json.dumps(req.projects, ensure_ascii=False, indent=2)
    if len(data.encode("utf-8")) > 8 * 1024 * 1024:
        raise HTTPException(400, "项目存档过大")
    with _JOBS_LOCK:
        path = DATA_DIR / "projects.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(data, encoding="utf-8")
        temp.replace(path)
    return {"ok": True}


@app.get("/api/voices")
def api_voices():
    from .assets import FFMPEG, FFPROBE
    return {
        "version": VERSION,
        "default_output": default_output(),
        "engine_ready": bool(FFMPEG and FFPROBE),
        "voices": [{"id": v, "label": label} for v, label in VOICE_LIST],
        "templates": [
            {"id": k, "label": t["label"]} for k, t in TEMPLATES.items()
        ],
        "covers": [{"id": k, "label": v} for k, v in COVER_TEMPLATES.items()],
        "fonts": _list_fonts(),
        "sub_colors": SUB_COLORS,
        "sub_positions": SUB_POSITIONS,
        "bgm": _list_bgm(),
    }


@app.post("/api/bgm/upload")
async def api_bgm_upload(request: Request, name: str = "bgm"):
    """上传 BGM：请求体为原始音频字节，?name=文件名。"""
    body = await request.body()
    if not body or len(body) < 1024:
        raise HTTPException(400, "音频文件为空或太小")
    safe = Path(name).name
    ext = Path(safe).suffix.lower()
    if ext not in {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}:
        ext = ".mp3"
        safe = Path(safe).stem + ext
    import re as _re
    stem = _re.sub(r"[^\w\u4e00-\u9fff-]", "_", Path(safe).stem)[:40] or "bgm"
    out = _BGM_DIR / f"{stem}_{uuid.uuid4().hex[:6]}{ext}"
    out.write_bytes(body)
    return {"ok": True, "path": str(out.resolve()), "bgm": _list_bgm()}


@app.get("/api/bgm/list")
def api_bgm_list():
    return {"bgm": _list_bgm()}


@app.post("/api/preview")
def api_preview(req: PreviewReq):
    text = (req.script or "").strip()
    if not text:
        raise HTTPException(400, "文案为空，无法试听")
    # 取前 55 个字符做试听
    text = text[:55]
    preview_dir = DATA_DIR / "_previews"
    preview_dir.mkdir(exist_ok=True)
    key = abs(hash((text, req.voice, req.rate))) % (10**12)
    out = preview_dir / f"preview_{key}.mp3"
    if not out.exists() or out.stat().st_size < 512:
        try:
            synth(text, req.voice, str(out), rate=req.rate)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, f"TTS 试听失败: {e}")
    dur = probe_audio_duration(str(out))
    _MEDIA_ROOTS.add(str(preview_dir.resolve()))
    return {
        "url": f"/api/media?path={out.resolve()}",
        "duration": round(dur, 2),
        "text": text,
    }


@app.post("/api/scan")
def api_scan(req: ScanReq):
    src = req.src_dir.strip()
    p = Path(src)
    if not src or not p.exists():
        raise HTTPException(400, f"素材路径不存在: {src}")
    try:
        assets = scan_assets(src, recursive=True, img_display=3.0)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"扫描失败: {e}")
    n_img = sum(1 for a in assets if a.is_image)
    n_vid = len(assets) - n_img
    vid_dur = sum(a.duration for a in assets if not a.is_image)
    groups: Dict[str, int] = {}
    for a in assets:
        groups[a.group or "(根目录)"] = groups.get(a.group or "(根目录)", 0) + 1
    # 缩略样本（供前端预览，最多 24 个）
    sample = []
    for a in assets[:24]:
        sample.append({
            "name": a.name, "is_image": a.is_image,
            "duration": round(a.duration, 1),
            "portrait": a.is_portrait,
        })
    return {
        "total": len(assets),
        "videos": n_vid,
        "images": n_img,
        "video_seconds": round(vid_dur, 1),
        "groups": groups,
        "sample": sample,
        "enough": bool(assets),
    }


@app.post("/api/generate")
def api_generate(req: GenerateReq):
    from .batch import validate_scripts, run_batch
    cfg = JobConfig.from_dict(req.config)
    scripts = req.config.get('batch_scripts')
    if scripts is not None:
        try:
            scripts = validate_scripts(scripts,cfg.count)
        except ValueError as error:
            raise HTTPException(400,str(error))
        cfg.script = scripts[0]
    errs = cfg.validate()
    if errs:
        raise HTTPException(400, "；".join(errs))

    job_id = uuid.uuid4().hex[:12]
    cfg.out_dir = str(Path(cfg.out_dir).resolve() / job_id)
    return _start_job(job_id, cfg, lambda progress: run_batch(cfg,scripts,progress,req.preview_only)
                      if scripts is not None else Pipeline(cfg, progress, preview_only=req.preview_only).run())


def _start_job(job_id, cfg, run):

    out_root = Path(cfg.out_dir).resolve()
    _MEDIA_ROOTS.add(str(out_root))

    state = {
        "id": job_id,
        "status": "running",
        "phase": "init",
        "pct": 0,
        "detail": "任务启动 ...",
        "created_at": time.strftime("%H:%M:%S"),
        "result": None,
        "config": cfg,
        "error_code": None,
        "error": None,
        "log": [],
    }

    with _JOBS_LOCK:
        _JOBS[job_id] = state

    def on_progress(phase: str, pct: float, detail: str = "") -> None:
        with _JOBS_LOCK:
            if state["status"] == "cancelling":
                raise RuntimeError("任务已取消")
            state["phase"] = phase
            state["pct"] = round(pct)
            state["detail"] = detail
            state["log"].append(f"[{time.strftime('%H:%M:%S')}] {detail}")

    def run_job() -> None:
        try:
            with _RENDER_LOCK:
                on_progress("init", 0, "开始处理任务")
                result = run(on_progress)
            with _JOBS_LOCK:
                if state["status"] == "cancelling":
                    state["status"] = "cancelled"
                    return
                state["status"] = "done"
                state["result"] = result
                if not result.get("draft"):
                    _save_job(state)
        except Exception as e:  # noqa: BLE001
            with _JOBS_LOCK:
                state["status"] = "cancelled" if state["status"] == "cancelling" else "error"
                state["error"] = str(e)
                if isinstance(e, MaterialsExhausted):
                    state["error_code"] = "materials_exhausted"
                state["log"].append(f"[ERROR] {e}")

    threading.Thread(target=run_job, daemon=True).start()
    return {"job_id": job_id}


class EditReq(BaseModel):
    index: int
    order: list[int]
    starts: list[float]
    subtitles: list[str]
    title: str | None = None
    durations: list[float] | None = None
    replacements: list[str] | None = None
    draft: bool = False
    settings: Dict[str, Any]


@app.post("/api/job/{job_id}/edit")
def api_edit(job_id: str, req: EditReq):
    state = _get_job(job_id)
    if not state or state["status"] != "done":
        raise HTTPException(404, "找不到已完成的任务")
    original = next((v for v in state["result"]["variants"] if v["index"] == req.index), None)
    if original is None:
        raise HTTPException(404, "找不到成片")
    clips = original["clips"]
    if (sorted(req.order) != list(range(len(clips))) or len(req.starts) != len(clips)
            or len(req.subtitles) != len(original["subs"])):
        raise HTTPException(400, "片段或字幕数量不匹配")
    durations = req.durations if req.durations is not None else [clips[i]["dur"] for i in req.order]
    replacements = req.replacements if req.replacements is not None else [""] * len(clips)
    if len(durations) != len(clips) or len(replacements) != len(clips):
        raise HTTPException(400, "片段数量不匹配")
    asset_map = {}
    revised = []
    root = Path(state["config"].src_dir).resolve()
    fps = state["config"].fps
    for index, start, duration, replacement in zip(req.order, req.starts, durations, replacements):
        clip = ClipSpec(**clips[index], index=len(revised))
        if replacement:
            new_path = Path(replacement).resolve()
            if new_path != root and (not root.is_dir() or not new_path.is_relative_to(root)):
                raise HTTPException(400, "替换素材必须来自当前项目素材")
            clip = replace(clip, src=str(new_path))
        if not isfinite(duration) or not (1 / fps <= duration <= 300):
            raise HTTPException(400, "片段时长无效")
        clip = replace(clip, dur=round(duration * fps) / fps)
        image = Path(clip.src).suffix.lower() in IMAGE_EXTS
        if not isfinite(start) or start < 0:
            raise HTTPException(400, "素材入点必须为有效的非负秒数")
        if image:
            if not Path(clip.src).is_file() or start or clip.dur < 1:
                raise HTTPException(400, "图片须存在、入点为 0，且至少展示 1 秒")
            asset_map[clip.src] = (False, True)
        else:
            info = probe(clip.src)
            if not info:
                raise HTTPException(400, f"素材无法读取：{Path(clip.src).name}")
            stream = next((s for s in info["streams"] if s.get("codec_type") == "video"), None)
            if not stream:
                raise HTTPException(400, "替换文件必须为视频或图片")
            duration = float(info["format"].get("duration", 0))
            if start + clip.dur > duration + 0.002:
                raise HTTPException(400, f"入点超出素材可用范围：{Path(clip.src).name}")
            asset_map[clip.src] = (any(s["codec_type"] == "audio" for s in info["streams"]), False)
        revised.append(replace(clip, start=start))
    requested_overlap = req.settings.get("trans_dur", original.get("overlap") or 0)
    if not isinstance(requested_overlap, (int, float)) or not 0 <= requested_overlap <= 1:
        raise HTTPException(400, "转场时长需在 0~1 秒之间")
    overlap = min(requested_overlap, min(c.dur for c in revised) * .45)
    length = sum(c.dur for c in revised) - overlap * (len(revised) - 1)
    if (not any(replacements) and all(abs(revised[j].dur - clips[i]["dur"]) < 0.002
            for j, i in enumerate(req.order)) and abs(overlap - (original.get("overlap") or 0)) < 0.002):
        length = original["total_dur"]
    if length + 0.002 < original["narration_dur"] + state["config"].narration_delay:
        raise HTTPException(400, "调整后画面时长不足以覆盖配音，请延长片段")
    subs = [dict(sub, text=value) for sub, value in zip(original["subs"], req.subtitles)]
    variant = Variant(**dict(original, clips=revised, subs=subs, overlap=overlap, total_dur=length,
                             title=original["title"] if req.title is None else req.title))
    edit_id = uuid.uuid4().hex[:12]
    out = Path(state["config"].out_dir).parent / edit_id
    settings = {key: value for key, value in req.settings.items() if key in {
        "sub_font", "sub_style", "sub_opacity", "sub_color", "sub_pos", "sub_size_ratio",
        "video_filter", "filter_strength", "sub_box_color", "bgm_file", "bgm_gain", "bgm_duck", "keep_original", "trans_style",
        "cover_title", "cover_template",
    }}
    cfg = replace(state["config"], out_dir=str(out), **settings)
    errors = cfg.validate()
    if errors:
        raise HTTPException(400, "；".join(errors))

    if req.draft:
        cfg = replace(cfg, width=360, height=640, preset="ultrafast", crf=28)

    def run(progress):
        progress("render", 40, "生成粗剪预览" if req.draft else "重新渲染微调版本")
        rows = render_batch(cfg, [variant], out / "videos", out / "parts", asset_map, jobs=1)
        if not rows[0]["ok"]:
            raise RuntimeError(rows[0]["error"])
        if not req.draft:
            _material_history(c.src for c in variant.clips)
            cover = render_cover(cfg, variant, Path(rows[0]["path"]), out / "covers")
            if cover:
                rows[0]["cover"] = str(cover)
        return {"out_dir": str(out), "ok": 1, "total": 1, "seconds": 0, "draft": req.draft,
                "results": rows, "variants": [variant.to_dict()], "revision": True}

    return _start_job(edit_id, cfg, run)


@app.get("/api/job/{job_id}/assets")
def api_edit_assets(job_id: str):
    state = _get_job(job_id)
    if not state or state["status"] != "done":
        raise HTTPException(404, "找不到已完成的任务")
    cfg = state["config"]
    return [{"path": a.path, "name": a.name, "image": a.is_image, "duration": a.duration}
            for a in scan_assets(cfg.src_dir)]


class CoverReq(BaseModel):
    index: int
    time: float
    template: str
    title: str = ""


@app.post("/api/job/{job_id}/cover")
def api_cover(job_id: str, req: CoverReq):
    state = _get_job(job_id)
    if not state or state["status"] != "done":
        raise HTTPException(404, "找不到已完成的任务")
    row = next((r for r in state["result"]["results"] if r["index"] == req.index and r["ok"]), None)
    if row is None or not Path(row["path"]).is_file():
        raise HTTPException(404, "找不到成片")
    if state["result"].get("initial_preview"):
        raise HTTPException(400, "请先导出正式版本，再从成片选封面")
    duration = probe_video_duration(row["path"])
    if not isfinite(req.time) or not 0 <= req.time < duration:
        raise HTTPException(400, "选帧时间超出视频范围")
    if req.template not in COVER_TEMPLATES or req.template == "none":
        raise HTTPException(400, "请选择一个封面模板")
    data = next(v for v in state["result"]["variants"] if v["index"] == req.index)
    variant = Variant(**dict(data, clips=[ClipSpec(**c) for c in data["clips"]]))
    cfg = replace(state["config"], cover_template=req.template, cover_title=req.title)
    with _RENDER_LOCK:
        folder = Path(cfg.out_dir) / "covers" / uuid.uuid4().hex[:8]
        output = render_cover(cfg, variant, Path(row["path"]), folder, frame_time=req.time)
        if output is None:
            raise HTTPException(400, "该时刻无法取帧，请稍向前移动")
        with _JOBS_LOCK:
            row["cover"] = str(output)
            _save_job(state)
    return {"cover": str(output)}


@app.get("/api/job/{job_id}")
def api_job(job_id: str):
    state = _get_job(job_id)
    with _JOBS_LOCK:
        if not state:
            raise HTTPException(404, "任务不存在")
        return {
            "id": state["id"], "status": state["status"], "phase": state["phase"],
            "pct": state["pct"], "detail": state["detail"],
            "result": state["result"], "error": state["error"], "error_code": state["error_code"],
            "log": state["log"][-12:],
        }


@app.post("/api/job/{job_id}/cancel")
def api_cancel(job_id: str):
    with _JOBS_LOCK:
        state = _JOBS.get(job_id)
        if not state:
            raise HTTPException(404, "任务不存在")
        if state["status"] == "running":
            state["status"] = "cancelling"
    return {"ok": True}


@app.get("/api/media")
def api_media(path: str):
    p = Path(path).resolve()
    if not p.is_file():
        raise HTTPException(404, "文件不存在")
    roots = [*_MEDIA_ROOTS, _BGM_DIR.resolve(), (DATA_DIR / "_previews").resolve()]
    allowed = any(p.is_relative_to(root) for root in roots)
    if not allowed:
        raise HTTPException(403, "路径不在允许的输出目录内")
    media_type = {
        ".mp4": "video/mp4", ".mp3": "audio/mpeg", ".png": "image/png",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    }.get(p.suffix.lower(), "application/octet-stream")
    return FileResponse(str(p), media_type=media_type)


# MV uses a separate music timeline and persistent project store.
from .mv_api import router as mv_router
app.include_router(mv_router)

# GUI 页面放最后挂载（避免吞掉 /api 路由）
app.mount("/", StaticFiles(directory=str(_STATIC), html=True), name="static")
