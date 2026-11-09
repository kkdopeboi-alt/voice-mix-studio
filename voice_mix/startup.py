"""Small, testable startup primitives; no GUI or ML imports."""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import json
from pathlib import Path


def watch_page(ready, closed, on_timeout, timeout=15):
    """Monitor actual page initialization without blocking the native GUI loop."""
    def run():
        deadline=time.monotonic()+timeout
        while not closed.wait(.05):
            if ready.is_set():
                return
            if time.monotonic() >= deadline:
                if not closed.is_set():
                    on_timeout()
                return
    worker=threading.Thread(target=run,daemon=True)
    worker.start()
    return worker


def existing_workbench(root):
    """Only reuse the loopback server whose random identity matches our registry."""
    from urllib.parse import urlsplit
    from urllib.request import urlopen
    try:
        session=json.loads((Path(root)/'desktop-session.json').read_text(encoding='utf-8'))
        url=session['url']
        parsed=urlsplit(url)
        if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or parsed.path!='/':
            return None
        with urlopen(url+'api/health',timeout=2) as response:
            data=json.load(response)
        return url if data.get('app')=='VoiceMix Studio' and data.get('instance')==session['instance'] else None
    except (OSError,ValueError,KeyError,TypeError):
        return None


class InstanceGuard:
    """An OS lock is released even if the previous application crashed."""
    def __init__(self, root):
        self.path = Path(root) / 'desktop.lock'
        self.file = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file = self.path.open('a+b')
        file.seek(0,2)
        if not file.tell():
            file.write(b'0'); file.flush()
        file.seek(0)
        try:
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            file.close()
            return False
        self.file = file
        return True

    def close(self):
        if self.file:
            self.file.close()
            self.file = None


class LocalService:
    def __init__(self):
        self.server = self.listener = self.thread = None
        self.closed = threading.Event()
        self.lock = threading.Lock()

    def start(self, timeout=45):
        from .server import app
        import uvicorn
        with self.lock:
            if self.closed.is_set():
                raise RuntimeError('窗口已关闭')
            listener = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
            try:
                listener.bind(('127.0.0.1',0))
                listener.listen(128)
                self.listener = listener
                self.server = uvicorn.Server(uvicorn.Config(app,log_config=None,log_level='warning'))
                self.thread = threading.Thread(target=self.server.run,kwargs={'sockets':[listener]},daemon=True)
                self.thread.start()
                port = listener.getsockname()[1]
            except BaseException:
                listener.close()
                raise
        deadline = time.monotonic()+timeout
        while not self.server.started:
            if self.closed.wait(.025) or not self.thread.is_alive():
                raise RuntimeError('本地服务已停止')
            if time.monotonic()>deadline:
                self.close()
                raise RuntimeError('本地服务启动超时，请查看 startup.log')
        return f'http://127.0.0.1:{port}/'

    def close(self):
        self.closed.set()
        with self.lock:
            if self.server:
                self.server.should_exit = True
            if self.thread:
                self.thread.join(timeout=3)
            if self.listener:
                self.listener.close()
