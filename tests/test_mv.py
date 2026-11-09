import copy
import math
import tempfile
import unittest
import wave
from pathlib import Path

from voice_mix.mv_core import (parse_lrc, align_text, plan, validate_project, make_ass,
                               recommendations, timed_words)
from voice_mix.runtime import default_font
from voice_mix.planner import MaterialsExhausted


def fixture(root):
    from PIL import Image
    root = Path(root)
    for name, color in [('sunrise',(200,140,70)),('rain',(50,90,140))]:
        Image.new('RGB',(640,480),color).save(root/(name+'.png'))
    audio = root/'music.wav'
    import struct
    with wave.open(str(audio),'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
        wav.writeframes(b''.join(struct.pack('<h',int(3000*math.sin(2*math.pi*220*i/16000))) for i in range(16000*6)))
    return dict(id='test',name='测试 MV',audio=str(audio),duration=6.,range=[0.,6.],seed=1,
                settings=dict(style='cinema',aspect='9:16',lyric_style='line',filter='warm',font=default_font(),
                              font_size=.035,color='#ffffff',highlight='#c4ef8b',lyric_y=.78,mask=.2,allow_reuse=True),
                lyrics=parse_lrc('[00:01.00]清晨看见新的光\n[00:03.00]雨落在城市窗前\n[00:05.00]',6),
                assets=[dict(path=str(root/(name+'.png')),name=name+'.png',image=True,duration=3,enabled=True,
                             tags=tags,scene_ids=[]) for name,tags in [('sunrise','日出 希望'),('rain','雨夜 城市')]],clips=[])


class LyricsTests(unittest.TestCase):
    def test_lrc_offset_repeat_and_instrumental_gap(self):
        rows = parse_lrc('[offset:100]\n[00:01.00][00:05.00]同一句\n[00:03.00]\n[00:07.00]',9)
        self.assertEqual(len(rows),2)
        self.assertAlmostEqual(rows[0]['start'],1.1)
        self.assertAlmostEqual(rows[0]['end'],3.1)
        self.assertTrue(rows[0]['review'])

    def test_enhanced_lrc_preserves_word_times(self):
        rows=parse_lrc('[00:01.00]<00:01.00>你<00:02.00>好\n[00:03.00]',5)
        self.assertEqual(rows[0]['words'][1]['start'],2)
        self.assertFalse(rows[0]['review'])

    def test_plain_lyrics_match_recognized_timing(self):
        rec=[dict(text='你好世界',start=2,end=6,words=timed_words('你好世界',2,6))]
        rows=align_text('你好\n世界',rec,8)
        self.assertEqual([r['text'] for r in rows],['你好','世界'])
        self.assertEqual((rows[0]['start'],rows[1]['end']),(2,6))
        self.assertFalse(rows[0]['review'])
        with self.assertRaises(ValueError):
            align_text('完全不同的内容',rec,8)

    def test_recommendations_stay_inside_short_song(self):
        picks=recommendations(8,[],[.5]*16)
        self.assertEqual(picks[0]['start'],0)
        self.assertEqual(picks[0]['end'],8)


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.p=fixture(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_cover_whole_music_and_lock_partial_regeneration(self):
        p=plan(self.p)
        self.assertAlmostEqual(sum(c['dur'] for c in p['clips']),6)
        p['clips'][0]['locked']=True
        locked=copy.deepcopy(p['clips'][0])
        p['seed']+=1
        revised=plan(p,regenerate=True)
        self.assertEqual(revised['clips'][0],locked)
        validate_project(revised)

    def test_no_reuse_and_history_exhaustion(self):
        self.p['settings']['allow_reuse']=False
        with self.assertRaises(MaterialsExhausted):
            plan(self.p,[a['path'] for a in self.p['assets']])

    def test_short_video_can_fill_without_overrun(self):
        self.p['assets']=[dict(path='test.mp4',name='短视频',image=False,duration=2,enabled=True,tags='')]
        p=plan(self.p)
        self.assertTrue(all(c['dur']<=2 for c in p['clips']))
        self.assertAlmostEqual(sum(c['dur'] for c in p['clips']),6)

    def test_invalid_word_and_gap_rejected(self):
        p=plan(self.p)
        p['lyrics'][0]['words'][0]['start']=float('nan')
        with self.assertRaises(ValueError):validate_project(p)
        p=plan(self.p)
        p['clips'][0]['at']=.5
        with self.assertRaises(ValueError):validate_project(p)

    def test_ass_escapes_tags_and_karaoke_partial_range(self):
        p=plan(self.p)
        p['settings']['lyric_style']='karaoke'
        p['lyrics'][0]['text']='{\\pos(0,0)}'
        p['lyrics'][0]['words']=timed_words(p['lyrics'][0]['text'],1,3)
        ass=make_ass(p,360,640)
        self.assertIn('\\kf',ass)
        self.assertIn('｛',ass)
        self.assertNotIn('{\\pos(0,0)}',ass)


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.p=fixture(self.temp.name)
        from fastapi.testclient import TestClient
        from voice_mix.server import app
        from voice_mix import mv_api
        self.api=mv_api
        self.original_root=mv_api.ROOT
        mv_api.ROOT=Path(self.temp.name)/'store';mv_api.ROOT.mkdir()
        self.client=TestClient(app)

    def tearDown(self):
        self.api.ROOT=self.original_root
        self.temp.cleanup()

    def test_project_restart_conflict_and_media(self):
        res=self.client.post('/api/mv/projects',json=dict(name='歌曲测试',audio=self.p['audio'],
             source_paths=[a['path'] for a in self.p['assets']],lyrics='[00:01]清晨',lyric_input='lrc',visual_analysis=False))
        self.assertEqual(res.status_code,200,res.text)
        p=res.json();pid=p['id']
        restored=self.client.get('/api/mv/projects/'+pid).json()
        self.assertEqual(restored['audio'],self.p['audio'])
        update=dict(version=p['version'],project={'name':'新名称'})
        self.assertEqual(self.client.put('/api/mv/projects/'+pid,json=update).status_code,200)
        self.assertEqual(self.client.put('/api/mv/projects/'+pid,json=update).status_code,400)
        self.assertEqual(self.client.get('/api/mv/projects/'+pid+'/media').status_code,200)
        self.assertEqual(self.client.get('/api/mv/projects/'+pid+'/media?kind=asset&index=99').status_code,404)

    def test_upload_and_bad_lyrics(self):
        response=self.client.post('/api/mv/upload?name=../../test.exe',content=b'abc')
        self.assertEqual(response.status_code,400)
        with self.assertRaises(ValueError):self.api.public_url('file:///secret.txt')
        with self.assertRaises(ValueError):self.api.public_url('http://127.0.0.1/private')


if __name__=='__main__':unittest.main()
