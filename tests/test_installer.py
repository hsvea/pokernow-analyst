import tempfile
import unittest
from pathlib import Path
from installer import install_new


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'installed'
        self.stage=Path(self.tmp.name)/'stage'
        self.stage.mkdir()
        for name in ('app','pokernow_overlay_v2'):
            (self.stage/name).mkdir()
        (self.stage/'bundle.json').write_text('{}')

    def test_first_install(self):
        install_new(self.stage,self.root)
        self.assertTrue((self.root/'app').is_dir())
        self.assertTrue((self.root/'pokernow_overlay_v2').is_dir())

    def test_refuse_existing_install(self):
        self.root.mkdir()
        (self.root/'app').mkdir()
        with self.assertRaises(ValueError): install_new(self.stage,self.root)
        self.assertTrue((self.stage/'bundle.json').exists())

    def test_partial_move_is_reversed(self):
        (self.stage/'bundle.json').unlink()
        with self.assertRaises(FileNotFoundError): install_new(self.stage,self.root)
        self.assertTrue((self.stage/'app').exists())
        self.assertFalse((self.root/'app').exists())
