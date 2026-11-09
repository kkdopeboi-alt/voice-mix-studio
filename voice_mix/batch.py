"""Run independent scripts as one editable batch, with unique output indices."""
from dataclasses import replace
from pathlib import Path
import json
import time

from .pipeline import Pipeline
from .planner import MaterialsExhausted


def validate_scripts(scripts, count):
    if not isinstance(scripts, list) or not 1 <= len(scripts) <= 200:
        raise ValueError('文案数量需在 1～200 条之间')
    if not all(isinstance(s, str) and s.strip() and len(s) <= 20000 for s in scripts):
        raise ValueError('文案不能为空，且每条最多 20000 字符')
    if not isinstance(count, int) or isinstance(count,bool) or not 1 <= count <= 200 or len(scripts)*count > 200:
        raise ValueError('每条生成数量与本次总视频数量均不可超过 200')
    return [s.strip() for s in scripts]


def run_batch(cfg, scripts, progress, preview=False):
    scripts = validate_scripts(scripts,cfg.count)
    rows, variants, failures, used = [], [], [], set()
    variant_settings={}
    start = time.perf_counter()
    for number,script in enumerate(scripts):
        progress('batch',number/len(scripts)*100,f'处理文案 {number+1}/{len(scripts)}')
        child = replace(cfg,script=script,out_dir=str(Path(cfg.out_dir)/f'script_{number+1:03d}'),
                        seed=cfg.seed+number*104729,cover_title='' if len(scripts)>1 else cfg.cover_title)
        def emit(phase,pct,detail=''):
            progress(phase,(number+pct/100)/len(scripts)*100,f'文案 {number+1}/{len(scripts)} · {detail}')
        try:
            result = Pipeline(child,emit,preview_only=preview,used_paths=used).run()
        except MaterialsExhausted:
            # Preserve the existing confirmation flow. Successful prior outputs remain on disk.
            raise
        for row in result['results']:
            row = dict(row,index=number*cfg.count+row['index'],script_number=number+1)
            rows.append(row)
        for v in result['variants']:
            v = dict(v,index=number*cfg.count+v['index'])
            used.update(c['src'] for c in v['clips'])
            variants.append(v)
            variant_settings[str(v['index'])]={'script':script,'cover_title':child.cover_title}
    result = dict(out_dir=cfg.out_dir,initial_preview=preview,ok=sum(r['ok'] for r in rows),
                  total=len(scripts)*cfg.count,seconds=round(time.perf_counter()-start,1),
                  results=rows,variants=variants,scripts=scripts,per_script=cfg.count,variant_settings=variant_settings)
    Path(cfg.out_dir).mkdir(parents=True,exist_ok=True)
    (Path(cfg.out_dir)/'batch-manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
