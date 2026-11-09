"""Native desktop host. Run with python -m voice_mix.desktop."""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from .runtime import VERSION, user_data_dir, settings


class DesktopBridge:
    def __init__(self):
        self._window = None

    def open_browser(self):
        import webbrowser
        from .startup import existing_workbench
        url=existing_workbench(user_data_dir())
        if not url:
            raise RuntimeError('工作台服务尚未就绪')
        return webbrowser.open(url)

    def choose_path(self, kind):
        import webview
        if kind not in {"source-folder", "source-file", "output", "ffmpeg"}:
            raise ValueError("未知的文件选择类型")
        dialog = webview.FileDialog.OPEN if kind == "source-file" else webview.FileDialog.FOLDER
        result = self._window.create_file_dialog(dialog, allow_multiple=False)
        return str(result[0]) if result else None

    def configure_ffmpeg(self):
        folder = self.choose_path("ffmpeg")
        if not folder:
            return False
        extension = ".exe" if sys.platform == "win32" else ""
        if not all((Path(folder) / (name + extension)).is_file() for name in ("ffmpeg", "ffprobe")):
            raise ValueError("此文件夹需要同时包含 ffmpeg 和 ffprobe")
        data = settings()
        data["ffmpeg_dir"] = folder
        root = user_data_dir()
        root.mkdir(parents=True, exist_ok=True)
        temp = root / "settings.tmp"
        temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        temp.replace(root / "settings.json")
        return True

    def open_output(self, path):
        from .server import _MEDIA_ROOTS
        resolved = Path(path).resolve()
        if not resolved.is_dir() or not any(resolved.is_relative_to(Path(root)) for root in _MEDIA_ROOTS):
            raise ValueError("请选择已生成任务的输出目录")
        if sys.platform == "win32":
            os.startfile(str(resolved))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(resolved)])
        else:
            subprocess.Popen(["xdg-open", str(resolved)])
        return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--engine-check", action="store_true")
    parser.add_argument("--report")
    parser.add_argument("--software-rendering",action="store_true")
    parser.add_argument("--browser",action="store_true",help="在系统浏览器中使用本机工作台")
    args = parser.parse_args()
    from .startup import InstanceGuard, LocalService, existing_workbench
    started = time.perf_counter()
    guard = InstanceGuard(user_data_dir())
    if not args.smoke_test and not guard.acquire():
        if args.browser:
            url=existing_workbench(user_data_dir())
            if url:
                import webbrowser
                webbrowser.open(url)
                return 0
        # Repeated double-clicks must not open a second WebView profile/process.
        if sys.platform == 'win32':
            import ctypes
            user32 = ctypes.windll.user32
            user32.FindWindowW.restype = ctypes.c_void_p
            handle = user32.FindWindowW(None, 'VoiceMix Studio')
            if handle:
                user32.ShowWindow(ctypes.c_void_p(handle),9)
                user32.SetForegroundWindow(ctypes.c_void_p(handle))
                return 0
        url=existing_workbench(user_data_dir())
        if url:
            import webbrowser
            webbrowser.open(url)
        return 0
    root = user_data_dir()
    root.mkdir(parents=True,exist_ok=True)
    def log(message):
        with (root/'startup.log').open('a',encoding='utf-8') as stream:
            stream.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} +{time.perf_counter()-started:.3f}s {message}\n')
    service = LocalService()
    try:
        log('starting '+VERSION)
        if args.smoke_test:
            url = service.start()
            from urllib.request import urlopen
            from .assets import FFMPEG, FFPROBE
            from .runtime import default_font
            with urlopen(url+'api/voices',timeout=10) as response:
                metadata = json.load(response)
            with urlopen(url+'api/mv/capabilities',timeout=10) as response:
                caps = json.load(response)
            report = dict(version=VERSION,voices=len(metadata['voices']),font=default_font(),
                          ffmpeg=FFMPEG,ffprobe=FFPROBE,server=True,mv=caps,
                          backend_seconds=round(time.perf_counter()-started,3))
            if args.engine_check:
                import faster_whisper, onnxruntime, yt_dlp, tokenizers
                report['mv_engine_imports'] = True
            if args.report:
                Path(args.report).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            log('smoke complete')
            return 0
        def publish(url):
            from .server import app
            temp=root/'desktop-session.tmp'
            temp.write_text(json.dumps({'url':url,'instance':app.state.instance_id,'version':VERSION}),encoding='utf-8')
            temp.replace(root/'desktop-session.json')
        if args.browser:
            import webbrowser
            from .server import app
            app.state.browser_mode=True
            app.state.browser_exit=service.closed.set
            url=service.start()
            publish(url)
            log('browser workbench ready '+url)
            if not webbrowser.open(url):
                raise RuntimeError('无法打开默认浏览器，请手动访问：'+url)
            while not service.closed.wait(.5):
                pass
            return 0
        if sys.platform=='win32' and args.software_rendering:
            # Keep the app sandbox; only bypass GPU composition for problematic drivers.
            previous=os.environ.get('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS','')
            if '--disable-gpu' not in previous:
                os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS']=(previous+' --disable-gpu').strip()
        import webview
        bridge = DesktopBridge()
        splash = '<!doctype html><meta charset="utf-8"><style>body{background:#101114;color:#e9ebef;font:16px "Segoe UI","Microsoft YaHei",sans-serif;display:grid;place-content:center;height:90vh;text-align:center}h1{color:#c4ef8b;font-size:32px}p{color:#a2acba}small{color:#727c8c}.bar{height:3px;width:240px;background:#30352c;overflow:hidden;margin:20px auto}.bar:after{content:"";display:block;width:40%;height:3px;background:#c4ef8b;animation:load 1.5s infinite}@keyframes load{from{transform:translateX(-100%)}to{transform:translateX(350%)}}</style><h1>VoiceMix Studio</h1><p>正在准备创作工作台…</p><div class="bar"></div><button onclick="window.pywebview.api.open_browser()">在浏览器打开工作台</button><small>正在启动本地剪辑服务，首次打开可能需要稍等。</small>'
        screens=webview.screens if hasattr(webview,'screens') else []
        width=min(1440,max(800,int(screens[0].width*.9))) if screens else 1200
        height=min(940,max(550,int(screens[0].height*.85))) if screens else 780
        log(f'window size {width}x{height}')
        window = webview.create_window('VoiceMix Studio',html=splash,js_api=bridge,
                  width=width,height=height,min_size=(min(900,width),min(600,height)),background_color='#101114',
                  text_select=True,confirm_close=True)
        bridge._window = window
        window.events.closed += lambda: service.closed.set()
        def boot():
            try:
                log('window loop started; initializing backend')
                url = service.start()
                publish(url)
                log('backend ready '+url)
                if not service.closed.is_set():
                    from .server import app
                    app.state.page_ready_callback=lambda:log('workspace initialization confirmed')
                    from .startup import watch_page
                    def recover():
                        log('page readiness timed out; opening compatible browser')
                        try:
                            bridge.open_browser()
                        except Exception as error:
                            log('browser fallback failed: '+str(error))
                    watch_page(app.state.ui_ready,service.closed,recover)
                    log('requesting workspace navigation')
                    window.load_url(url)
                    log('workspace requested')
            except Exception:
                import traceback
                from html import escape
                detail = traceback.format_exc()
                log(detail)
                if not service.closed.is_set():
                    window.load_html('<meta charset="utf-8"><body style="background:#101114;color:#eee;padding:60px;font-family:sans-serif"><h2>工作台未能启动</h2><p>请关闭后重新打开；详细原因已记录：</p><p>'+escape(str(root/'startup.log'))+'</p><pre style="white-space:pre-wrap">'+escape(detail)+'</pre></body>')
        log('starting WebView')
        webview.start(boot,private_mode=False,storage_path=str(root/'webview-safe'),
                      gui='edgechromium' if sys.platform=='win32' else None)
        return 0
    finally:
        service.close()
        guard.close()


if __name__ == "__main__":
    raise SystemExit(main())
