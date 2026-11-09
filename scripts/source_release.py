"""Export only source-controlled product files, never local media or credentials."""
import argparse
import hashlib
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--output", default=str(root / "release/VoiceMixStudio-source.zip"))
args = parser.parse_args()
output = Path(args.output).resolve()
output.parent.mkdir(parents=True, exist_ok=True)
files = [root / name for name in ("README.md", "THIRD_PARTY.md", "CHANGELOG.md", "pyproject.toml", ".gitignore", ".gitattributes", "desktop_entry.py")]
files += list((root / "voice_mix").glob("*.py"))
for directory, patterns in [("voice_mix/static", ("*.html", "*.css", "*.js")),
                            ("scripts", ("*.py",)), ("tests", ("*.py", "*.cjs")),
                            ("packaging", ("*.spec",)), (".github/workflows", ("*.yml",))]:
    for pattern in patterns:
        files.extend((root / directory).glob(pattern))
if (root / "LICENSE").is_file():
    files.append(root / "LICENSE")
for directory, extensions in [('docs',{'.md','.svg','.png','.jpg'}),('examples',{'.md','.txt','.py','.json'}),('.github/ISSUE_TEMPLATE',{'.yml','.md'})]:
    files.extend(p for p in (root/directory).rglob('*') if p.is_file() and p.suffix in extensions
                 and 'generated' not in p.relative_to(root/directory).parts)
if (root/'CONTRIBUTING.md').exists():
    files.append(root/'CONTRIBUTING.md')
with ZipFile(output, "w", ZIP_DEFLATED) as archive:
    for file in sorted(set(files)):
        archive.write(file, "VoiceMixStudio/" + file.relative_to(root).as_posix())
output.with_suffix(".zip.sha256").write_text(hashlib.sha256(output.read_bytes()).hexdigest() + "  " + output.name + "\n", encoding="ascii")
print(output)
