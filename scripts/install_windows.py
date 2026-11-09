"""Install an immutable portable version and synchronize Windows shortcuts.

Never removes old versions or changes the VoiceMix project-data directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
from zipfile import ZipFile


def install(archive: Path, root: Path):
    archive,root=Path(archive).resolve(),Path(root).resolve()
    match=re.fullmatch(r'VoiceMixStudio-(\d+\.\d+\.\d+)-Windows-x64\.zip',archive.name)
    if not match:
        raise ValueError('请选择 VoiceMixStudio-版本-Windows-x64.zip 发布包')
    version=match[1]
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum=archive.with_suffix('.zip.sha256')
    if checksum.exists() and checksum.read_text(encoding='ascii').split()[0].lower()!=digest:
        raise ValueError('发布包校验失败，请重新下载')
    target=(root/'versions'/f'{version}-{digest[:10]}').resolve()
    if not target.is_relative_to(root):
        raise ValueError('安装路径超出用户程序目录')
    with ZipFile(archive) as package:
        entries=[]
        for item in package.infolist():
            name=item.filename.replace('\\','/')
            path=PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or ':' in name or not path.parts or path.parts[0]!='VoiceMixStudio':
                raise ValueError('发布包包含无效文件路径')
            if stat.S_ISLNK(item.external_attr>>16):
                raise ValueError('Windows 发布包不应包含符号链接')
            relative=Path(*path.parts[1:])
            output=(target/relative).resolve()
            if not output.is_relative_to(target):
                raise ValueError('发布文件超出安装目录')
            entries.append((item,output))
        if sum(item.file_size for item,_ in entries)>3*1024**3:
            raise ValueError('发布包解压体积异常')
        expected='VoiceMixStudio/VoiceMixStudio.exe'
        if expected not in package.namelist():
            raise ValueError('发布包缺少主程序')
        target.mkdir(parents=True,exist_ok=True)
        for item,output in entries:
            if item.is_dir():
                output.mkdir(parents=True,exist_ok=True)
            else:
                output.parent.mkdir(parents=True,exist_ok=True)
                if output.exists():
                    if output.stat().st_size==item.file_size:
                        continue
                    raise ValueError('已安装版本内容不一致，请使用新的发布包')
                with package.open(item) as src,output.open('wb') as dest:
                    import shutil
                    shutil.copyfileobj(src,dest)
    result=dict(version=version,exe=str(target/'VoiceMixStudio.exe'),archive_sha256=digest)
    temp=root/'current.tmp'
    temp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(root/'current.json')
    return result


def shortcuts(exe):
    # Environment variables carry paths; no user-controlled text is shell code.
    script=r'''
$ErrorActionPreference='Stop'
$shell=New-Object -ComObject WScript.Shell
$desktop=$shell.SpecialFolders.Item('Desktop')
$paths=@((Join-Path $desktop 'VoiceMix Studio.lnk'),(Join-Path $desktop 'VoiceMix Studio（浏览器兼容模式）.lnk'))
foreach($file in Get-ChildItem -LiteralPath $desktop -Filter '*VoiceMix*.lnk'){
  $old=$shell.CreateShortcut($file.FullName)
  if([IO.Path]::GetFileName($old.TargetPath) -ieq 'VoiceMixStudio.exe'){$paths+=$file.FullName}
}
foreach($path in ($paths|Select-Object -Unique)){
  $link=$shell.CreateShortcut($path)
  $link.TargetPath=$env:VOICEMIX_INSTALL_EXE
  $link.WorkingDirectory=[IO.Path]::GetDirectoryName($env:VOICEMIX_INSTALL_EXE)
  $link.Arguments=if([IO.Path]::GetFileName($path) -match '浏览器|稳定|兼容'){'--browser'}else{''}
  $link.IconLocation=$env:VOICEMIX_INSTALL_EXE+',0'
  $link.Description='VoiceMix Studio '+$env:VOICEMIX_INSTALL_VERSION
  $link.Save()
  Write-Output $path
}
'''
    import base64
    encoded=base64.b64encode(script.encode('utf-16le')).decode('ascii')
    version=Path(exe).parent.name.split('-')[0]
    env=dict(os.environ,VOICEMIX_INSTALL_EXE=str(exe),VOICEMIX_INSTALL_VERSION=version)
    subprocess.run(['powershell','-NoProfile','-NonInteractive','-EncodedCommand',encoded],
                   env=env,check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--install-root',type=Path,default=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'Programs/VoiceMixStudio')
    parser.add_argument('--no-shortcuts',action='store_true')
    args=parser.parse_args()
    if sys.platform!='win32' and not args.no_shortcuts:
        raise SystemExit('此安装工具仅用于 Windows')
    result=install(args.archive,args.install_root)
    if not args.no_shortcuts:
        shortcuts(result['exe'])
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
