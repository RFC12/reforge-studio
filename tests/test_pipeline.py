"""Regresión del pipeline de compilación."""
import os, sys, tempfile, threading, time, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication
from reforge.core import AppConfig
from reforge.pages import WorkshopPage
from reforge.runner import PipelineRunner, Step
from reforge.game import run_streaming
APP = QCoreApplication.instance() or QCoreApplication([])
def wait_until(predicate):
    end = time.monotonic() + 8
    while not predicate() and time.monotonic() < end:
        APP.processEvents(); time.sleep(.01)
    assert predicate(), 'Timeout'
class PipelineTests(unittest.TestCase):
    def test_refresh_and_build_only(self):
        page = SimpleNamespace(win=SimpleNamespace(cfg=AppConfig()), clean=SimpleNamespace(isChecked=lambda: False),
                               _refresh_tools=lambda root: None)   # la herramientas se prueban en test_latest_tools
        for selected in [['configure', 'codegen', 'build'], ['build']]:
            steps = WorkshopPage._build_steps(page, 'demo', '/tmp/demo', 'none', '', selected)
            self.assertEqual([s.key for s in steps][-2:], ['reconfigure', 'build'])
            self.assertEqual(steps[-2].cmd()[1:5], ['-S', '/tmp/demo', '-B', os.path.join('/tmp/demo', 'build')])
            self.assertEqual(steps[-2].env, steps[-1].env)
    def test_failure_stops_build_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as root:
            runner = PipelineRunner(); result = []; ran = []
            runner.finished.connect(result.append)
            runner.start([Step('refresh','Refresh',cmd=[sys.executable,'-c','raise SystemExit(1)']), Step('build','Build',func=lambda ctx: ran.append(True))], project_root=root)
            wait_until(lambda: bool(result))
            self.assertEqual(result,[False]); self.assertEqual(ran,[])
            self.assertFalse(Path(root,'.reforge-build.lock').exists())
    def test_lock_competition_and_cancel(self):
        with tempfile.TemporaryDirectory() as root:
            first=PipelineRunner(); second=PipelineRunner(); result=[]; ran=[]
            second.finished.connect(result.append)
            first.start([Step('wait','Wait',cmd=[sys.executable,'-c','import time; time.sleep(30)'])],project_root=root)
            second.start([Step('bad','Bad',func=lambda ctx: ran.append(True))],project_root=root)
            self.assertEqual(result,[False]); self.assertEqual(ran,[])
            first.cancel(); wait_until(lambda:not first.running)
            self.assertFalse(Path(root,'.reforge-build.lock').exists())
    def test_silent_cancel(self):
        event=threading.Event();ctx=SimpleNamespace(log=lambda *a:None,progress=lambda *a:None,cancelled=event.is_set)
        timer=threading.Timer(.25,event.set);timer.start();start=time.monotonic()
        with self.assertRaisesRegex(RuntimeError,'Cancelado'):
            run_streaming([sys.executable,'-c','import time; time.sleep(30)'],None,os.environ.copy(),ctx)
        timer.join();self.assertLess(time.monotonic()-start,5)
    def test_stream_output(self):
        ctx=SimpleNamespace(log=lambda *a:None,progress=lambda *a:None,cancelled=lambda:False)
        self.assertEqual(run_streaming([sys.executable,'-c','print("[1/1] Done")'],None,os.environ.copy(),ctx),(0,['[1/1] Done']))
if __name__=='__main__':unittest.main()
