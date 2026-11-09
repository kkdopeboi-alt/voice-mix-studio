# Build on the target operating system with Python 3.12.
from pathlib import Path
import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata

root = Path(SPECPATH).parent
analysis = Analysis(
    [str(root / "desktop_entry.py")],
    pathex=[str(root)],
    binaries=collect_dynamic_libs('ctranslate2') + collect_dynamic_libs('onnxruntime'),
    datas=[(str(root / "voice_mix/static"), "voice_mix/static"),
           (str(root / "build/dependency-licenses"), "dependency-licenses"),
           (str(root / "build/dependency-sources"), "dependency-sources"),
           (str(root / "THIRD_PARTY.md"), "."), (str(root / "LICENSE"), ".")]
          + collect_data_files('faster_whisper') + copy_metadata('faster-whisper')
          + copy_metadata('yt-dlp') + copy_metadata('huggingface-hub'),
    hiddenimports=["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.h11_impl",
                   "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on", "PIL.ImageFont",
                   "pillow_heif", "webview.platforms.cocoa" if sys.platform == "darwin" else "webview.platforms.winforms"],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "PySide2", "PySide6", "tkinter", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name="VoiceMixStudio",
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False,
          icon=str(root / "packaging/app.icns" if sys.platform == "darwin" else root / "packaging/app.ico"),
          codesign_identity=os.environ.get("MACOS_SIGNING_IDENTITY") or None)
collection = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False, name="VoiceMixStudio")
if sys.platform == "darwin":
    app = BUNDLE(collection, name="VoiceMixStudio.app", bundle_identifier="app.voicemix.studio", icon=str(root / "packaging/app.icns"),
                 info_plist={"CFBundleShortVersionString": "1.5.0", "CFBundleVersion": "1.5.0",
                             "NSHighResolutionCapable": True,
                             "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True}})
