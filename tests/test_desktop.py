import os
import tempfile
import unittest
from pathlib import Path

_temporary = tempfile.TemporaryDirectory()
os.environ["VOICE_MIX_DATA_DIR"] = _temporary.name

from fastapi.testclient import TestClient
from voice_mix.server import app
from voice_mix.config import JobConfig
from voice_mix.planner import Planner, MaterialsExhausted
from voice_mix.assets import Asset
from voice_mix.runtime import DATA_DIR


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_shell_and_assets_are_packaged(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.headers['cache-control'],'no-store')
        from voice_mix.runtime import VERSION
        self.assertEqual(page.headers['x-voicemix-version'],VERSION)
        for asset in ("/studio.js", "/studio.css"):
            self.assertEqual(self.client.get(asset).status_code, 200)
        metadata = self.client.get("/api/voices").json()
        self.assertTrue(metadata["default_output"])
        self.assertGreater(len(metadata["voices"]), 0)

    def test_projects_survive_client_restart(self):
        projects = [{"name": "测试项目", "values": {"script": "文案"}, "jobs": []}]
        self.assertEqual(self.client.put("/api/projects", json={"projects": projects}).status_code, 200)
        with TestClient(app) as other:
            self.assertEqual(other.get("/api/projects").json()["projects"], projects)
        self.assertTrue((DATA_DIR / "projects.json").is_file())

    def test_foreign_origin_cannot_write_projects(self):
        response = self.client.put("/api/projects", json={"projects": []}, headers={"origin": "https://example.com"})
        self.assertEqual(response.status_code, 403)

    def test_picture_minimum_and_no_reuse(self):
        asset = Asset(path="image.png", duration=1, width=400, height=600, fps=0,
                      has_audio=False, size=100, group="", name="image.png", is_image=True)
        cfg = JobConfig(img_dur=1, count=1, allow_reuse=True)
        v = Planner(cfg, [asset]).build(1, ["audio.mp3"], [4], [cfg.voice], [[]], [""])[0]
        self.assertTrue(all(c.dur >= 1 for c in v.clips))
        self.assertGreaterEqual(v.total_dur, 4.2)
        cfg.allow_reuse = False
        with self.assertRaises(MaterialsExhausted):
            Planner(cfg, [asset]).build(1, ["audio.mp3"], [4], [cfg.voice], [[]], [""])


if __name__ == "__main__":
    unittest.main()
