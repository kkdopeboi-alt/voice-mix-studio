"""PyInstaller entry point."""
import multiprocessing
import sys
import traceback

if __name__ == "__main__":
    multiprocessing.freeze_support()
    try:
        from voice_mix.desktop import main
        raise SystemExit(main())
    except Exception:
        from voice_mix.runtime import user_data_dir
        path = user_data_dir()
        path.mkdir(parents=True, exist_ok=True)
        (path / "startup-error.log").write_text(traceback.format_exc(), encoding="utf-8")
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, f"启动失败。请查看日志：\n{path / 'startup-error.log'}\nWindows 需要 Microsoft Edge WebView2 Runtime。", "VoiceMix Studio", 16)
        raise
