"""Music-first timelines. All lyric times are absolute song seconds."""
from __future__ import annotations

import copy
import difflib
import math
import random
import re
from pathlib import Path

STYLES = {
    'cinema': {'label': '电影叙事', 'shot': 5.0, 'fade': .18, 'filter': 'warm'},
    'mood': {'label': '情绪写真', 'shot': 6.5, 'fade': .35, 'filter': 'soft'},
    'beat': {'label': '节奏混剪', 'shot': 2.5, 'fade': 0, 'filter': 'clear'},
    'stage': {'label': '舞台演唱', 'shot': 7.0, 'fade': .12, 'filter': 'none'},
}
SCENES = [
    ('海边', 'ocean beach waves', '海 海岸 海边 浪 沙滩 自由 远方'),
    ('雨夜', 'rain on a window at night', '雨 泪 潮湿 思念 难过'),
    ('城市', 'city streets at night with lights', '城市 街道 霓虹 灯光 夜晚 人海'),
    ('山野', 'mountains and forest landscape', '山 森林 树 风 自然 自由'),
    ('日出', 'sunrise over the horizon', '日出 清晨 明天 希望 重来 开始 光'),
    ('落日', 'sunset evening sky', '黄昏 落日 夕阳 昨天 回忆 告别'),
    ('远行', 'a person walking along an empty road', '路 远行 走 离开 出发 放下 昨天'),
    ('车站', 'a train at a railway station', '车站 火车 站台 离别 等待 再见'),
    ('相伴', 'two people holding hands together', '你我 相爱 手 拥抱 陪伴 永远 爱'),
    ('独处', 'a lonely person looking out a window', '孤独 一个人 寂寞 沉默 想你 等待'),
    ('家', 'a family together in a warm home', '家 母亲 父亲 孩子 温暖 团圆'),
    ('花', 'flowers blooming in a garden', '花 春 盛开 温柔 美好'),
    ('雪', 'snow falling in winter', '雪 冬 冷 冰'),
    ('星空', 'stars and moon in a night sky', '星 月 夜 梦 宇宙'),
    ('演唱', 'a singer performing with a microphone on stage', '唱 歌 声音 音乐 舞台'),
    ('舞蹈', 'people dancing at a concert', '跳舞 舞动 快乐 热烈 狂欢'),
    ('生活', 'ordinary daily life and small details', '生活 日子 今天 时间 平凡'),
]


def finite(value, name, low=0, high=36000):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{name}必须是数字')
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f'{name}需在 {low}～{high} 之间')
    return number


def units(text):
    return list(text)  # Character timing also permits editing Chinese karaoke.


def timed_words(text, start, end):
    chars = units(text)
    return [{'text': c, 'start': start + (end-start)*i/len(chars),
             'end': start + (end-start)*(i+1)/len(chars)} for i, c in enumerate(chars)]


def parse_lrc(text, duration):
    offset = re.search(r'\[offset:([+-]?\d+)\]', text, re.I)
    shift = int(offset[1]) / 1000 if offset else 0
    stamp = r'(\d{1,3}):(\d{2}(?:\.\d{1,3})?)'
    rows = []
    for raw in text.splitlines():
        stamps = list(re.finditer(r'\[' + stamp + r'\]', raw))
        if not stamps:
            continue
        content = raw[stamps[-1].end():].strip()
        # Enhanced LRC supports <mm:ss.xx> word starts.
        tokens = list(re.finditer(r'<' + stamp + r'>([^<]*)', content))
        clean = re.sub(r'<' + stamp + r'>', '', content).strip()
        for mark in stamps:
            start = int(mark[1])*60 + float(mark[2]) + shift
            if 0 <= start < duration:
                words = [{'text': t[3], 'start': int(t[1])*60 + float(t[2]) + shift} for t in tokens]
                rows.append({'text': clean, 'start': start, 'words': words})
    rows.sort(key=lambda x: x['start'])
    result = []
    for i, row in enumerate(rows):
        row['end'] = min(duration, rows[i+1]['start'] if i+1 < len(rows) else row['start']+8)
        if not row['text'] or row['end'] <= row['start']:
            continue
        explicit = bool(row['words'])
        for j, word in enumerate(row['words']):
            word['end'] = row['words'][j+1]['start'] if j+1 < len(row['words']) else row['end']
        row['words'] = row['words'] or timed_words(row['text'], row['start'], row['end'])
        row.update(review=not explicit, timing='lrc' if explicit else 'lrc-line / estimated-words')
        result.append(row)
    if not result:
        raise ValueError('没有读到有效 LRC 时间标签，请使用 [00:12.30]歌词 格式')
    validate_lyrics(result, duration)
    return result


def align_text(text, recognized, duration):
    lines = [s.strip() for s in text.splitlines() if s.strip()]
    if not lines:
        raise ValueError('请填写歌词，每行一句')
    observed, timing = [], []
    for row in recognized:
        for word in row['words']:
            for char in timed_words(word['text'], word['start'], word['end']):
                if char['text'].isalnum():
                    observed.append(char['text'].lower())
                    timing.append(char)
    target = ''.join(c.lower() for line in lines for c in line if c.isalnum())
    matched = {}
    for block in difflib.SequenceMatcher(None, target, ''.join(observed), autojunk=False).get_matching_blocks():
        for k in range(block.size):
            matched[block.a+k] = timing[block.b+k]
    if len(matched) / max(1, len(target)) < .15:
        raise ValueError('识别结果与提供歌词差异过大，无法可靠对齐。请检查歌曲版本，或导入 LRC 后校正。')
    # Interpolate only unmatched characters between known anchors and mark them.
    anchors = sorted(matched)
    estimated = {}
    for lo, hi in zip([-1]+anchors, anchors+[len(target)]):
        start = matched[lo]['end'] if lo >= 0 else 0
        end = matched[hi]['start'] if hi < len(target) else duration
        count = hi-lo-1
        for j in range(count):
            estimated[lo+1+j] = {'start': start+(end-start)*j/count, 'end': start+(end-start)*(j+1)/count}
    rows, offset = [], 0
    for line in lines:
        n = sum(c.isalnum() for c in line)
        if not n:
            continue
        points = [matched.get(i, estimated.get(i)) for i in range(offset, offset+n)]
        st, en = points[0]['start'], points[-1]['end']
        if en-st < .02:
            raise ValueError('部分歌词无法对齐，请导入 LRC 或调整歌词分行')
        words, j = [], 0
        for c in line:
            p = points[min(j, n-1)]
            if c.isalnum():
                words.append(dict(text=c, start=p['start'], end=p['end']))
                j += 1
            elif words:
                words[-1]['text'] += c
        confidence = sum(i in matched for i in range(offset, offset+n))/n
        rows.append(dict(text=line, start=st, end=en, words=words, review=confidence < .95,
                         timing='asr-aligned', confidence=round(confidence, 2)))
        offset += n
    validate_lyrics(rows, duration)
    return rows


def validate_lyrics(rows, duration):
    if len(rows) > 3000:
        raise ValueError('歌词行数过多')
    last = 0
    for row in rows:
        st = finite(row['start'], '歌词起点', 0, duration)
        en = finite(row['end'], '歌词终点', 0, duration)
        if en <= st or st < last-.005 or not str(row['text']).strip():
            raise ValueError('歌词时间需按顺序且不能重叠，终点必须大于起点')
        if len(row['text']) > 300:
            raise ValueError('单句歌词过长，请分行')
        last, previous = en, st
        for word in row.get('words', []):
            a = finite(word['start'], '字起点', st, en)
            b = finite(word['end'], '字终点', st, en)
            if b < a or a < previous-.005:
                raise ValueError('逐字时间需在本句范围内且按顺序排列')
            previous = b


def concepts(text):
    return {i for i, (_, english, keys) in enumerate(SCENES)
            if any(k in text.lower() for k in keys.split()+english.split())}


def recommendations(duration, rows, energy, seconds=30):
    span = min(seconds, duration)
    starts = {0.0, max(0., duration-span)} | {r['start'] for r in rows if r['start']+span <= duration}
    frequencies = {r['text']: sum(x['text'] == r['text'] for x in rows) for r in rows}
    ranked = []
    for start in starts:
        end = min(duration, start+span)
        subset = [r for r in rows if start <= r['start'] < end]
        samples = energy[int(start*2):max(int(start*2)+1, int(end*2))]
        score = sum(samples)/max(1,len(samples)) + sum(frequencies[r['text']]-1 for r in subset)*.07
        ranked.append(dict(start=round(start,2), end=round(end,2), score=score,
                           reason='综合音量变化与重复歌词推荐；请试听确认', label=subset[0]['text'] if subset else '音乐段落'))
    picks = []
    for item in sorted(ranked, key=lambda x: -x['score']):
        if all(abs(item['start']-x['start']) >= span*.65 for x in picks):
            picks.append(item)
        if len(picks) == 3:
            break
    return picks


def plan(project, history=(), regenerate=False):
    p = copy.deepcopy(project)
    settings = p['settings']
    start, end = p['range']
    assets = [a for a in p['assets'] if a.get('enabled', True)]
    if not assets:
        raise ValueError('请至少勾选一份视频或图片素材')
    rng = random.Random(p.get('seed', 1))
    rows = p['lyrics']
    clips = copy.deepcopy(p.get('clips', [])) if regenerate else []
    if not clips:
        at = start
        nominal = STYLES[settings['style']]['shot']
        if not any(a['image'] for a in assets):
            nominal = min(nominal, max(a['duration'] for a in assets))
        while at < end-.001:
            wanted = min(end, at+nominal)
            boundaries = [r['start'] for r in rows if at+1.2 <= r['start'] <= min(end, wanted+1.2)]
            if boundaries:
                wanted = min(boundaries, key=lambda t: abs(t-wanted))
            if not any(a['image'] for a in assets):
                wanted = min(wanted, at+max(a['duration'] for a in assets))
            if settings['style'] == 'beat':
                beats = [t for t in p.get('beats', []) if at+1 <= t <= min(end, wanted+.5)]
                if beats:
                    wanted = min(beats, key=lambda t: abs(t-wanted))
            if end-wanted < 1 and (any(a['image'] for a in assets) or end-at <= max(a['duration'] for a in assets)):
                wanted = end
            clips.append(dict(id=len(clips), at=at, dur=wanted-at, locked=False))
            at = wanted
    used = set(history) if not settings['allow_reuse'] else set()
    used.update(c['src'] for c in clips if c.get('locked'))
    previous = ''
    for clip in clips:
        if clip.get('locked'):
            previous = clip['src']
            continue
        candidates = [a for a in assets if (a['image'] or a['duration'] >= clip['dur']-.002)
                      and (settings['allow_reuse'] or a['path'] not in used)]
        if not candidates:
            from .planner import MaterialsExhausted
            raise MaterialsExhausted('无可用新素材覆盖该镜头，是否允许使用老素材？也可补充更长视频或图片。')
        lyric = ' '.join(r['text'] for r in rows if r['start'] < clip['at']+clip['dur'] and r['end'] > clip['at'])
        wanted = concepts(lyric)
        if settings['style'] == 'stage':
            wanted.add(14)
        def score(a):
            found = concepts(a.get('tags','')+' '+a['name']) | set(a.get('scene_ids',[]))
            return (len(wanted & found)*4 - (a['path']==previous)*3 - (a['path'] in used)*1.5 + rng.random())
        chosen = max(candidates, key=score)
        found = concepts(chosen.get('tags','')+' '+chosen['name']) | set(chosen.get('scene_ids',[]))
        clip.update(src=chosen['path'], start=0 if chosen['image'] else round(rng.uniform(0,max(0,chosen['duration']-clip['dur'])),3),
                    focal_x=.5, focal_y=.5, filter='inherit', lyric_style='inherit',
                    fallback=not bool(wanted & found), reason='歌词场景匹配' if wanted & found else '意境替代 · 建议检查')
        used.add(chosen['path'])
        previous = chosen['path']
    p['clips'] = clips
    return p


def validate_project(p):
    duration = finite(p['duration'], '歌曲时长', .1, 3600)
    start, end = p['range']
    finite(start,'范围起点',0,duration)
    finite(end,'范围终点',0,duration)
    if end-start < 1:
        raise ValueError('制作范围至少 1 秒')
    s = p['settings']
    for key, allowed in {'style': STYLES, 'aspect': ['9:16','16:9','1:1'],
                         'lyric_style': ['line','karaoke','scroll'], 'filter': ['none','clear','warm','cool','soft','mono']}.items():
        if s[key] not in allowed:
            raise ValueError(f'无效设置：{key}')
    if s.get('resolution','1080p') not in {'1080p','4k'} or s.get('bitrate_mbps',40) not in {20,40,80}:
        raise ValueError('请选择有效导出分辨率与码率')
    finite(s['font_size'], '字号', .015, .10)
    finite(s['lyric_y'], '歌词位置', .15, .90)
    finite(s['mask'], '蒙版透明度', 0, 1)
    for key in ('color', 'highlight'):
        if not re.fullmatch('#[0-9a-fA-F]{6}', s[key]):
            raise ValueError('无效歌词颜色')
    if not Path(s['font']).is_file():
        raise ValueError('字体不可用，请重新选择')
    validate_lyrics(p['lyrics'], duration)
    asset_map = {a['path']:a for a in p['assets']}
    at = start
    if len(p.get('clips',[])) > 1500:
        raise ValueError('镜头数量过多')
    for clip in p.get('clips',[]):
        if clip['src'] not in asset_map:
            raise ValueError('镜头素材必须来自本项目')
        asset = asset_map[clip['src']]
        d = finite(clip['dur'], '镜头时长', 1 if asset['image'] else .1, 3600)
        st = finite(clip['start'], '素材入点', 0, 3600)
        if asset['image'] and st != 0 or not asset['image'] and st+d > asset['duration']+.005:
            raise ValueError('镜头超过素材可用时长')
        if abs(clip['at']-at) > .005:
            raise ValueError('镜头时间轴存在空隙或重叠')
        for key in ('focal_x','focal_y'):
            finite(clip.get(key,.5), '构图中心', 0, 1)
        if clip.get('filter','inherit') not in ['inherit','none','clear','warm','cool','soft','mono']:
            raise ValueError('无效镜头滤镜')
        if clip.get('lyric_style','inherit') not in ['inherit','line','karaoke','scroll']:
            raise ValueError('无效局部歌词样式')
        at += d
    if p.get('clips') and abs(at-end) > .035:
        raise ValueError('镜头总时长必须覆盖所选歌曲范围；可调整相邻镜头分配时长')


def ass_time(t):
    ticks = max(0,round(t*100))
    return f'{ticks//360000}:{ticks//6000%60:02d}:{ticks//100%60:02d}.{ticks%100:02d}'


def ass_text(text):
    return str(text).replace('\\','＼').replace('{','｛').replace('}','｝').replace('\n', r'\N')


def make_ass(p, width, height):
    from PIL import ImageFont
    s = p['settings']
    font = ImageFont.truetype(s['font'], 40)
    family = font.getname()[0].replace(',', '')
    def color(hex_color):
        return '&H00'+hex_color[5:7]+hex_color[3:5]+hex_color[1:3]
    size = max(10, round(height*s['font_size']))
    alpha = round((1-s['mask'])*255)
    header = f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{family},{size},{color(s['highlight'])},{color(s['color'])},&H{alpha if s['mask'] else 0:02X}101010,&H{alpha:02X}000000,-1,0,0,0,100,100,0,0,{3 if s['mask'] else 1},1,0,5,20,20,20,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    events = []
    begin, finish = p['range']
    rows = p['lyrics']
    for i, row in enumerate(rows):
        for clip in p['clips']:
            lo, hi = max(begin,row['start'],clip['at']), min(finish,row['end'],clip['at']+clip['dur'])
            if hi <= lo:
                continue
            mode = clip.get('lyric_style','inherit')
            mode = s['lyric_style'] if mode == 'inherit' else mode
            # Fit every line in its safe area, preserving readable long Chinese lyrics.
            measured = ImageFont.truetype(s['font'], size).getlength(row['text'])
            fit = max(8, min(size, round(size*width*.86/max(1,measured))))
            x,y = width//2, round(height*s['lyric_y'])
            prefix = rf'{{\an5\pos({x},{y})\fs{fit}}}'
            text = ass_text(row['text'])
            if mode == 'karaoke':
                # Absolute kt offsets preserve pauses and partial-line exports.
                chunks = []
                for word in row.get('words') or timed_words(row['text'],row['start'],row['end']):
                    if word['end'] <= lo:
                        chunks.append(r'{\1c'+color(s['highlight'])+r'&}'+ass_text(word['text']))
                    else:
                        t = max(0,round((word['start']-lo)*100))
                        d = max(1,round((word['end']-max(lo,word['start']))*100))
                        chunks.append(r'{\kt'+str(t)+r'\kf'+str(d)+'}'+ass_text(word['text']))
                text = ''.join(chunks)
            else:
                prefix += r'{\1c'+color(s['color'])+'&}'
            if mode == 'scroll':
                prefix = rf'{{\an5\move({x},{y+8},{x},{y},0,250)\fs{fit}}}'
                for j, delta in ((i-1,-1),(i+1,1)):
                    if 0 <= j < len(rows):
                        other = rows[j]['text']
                        width_other = ImageFont.truetype(s['font'],size).getlength(other)
                        fs = max(8,min(round(size*.8),round(size*width*.85/max(1,width_other))))
                        extra = rf'{{\an5\pos({x},{y+delta*size*2})\fs{fs}\alpha&H88&}}'+ass_text(other)
                        events.append(f'Dialogue: 0,{ass_time(lo-begin)},{ass_time(hi-begin)},Main,,0,0,0,,{extra}')
            events.append(f'Dialogue: 1,{ass_time(lo-begin)},{ass_time(hi-begin)},Main,,0,0,0,,{prefix}{text}')
    return header+'\n'.join(events)+'\n'
