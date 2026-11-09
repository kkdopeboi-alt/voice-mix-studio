"""Persisted MV projects, uploads, asynchronous analysis and rendering."""
from __future__ import annotations

import copy
import importlib.util
import ipaddress
import json
import os
import re
import socket
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .runtime import DATA_DIR, default_font, default_output
from .assets import scan, probe, IMAGE_EXTS, VIDEO_EXTS, FFMPEG
from .mv_core import STYLES, SCENES, parse_lrc, align_text, plan, validate_project, recommendations

router = APIRouter(prefix='/api/mv')
ROOT = DATA_DIR / '_mv'
ROOT.mkdir(exist_ok=True)
LOCK = threading.RLock()
TASKS = {}
ENGINE_LOCK = threading.Lock()
AUDIO = {'.mp3','.wav','.m4a','.flac','.ogg','.aac','.opus'}


def project_file(pid):
    if not re.fullmatch('[0-9a-f]{12}',pid):
        raise HTTPException(404,'MV 项目不存在')
    return ROOT / (pid+'.json')


def read(pid):
    path = project_file(pid)
    with LOCK:
        if not path.is_file():
            raise HTTPException(404,'MV 项目不存在')
        return json.loads(path.read_text(encoding='utf-8'))


def save(p, expected=None):
    path = project_file(p['id'])
    with LOCK:
        if expected is not None and read(p['id'])['version'] != expected:
            raise ValueError('项目已在其他操作中更新，请重新载入后再试；已有内容未被覆盖')
        p['version'] = p.get('version',0)+1
        p['updated'] = time.time()
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(p,ensure_ascii=False),encoding='utf-8')
        temp.replace(path)
    return p


def launch(work):
    tid = uuid.uuid4().hex[:12]
    state = dict(id=tid,status='queued',pct=0,detail='等待处理',error=None,result=None,cancel=False)
    with LOCK:
        TASKS[tid] = state
    def progress(pct, detail):
        with LOCK:
            if state['cancel']:
                raise RuntimeError('任务已取消')
            state.update(status='running',pct=round(pct),detail=detail)
    def worker():
        try:
            with ENGINE_LOCK:
                progress(0,'开始处理')
                result = work(progress)
                with LOCK:
                    state.update(status='done',pct=100,result=result,detail='完成')
        except Exception as error:
            from .planner import MaterialsExhausted
            with LOCK:
                state.update(status='cancelled' if state['cancel'] else 'error',error=str(error),
                             error_code='materials_exhausted' if isinstance(error,MaterialsExhausted) else None)
    threading.Thread(target=worker,daemon=True).start()
    return {'task_id':tid}


@router.get('/tasks/{tid}')
def task(tid: str):
    with LOCK:
        if tid not in TASKS:
            raise HTTPException(404,'任务不存在或应用已重启，请恢复项目后重试')
        return copy.deepcopy(TASKS[tid])


@router.post('/tasks/{tid}/cancel')
def cancel(tid: str):
    with LOCK:
        if tid in TASKS and TASKS[tid]['status'] in {'queued','running'}:
            TASKS[tid]['cancel'] = True
    return {'ok':True}


@router.get('/capabilities')
def capabilities():
    return {'asr': bool(importlib.util.find_spec('faster_whisper')),
            'visual':bool(importlib.util.find_spec('onnxruntime')),
            'download':bool(importlib.util.find_spec('yt_dlp')), 'styles':STYLES,
            'scenes':[s[0] for s in SCENES]}


@router.post('/upload')
async def upload(request: Request, name: str):
    ext = Path(name).suffix.lower()
    if ext not in AUDIO | IMAGE_EXTS | VIDEO_EXTS:
        raise HTTPException(400,'请选择音频、视频或图片文件；歌词请使用文本或 LRC 导入')
    directory = ROOT / 'uploads'
    directory.mkdir(exist_ok=True)
    stem = re.sub(r'[^\w\u4e00-\u9fff-]','_',Path(name).stem)[:55] or 'media'
    path = directory / (stem+'_'+uuid.uuid4().hex[:12]+ext)
    total = 0
    try:
        with path.open('wb') as stream:
            async for chunk in request.stream():
                total += len(chunk)
                if total > 1024**3:
                    raise HTTPException(413,'单文件超过 1 GB，请使用桌面版选择本地路径')
                stream.write(chunk)
        if not total:
            raise HTTPException(400,'文件为空')
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {'path':str(path.resolve()),'name':Path(name).name}


class URLRequest(BaseModel):
    url: str = Field(max_length=4000)
    browser: str = ''
    cookie_id: str = ''


@router.post('/cookies')
async def import_cookies(request: Request):
    body=await request.body()
    if len(body)>2*1024*1024 or not body.startswith((b'# Netscape HTTP Cookie File',b'# HTTP Cookie File')):
        raise HTTPException(400,'请选择 Netscape 格式的 cookies.txt 文件（最大 2 MB）')
    folder=ROOT/'credentials'
    folder.mkdir(exist_ok=True)
    token=uuid.uuid4().hex
    (folder/(token+'.txt')).write_bytes(body)
    return {'cookie_id':token}


def download_error(error):
    text=str(error)
    if 'bot' in text.lower() or 'sign in' in text.lower() or 'login' in text.lower():
        return '站点要求登录验证。请先在浏览器中正常打开该视频，再主动选择对应浏览器登录态，或导入该站点的 cookies.txt 后重试；凭据不保证消除站点限制。'
    if any(x in text.lower() for x in ('decrypt','cookie database','dpapi','could not copy')):
        return '无法读取浏览器登录态。可关闭对应浏览器后重试，或改用 Netscape 格式 cookies.txt；请勿发送账号密码。'
    if '403' in text:
        return '站点拒绝访问（403）。请检查该链接能否在浏览器正常播放，必要时选择登录态后重试。'
    return 'URL 导入失败：'+re.sub(r'\x1b\[[0-9;]*m','',text)[-800:]


def public_url(value):
    parsed = urlsplit(value)
    if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('请输入公开 HTTP/HTTPS 媒体或视频页面链接')
    addresses = socket.getaddrinfo(parsed.hostname,parsed.port or 443,type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError('下载链接需要指向公开网络地址')


@router.post('/download')
def download(req: URLRequest):
    if req.browser not in {'','chrome','edge','firefox','brave','safari','opera'}:
        raise HTTPException(400,'请选择支持的浏览器')
    if req.cookie_id and not re.fullmatch('[0-9a-f]{32}',req.cookie_id):
        raise HTTPException(400,'无效的登录凭据标识')
    if req.browser and req.cookie_id:
        raise HTTPException(400,'浏览器登录态与 cookies 文件请选择其中一种')
    def work(progress):
        public_url(req.url)
        try:
            import yt_dlp
        except ImportError:
            raise RuntimeError('此版本缺少 URL 下载组件，请安装 [mv] 依赖')
        target = ROOT / 'downloads' / uuid.uuid4().hex[:12]
        target.mkdir(parents=True)
        def hook(data):
            size = data.get('total_bytes') or data.get('total_bytes_estimate') or 0
            received = data.get('downloaded_bytes',0)
            if max(size,received) > 1024**3:
                raise ValueError('下载文件超过 1 GB 上限')
            progress(min(95,received/max(1,size)*90),'正在下载素材；站点限制或登录要求可能导致失败')
        options = {'outtmpl':str(target/'%(title).60s-%(id)s.%(ext)s'),
                   'noplaylist':True,'max_filesize':1024**3,
                   'format':'bestvideo+bestaudio/best' if FFMPEG else 'best',
                   'merge_output_format':'mp4','socket_timeout':20,'retries':2,
                   'quiet':True,'no_warnings':True,'windowsfilenames':True,
                   'ffmpeg_location':str(Path(FFMPEG).parent) if FFMPEG else None,
                   'progress_hooks':[hook], 'restrictfilenames':False}
        cookie_file=ROOT/'credentials'/(req.cookie_id+'.txt') if req.cookie_id else None
        if cookie_file:
            if not cookie_file.is_file():
                raise ValueError('登录凭据已使用或已过期，请重新导入 cookies.txt')
            options['cookiefile']=str(cookie_file)
        if req.browser:
            options['cookiesfrombrowser']=(req.browser,)
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.extract_info(req.url,download=True)
        except Exception as error:
            raise RuntimeError(download_error(error)) from None
        finally:
            if cookie_file:cookie_file.unlink(missing_ok=True)
        paths = [p for p in target.iterdir() if p.suffix.lower() in AUDIO|VIDEO_EXTS|IMAGE_EXTS]
        if not paths:
            raise ValueError('此链接未返回可用媒体，请下载到本地后上传')
        (target/'source.json').write_text(json.dumps({'url':req.url},ensure_ascii=False),encoding='utf-8')
        videos=[p for p in paths if p.suffix.lower() in VIDEO_EXTS]
        return {'paths':[str(p.resolve()) for p in paths], 'import_id':target.name,
                'video_name':videos[0].name if videos else None,
                'duration':float((probe(str(videos[0])) or {}).get('format',{}).get('duration',0)) if videos else 0}
    return launch(work)


@router.get('/imports/{token}/media')
def imported_media(token: str, name: str):
    if not re.fullmatch('[0-9a-f]{12}',token) or Path(name).name!=name:
        raise HTTPException(404,'导入素材不存在')
    path=ROOT/'downloads'/token/name
    if not path.is_file() or path.suffix.lower() not in VIDEO_EXTS|AUDIO:
        raise HTTPException(404,'导入素材不存在')
    return FileResponse(path)


class CreateRequest(BaseModel):
    name: str = Field(default='未命名 MV',max_length=120)
    audio: str
    source_paths: list[str] = Field(default_factory=list,max_length=300)
    lyrics: str = Field(default='',max_length=100000)
    lyric_input: str = 'text'
    model: str = 'base'
    visual_analysis: bool = True
    settings: dict = Field(default_factory=dict)


def asset_list(paths):
    assets = {}
    for path in paths:
        for a in scan(path,max_dur=3600):
            assets[a.path] = dict(path=a.path,name=a.name,image=a.is_image,duration=a.duration,
                                  tags=a.group,enabled=True,scene_ids=[])
            if len(assets)>300:
                raise ValueError('单个 MV 项目最多 300 份素材，请缩小选择范围')
    return list(assets.values())


@router.post('/projects')
def create(req: CreateRequest):
    try:
        audio = Path(req.audio).resolve()
        if not audio.is_file():
            raise ValueError('歌曲文件不存在')
        info = probe(str(audio))
        if not info or not any(s.get('codec_type')=='audio' for s in info.get('streams',[])):
            raise ValueError('文件中没有可读取的音乐音轨')
        duration = float(info['format'].get('duration',0))
        if not 1 <= duration <= 3600:
            raise ValueError('歌曲长度需在 1 秒到 60 分钟之间')
        if req.lyric_input not in {'text','auto','lrc'}:
            raise ValueError('无效歌词输入方式')
        if req.lyric_input != 'auto' and not req.lyrics.strip():
            raise ValueError('请提供歌词或选择自动识别')
        settings = dict(style='cinema',aspect='9:16',lyric_style='line',filter='warm',
                        resolution='1080p',bitrate_mbps=40,font=default_font(),font_size=.035,color='#ffffff',highlight='#c4ef8b',
                        lyric_y=.78,mask=.2,allow_reuse=True)
        settings.update({k:v for k,v in req.settings.items() if k in settings})
        p = dict(id=uuid.uuid4().hex[:12],name=req.name,audio=str(audio),duration=duration,
                 lyrics=[],lyric_text=req.lyrics,lyric_input=req.lyric_input,model=req.model,
                 visual_analysis=req.visual_analysis,assets=asset_list(req.source_paths),
                 settings=settings,range=[0,duration],clips=[],recommendations=[],energy=[],beats=[],waveform=[],
                 renders=[],version=0,seed=1)
        validate_project(p)
        return save(p)
    except (ValueError,OSError) as error:
        raise HTTPException(400,str(error))


@router.get('/projects')
def projects():
    items = []
    with LOCK:
        for path in ROOT.glob('????????????.json'):
            try:
                p = json.loads(path.read_text(encoding='utf-8'))
                items.append({k:p[k] for k in ('id','name','updated','duration')})
            except (OSError,ValueError,KeyError):
                continue
    return sorted(items,key=lambda p:-p['updated'])


@router.get('/projects/{pid}')
def get_project(pid: str):
    return read(pid)


class UpdateRequest(BaseModel):
    version: int
    project: dict


@router.put('/projects/{pid}')
def update(pid: str, req: UpdateRequest):
    p = read(pid)
    try:
        allowed = {'name','lyrics','settings','clips','range','visual_analysis'}
        for key in allowed:
            if key in req.project:
                p[key] = req.project[key]
        changes = {a['path']:a for a in req.project.get('assets',[])}
        for a in p['assets']:
            if a['path'] in changes:
                for key in ('tags','enabled'):
                    a[key] = changes[a['path']].get(key,a[key])
        validate_project(p)
        return save(p,req.version)
    except (ValueError,KeyError,TypeError) as error:
        raise HTTPException(400,str(error))


class PathsRequest(BaseModel):
    paths: list[str] = Field(max_length=300)


@router.post('/projects/{pid}/assets')
def add_assets(pid: str,req: PathsRequest):
    p = read(pid)
    version = p['version']
    try:
        existing = {a['path']:a for a in p['assets']}
        for a in asset_list(req.paths):
            existing.setdefault(a['path'],a)
        if len(existing)>300:
            raise ValueError('素材数量超过 300')
        p['assets'] = list(existing.values())
        return save(p,version)
    except (ValueError,OSError) as error:
        raise HTTPException(400,str(error))


@router.post('/projects/{pid}/analyze')
def analyze(pid: str):
    p = read(pid)
    version = p['version']
    def work(progress):
        from .mv_ai import transcribe, audio_features
        if p['lyric_input'] == 'lrc':
            p['lyrics'] = parse_lrc(p['lyric_text'],p['duration'])
        else:
            recognized = transcribe(p['audio'],progress,p['model'])
            p['lyrics'] = align_text(p['lyric_text'],recognized,p['duration']) if p['lyric_input']=='text' else recognized
        progress(60,'分析歌曲音量变化、切镜候选点与精彩段落')
        p['energy'],p['beats'],p['waveform'] = audio_features(p['audio'])
        p['recommendations'] = recommendations(p['duration'],p['lyrics'],p['energy'])
        validate_project(p)
        progress(95,'保存歌词时间轴')
        return {'project':save(p,version)}
    return launch(work)


class PlanRequest(BaseModel):
    regenerate: bool = False
    background: dict | None = None


@router.post('/projects/{pid}/plan')
def generate_plan(pid: str,req: PlanRequest):
    p = read(pid)
    version = p['version']
    def work(progress):
        from .pipeline import _material_history
        if req.background:
            from .mv_core import background_plan
            result=background_plan(p,req.background)
            validate_project(result)
            return {'project':save(result,version)}
        if p['visual_analysis']:
            from .mv_ai import tag_visuals
            tag_visuals(p['assets'],progress)
        history = _material_history() if not p['settings']['allow_reuse'] else set()
        used = [a['path'] for a in p['assets'] if os.path.normcase(str(Path(a['path']).resolve())) in history]
        p['seed'] += 1
        progress(92,'匹配歌词意境，编排镜头')
        result = plan(p,used,req.regenerate)
        validate_project(result)
        return {'project':save(result,version)}
    return launch(work)


class RenderRequest(BaseModel):
    preview: bool = True
    out_dir: str = ''


def preview_signature(project):
    import hashlib
    keys=('audio','range','settings','clips','lyrics')
    return hashlib.sha256(json.dumps({k:project[k] for k in keys},sort_keys=True,ensure_ascii=False).encode()).hexdigest()


@router.post('/projects/{pid}/render')
def export(pid: str,req: RenderRequest):
    p = read(pid)
    version = p['version']
    signature=preview_signature(p)
    if not req.preview and not any(r.get('preview') and r.get('signature')==signature for r in p['renders']):
        raise HTTPException(400,'请先生成并检查当前修改的 MV 样板预览，再确认导出')
    def work(progress):
        from .mv_render import render
        from .server import _RENDER_LOCK, _MEDIA_ROOTS
        from .pipeline import _material_history
        render_id=uuid.uuid4().hex[:8]
        folder = ROOT / 'renders' / pid / render_id
        with _RENDER_LOCK:
            path = render(p,folder,req.preview,progress)
        if not req.preview:
            from .delivery import publish_file
            destination=Path(req.out_dir or default_output()).resolve()/('MV-'+pid)
            path=publish_file(path,destination/('MV-'+render_id+'.mp4'))
            _MEDIA_ROOTS.add(str(destination))
        progress(98,'保存 MV 版本')
        result = dict(path=path,preview=req.preview,created=time.time(),range=p['range'],aspect=p['settings']['aspect'],signature=signature)
        p['renders'].append(result)
        # Check version before publishing history so an obsolete edit cannot overwrite a newer one.
        saved = save(p,version)
        _MEDIA_ROOTS.add(str(folder))
        if not req.preview:
            _material_history(c['src'] for c in p['clips'])
        return {'project':saved,'render':result}
    return launch(work)


@router.get('/projects/{pid}/media')
def media(pid: str, kind: str = 'audio', index: int = 0):
    p = read(pid)
    if kind == 'audio':
        path = p['audio']
    elif kind == 'render' and 0 <= index < len(p['renders']):
        path = p['renders'][index]['path']
    elif kind == 'asset' and 0 <= index < len(p['assets']):
        path = p['assets'][index]['path']
    else:
        raise HTTPException(404,'媒体不存在')
    if not Path(path).is_file():
        raise HTTPException(404,'原始文件已移动或删除，请重新导入')
    return FileResponse(path)
