# 开发、构建与贡献

建议 Python 3.12。在项目根目录创建并激活虚拟环境：

```sh
python -m venv .venv
```

Windows 激活 `.venv\Scripts\Activate.ps1`；macOS 激活 `source .venv/bin/activate`。之后运行：

```sh
python -m pip install -e ".[desktop,build,test,mv]"
python -m unittest discover -s tests -v
python -m voice_mix.desktop
```

浏览器开发：`python -m voice_mix --port 8780`。需要 FFmpeg 与 ffprobe。系统字体、FFmpeg 和模型不在源码包中。

## 主要模块

| 模块 | 责任 |
| --- | --- |
| config.py / assets.py | 配置、素材扫描和工具发现 |
| tts.py / planner.py / render.py | 配音、时间轴方案和渲染 |
| pipeline.py / batch.py | 单文案和批量流水线 |
| server.py | API、任务、项目、预览和微调 |
| mv_core.py / mv_ai.py / mv_render.py / mv_api.py | MV 时间轴、识别、场景分类与渲染 |
| desktop.py / startup.py | 原生与兼容窗口、单实例与就绪确认 |
| static/ | 桌面和网页共用工作台 |

网页与桌面共享源码。修改后需要重新打包才能更新 exe，更新浏览器开发服务不会自动更新历史 exe。

## 打包和安装

在目标操作系统运行：

```sh
python scripts/build_desktop.py
```

构建生成 release ZIP 与 SHA-256，并检查冻结程序启动。Windows 为 onedir 便携包，Mac 为 .app ZIP。默认 Mac 构建未配置开发者签名与公证；可通过 MACOS_SIGNING_IDENTITY 提供本机签名身份，公证需自行配置。

Windows 本地安装与快捷方式同步：

```powershell
python scripts/install_windows.py --archive release/VoiceMixStudio-1.4.2-Windows-x64.zip
```

安装工具使用 `%LOCALAPPDATA%/Programs/VoiceMixStudio/versions/` 版本目录，不覆盖应用数据。更新前保存并退出旧服务。

## GitHub Actions

`Desktop packages` 可手动运行或由版本标签触发，构建 Windows、macOS Apple Silicon 和 Intel。先安装工具，执行回归、打包与后台启动检查。

标签构建将产物上传到同版本草稿 Release；已有同标签 Release 时更新附件。CI 不能代替所有平台图形交互验收。

## 清洁源码与贡献

```sh
python scripts/source_release.py
```

脚本使用允许列表，包含代码、构建配置、测试、文档和自有示例，不导出个人项目与素材。二进制放 Releases，不加入 Git 历史。

Issue 中提供版本、操作系统、复现步骤与去除隐私的错误片段。凭据放环境变量或 GitHub Secrets，不能写进源码。

修改后运行相关检查。界面、API 与打包资源应保持同步，网页桥接的原生窗口引用必须保持私有。
