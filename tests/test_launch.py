"""Pruebas de preparación del arranque Windows (con archivos simulados)."""
import sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reforge import game
class LaunchTests(unittest.TestCase):
    def test_gpu_and_assets_arguments(self):
        args=game.launch_args('game.exe','project with spaces')
        self.assertIn('--gpu_plugin=xenos',args)
        self.assertEqual(len(args),3)
    def test_stage_matching_plugin_and_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'assets').mkdir();(root/'assets/default.xex').touch()
            (root/'build').mkdir();exe=root/'build/game.exe';exe.touch()
            (root/'sdk/bin').mkdir(parents=True)
            cfg=SimpleNamespace(sdk_prefix=lambda:str(root/'sdk'),build_type='Release')
            for build_type,suffix in [('Release',''),('Debug','d'),('RelWithDebInfo','rd')]:
                (root/'build/CMakeCache.txt').write_text('CMAKE_BUILD_TYPE:STRING='+build_type+'\n')
                plugin='rexgpu-xenos'+suffix+'.dll';(root/'sdk/bin'/plugin).write_bytes(b'plugin')
                with patch.object(game.sys,'platform','win32'):
                    game.prepare_game_runtime(cfg,str(exe),str(root))
                    launcher=game.write_launcher(str(exe),str(root),'game')
                self.assertEqual((root/'build'/plugin).read_bytes(),b'plugin')
                self.assertIn('--gpu_plugin=xenos',Path(launcher).read_text())
                self.assertIn('--game_data_root=',Path(launcher).read_text())
    def test_missing_assets_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError,'default.xex'):
                game.prepare_game_runtime(None,'game.exe',tmp)
if __name__=='__main__':unittest.main()
