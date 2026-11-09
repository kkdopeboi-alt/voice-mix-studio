import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from scripts.install_windows import install


class InstallTests(unittest.TestCase):
    def test_immutable_version_and_pointer(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            archive=root/'VoiceMixStudio-1.4.0-Windows-x64.zip'
            with ZipFile(archive,'w') as z:
                z.writestr('VoiceMixStudio/VoiceMixStudio.exe',b'demo-executable')
                z.writestr('VoiceMixStudio/_internal/voice_mix/static/batch.js',b'ui')
            result=install(archive,root/'programs')
            self.assertTrue(Path(result['exe']).is_file())
            self.assertEqual(json.loads((root/'programs/current.json').read_text())['version'],'1.4.0')
            self.assertEqual(install(archive,root/'programs'),result)

    def test_reject_traversal_and_bad_checksum(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            archive=root/'VoiceMixStudio-1.4.0-Windows-x64.zip'
            with ZipFile(archive,'w') as z:
                z.writestr('VoiceMixStudio/VoiceMixStudio.exe',b'demo')
                z.writestr('VoiceMixStudio/../../escape.txt',b'bad')
            with self.assertRaises(ValueError):install(archive,root/'programs')
            self.assertFalse((root/'escape.txt').exists())
            archive.with_suffix('.zip.sha256').write_text('0'*64+'  bad.zip')
            with self.assertRaises(ValueError):install(archive,root/'programs')
