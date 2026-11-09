"""Bounded-memory MV renderer: one shot at a time, one uninterrupted music track."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from .assets import FFMPEG
from .runtime import run_process
from .render import esc_filter_path, _resolve_image
from .mv_core import STYLES, make_ass, validate_project


def run(cmd, timeout=3600):
    result = run_process(cmd, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('MV 渲染失败：'+result.stderr.decode('utf-8','replace')[-1800:])


def grade(name):
    return {'none':'null','warm':'eq=contrast=1.04:saturation=1.04:gamma_r=1.025:gamma_b=.98',
            'cool':'eq=contrast=1.04:saturation=.95:gamma_b=1.03',
            'soft':'eq=contrast=.96:brightness=.015:saturation=.94',
            'clear':'eq=contrast=1.08:saturation=1.08',
            'mono':'eq=contrast=1.08:saturation=0'}[name]


def render(project, output, preview, progress):
    validate_project(project)
    if not project['clips']:
        raise ValueError('请先生成镜头方案')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    settings = project['settings']
    w,h = {'9:16':(1080,1920),'16:9':(1920,1080),'1:1':(1080,1080)}[settings['aspect']]
    if not preview and settings.get('resolution','1080p') == '4k':
        w,h = w*2,h*2
    if preview:
        w,h = round(w/3),round(h/3)
    fps = 30
    parts = output.parent / 'mv-parts'
    parts.mkdir(exist_ok=True)
    assets = {a['path']:a for a in project['assets']}
    paths = []
    begin,end = project['range']
    for i,clip in enumerate(project['clips']):
        progress(5+75*i/len(project['clips']),f'制作镜头 {i+1}/{len(project["clips"])}')
        asset = assets[clip['src']]
        stat = Path(clip['src']).stat()
        fade = min(STYLES[settings['style']]['fade'],clip['dur']*.2)
        look = settings['filter'] if clip.get('filter','inherit') == 'inherit' else clip['filter']
        # Cumulative rounding prevents per-shot frame errors from drifting over a full song.
        frames = max(1,round((clip['at']-begin+clip['dur'])*fps)-round((clip['at']-begin)*fps))
        signature = json.dumps([clip,w,h,frames,look,fade,stat.st_size,stat.st_mtime_ns,'mv-hq-v2'],sort_keys=True)
        path = parts / (hashlib.sha256(signature.encode()).hexdigest()[:24]+'.mp4')
        if not path.exists():
            tmp = path.with_suffix('.tmp.mp4')
            cmd = [FFMPEG,'-v','error','-y','-filter_threads','2']
            if asset['image']:
                cmd += ['-loop','1','-framerate',str(fps),'-i',_resolve_image(clip['src'],parts)]
            else:
                cmd += ['-threads','2','-ss',str(clip['start']),'-i',clip['src']]
            x,y = clip.get('focal_x',.5),clip.get('focal_y',.5)
            vf = (f'scale={w}:{h}:force_original_aspect_ratio=increase,'
                  f'crop={w}:{h}:(iw-ow)*{x}:(ih-oh)*{y},setsar=1,fps={fps},'
                  f'tpad=stop_mode=clone:stop_duration=0.1,{grade(look)}')
            if fade:
                vf += f',fade=t=in:d={fade},fade=t=out:st={max(0,frames/fps-fade)}:d={fade}'
            cmd += ['-vf',vf,'-frames:v',str(frames),'-an','-c:v','libx264','-threads','2',
                    '-preset','ultrafast' if preview else 'veryfast','-crf','26' if preview else '12',
                    '-pix_fmt','yuv420p','-video_track_timescale','90000',str(tmp)]
            try:
                run(cmd)
                tmp.replace(path)
            finally:
                tmp.unlink(missing_ok=True)
        paths.append(path)
    listing = output / 'segments.txt'
    # Generated cache filenames are hex-only; avoid user paths in concat grammar.
    listing.write_text(''.join("file '../mv-parts/"+p.name+"'\n" for p in paths),encoding='utf-8')
    ass = output / 'lyrics.ass'
    ass.write_text(make_ass(project,w,h),encoding='utf-8-sig')
    # Copy exactly the chosen font into an isolated fontsdir for predictable libass lookup.
    import shutil
    fonts = output / 'fonts'
    fonts.mkdir(exist_ok=True)
    shutil.copy2(settings['font'],fonts/Path(settings['font']).name)
    video = output / ('MV-preview.mp4' if preview else 'MV.mp4')
    progress(84,'合成完整歌曲与歌词；滤镜仅作用于画面')
    vf = f"ass='{esc_filter_path(ass)}':fontsdir='{esc_filter_path(fonts)}',format=yuv420p"
    audio = ['-af',f'afade=t=in:d=0.12,afade=t=out:st={max(0,end-begin-.25)}:d=0.25'] if begin>0 or end<project['duration']-.01 else []
    bitrate = int(settings.get('bitrate_mbps',40))
    encoding = ['-preset','ultrafast','-crf','25'] if preview else ['-preset','medium','-b:v',f'{bitrate}M','-minrate',f'{bitrate}M','-maxrate',f'{bitrate}M','-bufsize',f'{bitrate*2}M','-x264-params','nal-hrd=cbr:force-cfr=1']
    cmd = [FFMPEG,'-v','error','-y','-filter_threads','2','-f','concat','-safe','0','-i',str(listing),
           '-ss',str(begin),'-i',project['audio'],'-map','0:v:0','-map','1:a:0',
           '-vf',vf,*audio,'-t',str(end-begin),'-c:v','libx264','-threads','2',
           *encoding,
           '-c:a','aac','-b:a','320k','-ar','48000','-movflags','+faststart',str(video)]
    run(cmd)
    (output/'project.json').write_text(json.dumps(project,ensure_ascii=False,indent=2),encoding='utf-8')
    return str(video.resolve())
