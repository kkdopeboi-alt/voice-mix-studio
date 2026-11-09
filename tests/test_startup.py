import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch
import io
import json

from voice_mix.startup import InstanceGuard,LocalService,existing_workbench,watch_page


class StartupTests(unittest.TestCase):
    def test_bridge_never_exposes_native_window_tree(self):
        from voice_mix.desktop import DesktopBridge
        class NativeWindow:
            def __dir__(self):
                raise AssertionError('native window tree must never be inspected')
        bridge=DesktopBridge()
        bridge._window=NativeWindow()
        exported=[name for name in dir(bridge) if not name.startswith('_')]
        self.assertNotIn('window',exported)
        self.assertTrue(all(callable(getattr(bridge,name)) for name in exported))

    def test_browser_reuse_checks_loopback_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'desktop-session.json'
            path.write_text(json.dumps({'url':'http://127.0.0.1:12345/','instance':'test'}),encoding='utf-8')
            body=json.dumps({'app':'VoiceMix Studio','instance':'test'}).encode()
            with patch('urllib.request.urlopen',return_value=io.BytesIO(body)):
                self.assertEqual(existing_workbench(folder),'http://127.0.0.1:12345/')
            with patch('urllib.request.urlopen',return_value=io.BytesIO(b'{"instance":"different"}')):
                self.assertIsNone(existing_workbench(folder))
            path.write_text(json.dumps({'url':'https://example.com/','instance':'test'}),encoding='utf-8')
            with patch('urllib.request.urlopen') as request:
                self.assertIsNone(existing_workbench(folder));request.assert_not_called()

    def test_page_timeout_and_ready_close_suppression(self):
        calls=[]
        ready,closed=threading.Event(),threading.Event()
        worker=watch_page(ready,closed,lambda:calls.append('fallback'),.02)
        worker.join(1)
        self.assertEqual(calls,['fallback'])
        for event in (ready,closed):
            ready.clear();closed.clear();event.set();calls.clear()
            watch_page(ready,closed,lambda:calls.append('fallback'),.02).join(1)
            self.assertEqual(calls,[])

    def test_page_ready_requires_current_instance(self):
        from fastapi.testclient import TestClient
        from voice_mix.server import app
        client=TestClient(app)
        app.state.ui_ready.clear()
        self.assertEqual(client.post('/api/desktop/ready',json={'instance':'old'}).status_code,409)
        self.assertFalse(app.state.ui_ready.is_set())
        self.assertEqual(client.post('/api/desktop/ready',json={'instance':app.state.instance_id}).status_code,200)
        self.assertTrue(app.state.ui_ready.is_set())
        app.state.ui_ready.clear()

    def test_instance_lock_released_on_close(self):
        with tempfile.TemporaryDirectory() as folder:
            first,second=InstanceGuard(folder),InstanceGuard(folder)
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            first.close()
            self.assertTrue(second.acquire())
            second.close()

    def test_closed_service_never_binds_or_starts_thread(self):
        service=LocalService()
        service.close()
        with self.assertRaises(RuntimeError):service.start()
        self.assertIsNone(service.thread)

    def test_window_and_gui_loop_precede_backend_start(self):
        from voice_mix import desktop
        order=[]
        class Event:
            def __iadd__(self, callback):return self
        class Window:
            events=types.SimpleNamespace(closed=Event())
            def load_url(self,url):order.append('url')
        class Service:
            def __init__(self):self.closed=threading.Event()
            def start(self):order.append('backend');return 'http://127.0.0.1:1234/'
            def close(self):self.closed.set();order.append('close')
        def create(*args,**kwargs):
            self.assertIn('正在准备',kwargs['html'])
            order.append('window');return Window()
        def gui(boot,**kwargs):order.append('gui');boot()
        fake=types.SimpleNamespace(create_window=create,start=gui)
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(sys,'argv',['app']),patch.object(desktop,'user_data_dir',return_value=Path(folder)),patch.dict(sys.modules,{'webview':fake}),patch('voice_mix.startup.LocalService',Service):
                self.assertEqual(desktop.main(),0)
        self.assertEqual(order,['window','gui','backend','url','close'])


if __name__=='__main__':unittest.main()
