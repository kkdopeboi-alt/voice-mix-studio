"""Lazy local model adapters. Media stays on this computer."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .assets import FFMPEG
from .runtime import DATA_DIR, run_process
from .mv_core import SCENES

MODEL_DIR = DATA_DIR / '_mv_models'


def transcribe(path, progress, model_name='base'):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError('缺少歌词识别组件，请安装带 MV 引擎的版本，或安装项目的 [mv] 依赖；LRC 导入仍可使用')
    if model_name not in {'tiny','base','small'}:
        raise ValueError('无效识别模型')
    progress(8, '准备本地歌词识别模型；首次使用需要下载，之后离线运行')
    model = WhisperModel(model_name, device='cpu', compute_type='int8', cpu_threads=2,
                         num_workers=1, download_root=str(MODEL_DIR / 'whisper'))
    # Decode through the same FFmpeg installation as rendering. This avoids PyAV
    # version-specific audio APIs and accepts all supported music containers.
    import numpy as np
    decoded = run_process([FFMPEG,'-v','error','-i',str(path),'-vn','-ac','1','-ar','16000',
                           '-f','f32le','pipe:1'],capture_output=True,timeout=300)
    if decoded.returncode or not decoded.stdout:
        raise ValueError('音乐无法解码，请检查文件')
    audio = np.frombuffer(decoded.stdout,dtype='<f4').copy()
    segments, info = model.transcribe(audio, beam_size=3, word_timestamps=True,
                                      vad_filter=False, condition_on_previous_text=False)
    rows = []
    for segment in segments:
        progress(12+40*segment.end/max(1,info.duration), '识别演唱与逐字时间；歌曲伴奏可能影响准确度')
        words = []
        last = max(0, segment.start)
        for word in segment.words or []:
            start = max(last, word.start)
            end = max(start, min(info.duration, word.end))
            words.append(dict(text=word.word, start=start, end=end))
            last = end
        if not words or not segment.text.strip() or segment.end <= segment.start:
            continue
        # Mark machine timings for review; recognition is not forced alignment.
        rows.append(dict(text=segment.text.strip(), start=words[0]['start'], end=words[-1]['end'],
                         words=words, review=True, timing='asr', confidence=round(1-segment.no_speech_prob,2)))
    del model
    if not rows:
        raise ValueError('没有识别到可用歌词，请尝试更清晰的人声版本或导入 LRC')
    # Whisper can overlap segment boundaries. Trim to the next start.
    for row, nxt in zip(rows, rows[1:]):
        row['end'] = min(row['end'], nxt['start'])
        row['words'] = [dict(w, end=min(w['end'],row['end'])) for w in row['words'] if w['start'] < row['end']]
    return [r for r in rows if r['end'] > r['start']]


def audio_features(path):
    import numpy as np
    result = run_process([FFMPEG,'-v','error','-i',str(path),'-vn','-ac','1','-ar','8000',
                          '-f','f32le','pipe:1'], capture_output=True, timeout=300)
    if result.returncode:
        raise ValueError('音乐无法解码')
    data = np.frombuffer(result.stdout, dtype='<f4')
    if not len(data):
        raise ValueError('音乐文件没有音频')
    def rms(hop):
        n = int(np.ceil(len(data)/hop))
        padded = np.pad(data, (0,n*hop-len(data)))
        values = np.sqrt(np.mean(padded.reshape(n,hop)**2,axis=1))
        return values / max(float(values.max()),1e-6)
    energy = rms(4000)
    fine = rms(400)
    changes = np.maximum(0,np.diff(fine,prepend=0))
    threshold = max(.03,float(np.quantile(changes,.8)))
    beats = []
    for i in range(1,len(fine)-1):
        t = i*.05
        if changes[i] >= threshold and changes[i] >= changes[i-1] and changes[i] > changes[i+1] and (not beats or t-beats[-1] >= .3):
            beats.append(round(t,3))
    waveform = rms(max(1,int(np.ceil(len(data)/700))))
    return energy.round(4).tolist(), beats, waveform.round(4).tolist()


def tag_visuals(assets, progress):
    """Zero-shot scene categories on sampled frames, not identity recognition."""
    import numpy as np
    import onnxruntime as ort
    from tokenizers import Tokenizer
    from huggingface_hub import hf_hub_download
    from PIL import Image, ImageOps
    from .render import _resolve_image
    cache = DATA_DIR / '_mv_visual_cache'
    cache.mkdir(parents=True, exist_ok=True)
    pending = []
    for a in assets:
        stat = Path(a['path']).stat()
        key = hashlib.sha256(f"{a['path']}:{stat.st_size}:{stat.st_mtime_ns}:clip-v1".encode()).hexdigest()
        file = cache / (key+'.json')
        if file.exists():
            a['scene_ids'] = json.loads(file.read_text())
        else:
            pending.append((a,file))
    if not pending:
        return
    progress(8, '准备本地画面分析模型；首次下载约 155 MB，可关闭画面分析改用素材标签')
    repo = 'Xenova/clip-vit-base-patch32'
    def fetch(name):
        return hf_hub_download(repo,name,cache_dir=str(MODEL_DIR/'clip'))
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 2
    opts.inter_op_num_threads = 1
    text_session = ort.InferenceSession(fetch('onnx/text_model_quantized.onnx'), opts, providers=['CPUExecutionProvider'])
    tokenizer = Tokenizer.from_file(fetch('tokenizer.json'))
    tokenizer.enable_padding(pad_id=49407, pad_token='<|endoftext|>',length=77)
    tokenizer.enable_truncation(max_length=77)
    batch = tokenizer.encode_batch(['a photo of '+english for _,english,_ in SCENES])
    inputs = {'input_ids':np.array([x.ids for x in batch],dtype=np.int64),
              'attention_mask':np.array([x.attention_mask for x in batch],dtype=np.int64)}
    text_vectors = text_session.run(None,{i.name:inputs[i.name] for i in text_session.get_inputs()})[0]
    text_vectors /= np.maximum(np.linalg.norm(text_vectors,axis=-1,keepdims=True),1e-9)
    del text_session
    vision = ort.InferenceSession(fetch('onnx/vision_model_quantized.onnx'),opts,providers=['CPUExecutionProvider'])
    mean = np.array([.48145466,.4578275,.40821073],dtype=np.float32)
    std = np.array([.26862954,.26130258,.27577711],dtype=np.float32)
    for index,(asset,file) in enumerate(pending):
        progress(20+70*index/max(1,len(pending)), f"分析画面 {index+1}/{len(pending)}：{asset['name']}")
        images = []
        if asset['image']:
            with Image.open(_resolve_image(asset['path'],cache)) as im:
                images.append(ImageOps.exif_transpose(im).convert('RGB'))
        else:
            import io
            for ratio in (.2,.5,.8):
                result = run_process([FFMPEG,'-v','error','-ss',str(asset['duration']*ratio),'-i',asset['path'],
                                      '-frames:v','1','-vf','scale=320:-1','-f','image2pipe','-c:v','mjpeg','pipe:1'],capture_output=True,timeout=90)
                if result.returncode == 0 and result.stdout:
                    images.append(Image.open(io.BytesIO(result.stdout)).convert('RGB'))
        scores = []
        for im in images:
            scaled = ImageOps.fit(im,(224,224),method=Image.Resampling.BICUBIC)
            pixels = ((np.asarray(scaled,dtype=np.float32)/255-mean)/std).transpose(2,0,1)[None]
            vectors = vision.run(None,{'pixel_values':pixels})[0]
            vectors /= np.maximum(np.linalg.norm(vectors,axis=-1,keepdims=True),1e-9)
            scores.append((vectors@text_vectors.T)[0])
        if scores:
            values = np.max(scores,axis=0)
            asset['scene_ids'] = [int(i) for i in np.argsort(values)[-2:][::-1] if values[i] > .20]
        else:
            asset['scene_ids'] = []
        file.write_text(json.dumps(asset['scene_ids']),encoding='utf-8')
    del vision
