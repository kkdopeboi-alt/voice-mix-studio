# Third-party components

VoiceMix Studio uses the following independently licensed projects. Their license notices are retained by the Python package and frozen dependency metadata where provided.

| Component | Upstream | License |
| --- | --- | --- |
| Python | https://www.python.org/ | PSF |
| pywebview | https://github.com/r0x0r/pywebview | BSD-3-Clause |
| FastAPI | https://github.com/fastapi/fastapi | MIT |
| Starlette | https://github.com/encode/starlette | BSD-3-Clause |
| Uvicorn | https://github.com/encode/uvicorn | BSD-3-Clause |
| edge-tts | https://github.com/rany2/edge-tts | LGPL-3.0 |
| Pillow | https://github.com/python-pillow/Pillow | MIT-CMU |
| pillow-heif | https://github.com/bigcat88/pillow_heif | BSD-3-Clause |
| PyInstaller | https://github.com/pyinstaller/pyinstaller | GPL with bootloader exception |

FFmpeg and ffprobe are external runtime tools, obtained and installed separately. They are not included in these release archives. Their license depends on their build configuration. The application launches them as subprocesses. Use https://ffmpeg.org/download.html for official distribution links.

Windows uses the installed Microsoft Edge WebView2 Runtime. macOS uses the system WebKit engine. Fonts are loaded from the user's operating system. Personal music, images, video, voice caches and project history are excluded from the source release.

Speech generation sends the entered narration text to the Microsoft online speech service through edge-tts. An internet connection is required. Media rendering and project storage run locally. No speech-service availability guarantee is made by this application.

Before publishing a new binary release, retain the generated `dependency-licenses` directory and review upstream notices. This file does not assign an open-source license to the project's original code.
# MV 模式新增依赖

MV 使用 faster-whisper / CTranslate2 进行本地识别，ONNX Runtime / Tokenizers 进行本地场景分类，yt-dlp 提供 URL 下载。各依赖许可证随桌面构建收集。语音与画面模型按需从 Hugging Face 下载，模型遵循各自许可证；不随源码 ZIP 分发。

技术来源：[faster-whisper](https://github.com/SYSTRAN/faster-whisper)、[yt-dlp](https://github.com/yt-dlp/yt-dlp)、[CLIP ONNX 模型](https://huggingface.co/Xenova/clip-vit-base-patch32)、[ASS 字幕格式](https://aegisub.org/docs/latest/ass_tags/)。

