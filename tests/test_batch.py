import tempfile
import unittest
from unittest.mock import patch

from voice_mix.batch import validate_scripts, run_batch
from voice_mix.config import JobConfig


class BatchTests(unittest.TestCase):
    def test_limits_and_trim(self):
        self.assertEqual(validate_scripts([' a ', 'b'], 2), ['a','b'])
        for scripts,count in [([],1),([''],1),(['x']*10,21),(['x'],0),(['x'],True),('x',1)]:
            with self.assertRaises(ValueError):validate_scripts(scripts,count)

    def test_unique_indices_and_script_output_mapping(self):
        with tempfile.TemporaryDirectory() as root:
            cfg=JobConfig(script='first',count=2,out_dir=root)
            calls=[]
            class FakePipeline:
                def __init__(self,cfg,progress,preview_only,used_paths):
                    self.cfg=cfg;calls.append((cfg,preview_only,set(used_paths)))
                def run(self):
                    return dict(results=[dict(index=i,ok=True) for i in range(2)],
                                variants=[dict(index=i,clips=[dict(src='used.png')]) for i in range(2)])
            with patch('voice_mix.batch.Pipeline',FakePipeline):
                result=run_batch(cfg,['first','second','third'],lambda *args:None,True)
            self.assertEqual([r['index'] for r in result['results']],list(range(6)))
            self.assertEqual([r['script_number'] for r in result['results']],[1,1,2,2,3,3])
            self.assertEqual([c[0].script for c in calls],['first','second','third'])
            self.assertEqual(len({c[0].out_dir for c in calls}),3)
            self.assertIn('used.png',calls[1][2])
            self.assertEqual((result['ok'],result['total']),(6,6))

    def test_reject_batch_before_background_task(self):
        from fastapi.testclient import TestClient
        from voice_mix.server import app
        response=TestClient(app).post('/api/generate',json={'config':{'batch_scripts':['']}})
        self.assertEqual(response.status_code,400)


if __name__=='__main__':unittest.main()
