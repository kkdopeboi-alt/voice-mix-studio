import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from voice_mix.delivery import deliver
from voice_mix.mv_core import background_plan, validate_project
from voice_mix.mv_api import download_error
from voice_mix.planner import MaterialsExhausted
from test_mv import fixture


class DeliveryTests(unittest.TestCase):
    def test_batch_flattens_and_cover_is_optional(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'working';source.mkdir()
            video=source/'video.mp4';video.write_bytes(b'video')
            cover=source/'cover.jpg';cover.write_bytes(b'cover')
            (source/'manifest.json').write_text('private')
            result={'results':[{'index':0,'ok':True,'path':str(video),'cover':str(cover)},
                               {'index':2,'ok':True,'path':str(video)}]}
            deliver(result,root/'export')
            self.assertEqual({p.name for p in (root/'export').iterdir()},
                             {'video_001.mp4','video_001-cover.jpg','video_003.mp4'})
            self.assertEqual((root/'export/video_001.mp4').read_bytes(),b'video')
            result['results'][0]['cover']=''
            deliver(result,root/'export')
            self.assertFalse((root/'export/video_001-cover.jpg').exists())

    def test_cached_tts_keeps_timings_and_skips_network(self):
        from voice_mix.tts import synth_narration, Sentence
        with tempfile.TemporaryDirectory() as tmp:
            def fake(sentences,voice,path,*args):
                Path(path).write_bytes(b'audio');return [{'text':'hello','start':.2,'end':1.2}],1.5
            with patch('voice_mix.runtime.DATA_DIR',Path(tmp)),patch('voice_mix.tts._synth_narration_uncached',side_effect=fake) as engine:
                a=synth_narration([Sentence('hello',5)],'test',str(Path(tmp)/'a.mp3'))
                b=synth_narration([Sentence('hello',5)],'test',str(Path(tmp)/'b.mp3'))
                self.assertEqual(a,b);self.assertEqual(engine.call_count,1)
                self.assertEqual((Path(tmp)/'a.mp3').read_bytes(),(Path(tmp)/'b.mp3').read_bytes())

    def test_background_trim_reuse_and_framing(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=fixture(tmp)
            p['assets']=[dict(path='background.mp4',name='background',image=False,duration=10,enabled=True)]
            bg=dict(path='background.mp4',start=2,end=5,focal_x=.4,focal_y=.7)
            result=background_plan(p,bg)
            validate_project(result)
            self.assertEqual([c['start'] for c in result['clips']],[2,2])
            self.assertEqual(result['clips'][0]['focal_y'],.7)
            p['settings']['allow_reuse']=False
            with self.assertRaises(MaterialsExhausted):background_plan(p,bg)
            with self.assertRaises(ValueError):background_plan(p,dict(bg,end=2))

    def test_login_diagnostics_and_credential_validation(self):
        from voice_mix.server import app
        self.assertIn('登录验证',download_error(Exception('Sign in to confirm you’re not a bot')))
        self.assertIn('无法读取',download_error(Exception('Could not copy Chrome cookie database')))
        client=TestClient(app)
        self.assertEqual(client.post('/api/mv/download',json={'url':'https://example.com','browser':'invalid'}).status_code,400)
        self.assertEqual(client.post('/api/mv/download',json={'url':'https://example.com','cookie_id':'../a'}).status_code,400)
        self.assertEqual(client.post('/api/mv/cookies',content=b'not a cookie file').status_code,400)
        self.assertEqual(client.get('/api/mv/imports/invalid/media?name=../private').status_code,404)

    def test_mv_requires_preview_of_current_settings(self):
        from voice_mix.mv_api import export, RenderRequest, preview_signature
        from fastapi import HTTPException
        with tempfile.TemporaryDirectory() as tmp:
            p=fixture(tmp);p['version']=1;p['renders']=[]
            with patch('voice_mix.mv_api.read',return_value=p):
                with self.assertRaises(HTTPException):export('test',RenderRequest(preview=False))
                p['renders']=[{'preview':True,'signature':preview_signature(p)}]
                with patch('voice_mix.mv_api.launch',return_value={'task_id':'test'}):
                    self.assertEqual(export('test',RenderRequest(preview=False)),{'task_id':'test'})
                p['settings']['filter']='cream'
                with self.assertRaises(HTTPException):export('test',RenderRequest(preview=False))

    def test_export_snapshot_preserves_edits_and_quality(self):
        from voice_mix.server import api_export, ExportReq
        from voice_mix.config import JobConfig
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=fixture(tmp)
            cfg=JobConfig(script='hello',src_dir=tmp,out_dir=tmp,export_dir=str(root/'export'),cover_template='none')
            variant=dict(index=3,clips=[dict(src=p['assets'][0]['path'],start=0,dur=2,mirror=False,motion='in')],
                         total_dur=2,narration='narration.mp3',narration_dur=1,voice=cfg.voice,subs=[],title='Edited',overlap=0)
            # Reflect the actual schema without forcing a new plan or TTS request.
            from voice_mix.planner import Variant
            import inspect
            variant={k:v for k,v in variant.items() if k in inspect.signature(Variant).parameters}
            state=dict(status='done',config=cfg,result=dict(variants=[variant],variant_settings={'3':{'video_filter':'film'}}))
            observed=[]
            def renderer(config,variants,out,parts,assets,**kwargs):
                observed.append((config,variants[0]))
                out.mkdir(parents=True,exist_ok=True);path=out/'result.mp4';path.write_bytes(b'high-quality')
                return [dict(index=3,ok=True,path=str(path))]
            def start(jid,config,run):return run(lambda *a:None)
            with patch('voice_mix.server._get_job',return_value=state),patch('voice_mix.server._start_job',side_effect=start),patch('voice_mix.server.render_batch',side_effect=renderer),patch('voice_mix.server._material_history'),patch('voice_mix.server.DATA_DIR',root):
                result=api_export('test',ExportReq())
            self.assertEqual((observed[0][0].width,observed[0][0].height,observed[0][0].crf),(1080,1920,16))
            self.assertEqual(observed[0][0].video_filter,'film')
            self.assertEqual(observed[0][1].title,'Edited')
            self.assertEqual({p.name for p in (root/'export').iterdir()},{'video_004.mp4'})


if __name__=='__main__':unittest.main()
