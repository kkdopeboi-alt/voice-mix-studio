"""Build, smoke-test and archive the native application on its target OS."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from voice_mix.runtime import VERSION


def main():
    if sys.platform not in {"win32", "darwin"}:
        raise SystemExit("Build desktop releases on Windows or macOS.")
    dist = Path(os.environ.get("VOICE_MIX_DIST_DIR", ROOT / "dist")).resolve()
    from PIL import Image, ImageDraw
    image = Image.new("RGBA", (512, 512), "#15171b")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((30, 30, 482, 482), radius=104, fill="#222820")
    draw.polygon([(100, 152), (193, 152), (256, 276), (319, 152), (412, 152), (256, 423)], fill="#c4ef8b")
    draw.rounded_rectangle((100, 90, 412, 122), radius=8, fill="#667d4c")
    image.save(ROOT / "packaging/app.ico", sizes=[(16,16), (32,32), (48,48), (256,256)])
    if sys.platform == "darwin":
        image.save(ROOT / "packaging/app.icns")
    notices = ROOT / "build/dependency-licenses"
    notices.mkdir(parents=True, exist_ok=True)
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name", "unknown")
        dest = notices / name
        dest.mkdir(exist_ok=True)
        (dest / "METADATA.txt").write_text(distribution.read_text("METADATA") or name, encoding="utf-8")
        for file in distribution.files or []:
            if "license" in str(file).lower() or "copying" in str(file).lower():
                source = Path(distribution.locate_file(file))
                if source.is_file():
                    # Preserve unique relative names to avoid overwriting dependency notices.
                    target = dest / str(file).replace("/", "__").replace("\\", "__")
                    shutil.copy2(source, target)
    import edge_tts
    speech_source = ROOT / "build/dependency-sources/edge_tts"
    shutil.copytree(Path(edge_tts.__file__).parent, speech_source, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--distpath", str(dist),
                    str(ROOT / "packaging/VoiceMixStudio.spec")], cwd=ROOT, check=True)
    release = ROOT / "release"
    release.mkdir(exist_ok=True)
    app = dist / "VoiceMixStudio.app" if sys.platform == "darwin" else dist / "VoiceMixStudio"
    binary = app / "Contents/MacOS/VoiceMixStudio" if sys.platform == "darwin" else app / "VoiceMixStudio.exe"
    report = release / "smoke-report.json"
    env = dict(os.environ, VOICE_MIX_DATA_DIR=str(ROOT / "build/smoke-data"))
    subprocess.run([str(binary), "--smoke-test", "--engine-check", "--report", str(report)], check=True, timeout=60, env=env)
    result = json.loads(report.read_text(encoding="utf-8"))
    if not result.get("server") or result.get("voices", 0) < 1:
        raise RuntimeError("Frozen application smoke test failed")
    if result.get('version') != VERSION:
        raise RuntimeError('Packaged backend version does not match source')
    resource_root=app/'Contents/Resources' if sys.platform=='darwin' else app/'_internal'
    # macOS PyInstaller may place data in Frameworks with Resources symlinks.
    for source in (ROOT/'voice_mix/static').iterdir():
        if source.is_file() and source.suffix in {'.html','.js','.css'}:
            packaged=resource_root/'voice_mix/static'/source.name
            if not packaged.is_file() or packaged.read_bytes()!=source.read_bytes():
                raise RuntimeError('Packaged UI resource differs: '+source.name)
    arch = platform.machine().lower().replace("amd64", "x64").replace("x86_64", "x64")
    system = "macOS" if sys.platform == "darwin" else "Windows"
    name = f"VoiceMixStudio-{VERSION}-{system}-{arch}"
    archive = release / (name + ".zip")
    if sys.platform == "darwin":
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(archive)], check=True)
    else:
        for file in ("README.md", "THIRD_PARTY.md", "LICENSE"):
            shutil.copy2(ROOT / file, app / file)
        shutil.copytree(ROOT/'docs',app/'docs',dirs_exist_ok=True)
        shutil.copytree(ROOT/'examples',app/'examples',dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('generated','__pycache__','*.pyc'))
        shutil.make_archive(str(release / name), "zip", root_dir=app.parent, base_dir=app.name)
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{checksum}  {archive.name}\n", encoding="ascii")
    print(archive)


if __name__ == "__main__":
    main()
