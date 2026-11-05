"""Perfiles: identidad, preservación, repetición e integración con codegen."""
import sys, tempfile, unittest, struct
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reforge.game_profiles import apply_game_profile
from reforge import game
from reforge.core import AppConfig

class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        (self.root/'assets').mkdir()
        data=bytearray(80);data[:4]=b'XEX2';struct.pack_into('>I',data,20,1)
        struct.pack_into('>II',data,24,0x40006,40)
        struct.pack_into('>IIII',data,40,0x1A15DA04,2,0,0x415608E4)
        (self.root/'assets/default.xex').write_bytes(data)
        (self.root/'demo_manifest.toml').write_text('[project]\nname="demo"\n[entrypoint]\nfile_path="assets/default.xex"\n')
        self.path=self.root/'reforge_functions.toml'
        self.path.write_text('[functions]\n0x82478B30 = { size = 8 }\n\n[other]\nvalue=3\n')
        self.ctx=SimpleNamespace(log=lambda *args:None,cancelled=lambda:False)
    def tearDown(self):self.tmp.cleanup()
    def test_apply_preserves_manual_data_and_is_idempotent(self):
        self.assertTrue(apply_game_profile(str(self.root),self.ctx))
        text=self.path.read_text();self.assertIn('0x82478B30 = { size = 8 }',text)
        self.assertLess(text.index('0x8262E8B8'),text.index('[other]'))
        self.assertEqual(len(list(self.root.glob('*.bak-*'))),2)
        self.assertFalse(apply_game_profile(str(self.root),self.ctx))
        self.assertEqual(text,self.path.read_text())
    def test_other_version_is_untouched(self):
        path=self.root/'assets/default.xex';data=bytearray(path.read_bytes());struct.pack_into('>I',data,44,3);path.write_bytes(data)
        before=self.path.read_bytes();self.assertFalse(apply_game_profile(str(self.root),self.ctx))
        self.assertEqual(before,self.path.read_bytes());self.assertEqual(list(self.root.glob('*.bak-*')),[])
    def test_existing_manual_target_is_preserved(self):
        self.path.write_text('[functions]\n0x8262E8B8 = { size = 48 }\n')
        self.assertFalse(apply_game_profile(str(self.root),self.ctx))
        self.assertIn('size = 48',self.path.read_text())
    def test_profile_precedes_codegen(self):
        def run(*args):
            self.assertIn('0x8262E8B8',self.path.read_text());return 0,[]
        with patch.object(game,'run_streaming',side_effect=run) as mocked:
            game.codegen_with_autofix(AppConfig(),str(self.root),str(self.root/'build'),'demo',{},self.ctx)
            mocked.assert_called_once()
if __name__=='__main__':unittest.main()
