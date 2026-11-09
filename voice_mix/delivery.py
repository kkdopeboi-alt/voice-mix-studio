"""Publish only deliverables; project data stays in the application workspace."""
import os
import shutil
import uuid
from pathlib import Path


def publish_file(source, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name('.'+target.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        shutil.copy2(source, temp)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return str(target.resolve())


def deliver(result, directory):
    directory = Path(directory)
    for row in result['results']:
        if not row['ok']:
            continue
        stem = f'video_{row["index"]+1:03d}'
        row['path'] = publish_file(row['path'], directory/(stem+'.mp4'))
        if row.get('cover'):
            row['cover'] = publish_file(row['cover'], directory/(stem+'-cover.jpg'))
        else:
            # Remove only this application's previous optional cover for this variant.
            (directory/(stem+'-cover.jpg')).unlink(missing_ok=True)
    result.update(out_dir=str(directory), videos_dir=str(directory), initial_preview=False)
    return result
