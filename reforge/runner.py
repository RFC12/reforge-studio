"""Ejecutor de pipelines: comandos externos (QProcess) y pasos Python (QThread)."""
import re
import os
import threading
import time
import traceback

from PySide6.QtCore import QObject, QLockFile, QProcess, QProcessEnvironment, QThread, QTimer, Signal

NINJA_RE = re.compile(r"^\[(\d+)/(\d+)\]")
MAKE_RE = re.compile(r"^\[\s*(\d+)%\]")
ERR_RE = re.compile(r"(\berror\b|\bfatal\b|\bfailed\b|undefined reference|LNK\d{4})", re.I)
WARN_RE = re.compile(r"\bwarning\b", re.I)


def classify(line):
    if ERR_RE.search(line) and not re.search(r"\b0 error", line, re.I):
        return "err"
    if WARN_RE.search(line):
        return "warn"
    return "info"


def _quote(a):
    return f'"{a}"' if (" " in a or not a) else a


class Step:
    def __init__(self, key, title, cmd=None, func=None, cwd=None, env=None, skip_if=None):
        self.key, self.title = key, title
        self.cmd, self.func = cmd, func
        self.cwd, self.env, self.skip_if = cwd, env, skip_if


class StepContext:
    def __init__(self, thread):
        self._t = thread

    def log(self, text, level="info"):
        self._t.log_signal.emit(str(text), level)

    def progress(self, value, maximum):
        self._t.progress_signal.emit(int(value), int(maximum))

    def cancelled(self):
        return self._t.cancel_event.is_set()


_LIVE_THREADS = set()


def wait_threads(timeout_ms=5000):
    """Espera a los pasos en segundo plano antes de cerrar (Qt aborta si se destruye un QThread vivo)."""
    for t in list(_LIVE_THREADS):
        t.cancel_event.set()
    for t in list(_LIVE_THREADS):
        if t.isRunning():
            t.wait(timeout_ms)


class _FuncThread(QThread):
    log_signal = Signal(str, str)
    progress_signal = Signal(int, int)
    done = Signal(bool, str)

    def __init__(self, func, cancel_event):
        super().__init__()
        self.func, self.cancel_event = func, cancel_event
        _LIVE_THREADS.add(self)
        self.finished.connect(lambda: _LIVE_THREADS.discard(self))

    def run(self):
        try:
            self.func(StepContext(self))
            ok = not self.cancel_event.is_set()
            self.done.emit(ok, "" if ok else "Cancelado por el usuario")
        except Exception as e:  # noqa
            if not getattr(e, "quiet", False):      # fallos esperados (p. ej. la prueba del juego) sin traza
                self.log_signal.emit(traceback.format_exc().rstrip(), "dim")
            self.done.emit(False, str(e))


def run_in_thread(func, done=None):
    """Lanza func(ctx) en un hilo y llama a done(ok, error) al terminar. Devuelve el hilo (tiene
    .cancel_event para cancelar y .progress_signal para el progreso)."""
    import threading
    t = _FuncThread(func, threading.Event())
    if done is not None:
        t.done.connect(done)
    t.start()
    return t


class PipelineRunner(QObject):
    step_state = Signal(int, str)   # índice, pending|running|done|error|skipped
    log = Signal(str, str)
    progress = Signal(int, int)     # valor, máximo (0 = indeterminado)
    finished = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.steps, self.index = [], -1
        self.proc = self.thread = None
        self._cancel = threading.Event()
        self.running = False
        self._project_lock = None
        self._buf = ""
        self._step_done = False
        self._t0 = self._step_t0 = 0.0

    # ---------------------------------------------------------------- API
    def start(self, steps, project_root=None):
        if self.running:
            return
        self.steps, self.index = list(steps), -1
        self.running = True
        self._cancel.clear()
        self._t0 = time.time()
        if project_root:
            try:
                os.makedirs(project_root, exist_ok=True)
                lock = QLockFile(os.path.join(os.path.realpath(project_root), ".reforge-build.lock"))
                lock.setStaleLockTime(0)
                if not lock.tryLock(0):
                    self.log.emit("No se puede bloquear el proyecto: otra instancia de ReForge Studio "
                                  "lo está usando o no hay permisos de escritura.", "err")
                    self._finish(False)
                    return
                self._project_lock = lock
            except OSError as exc:
                self.log.emit(f"No se pudo bloquear el proyecto: {exc}", "err")
                self._finish(False)
                return
        for i in range(len(self.steps)):
            self.step_state.emit(i, "pending")
        self._next()

    def cancel(self):
        if not self.running:
            return
        self._cancel.set()
        self.log.emit("Cancelando…", "warn")
        if self.proc is not None and self.proc.state() != QProcess.ProcessState.NotRunning:
            from .processes import stop_process_tree
            stop_process_tree(int(self.proc.processId()))
            self.proc.kill()

    # ---------------------------------------------------------------- interno
    def _next(self):
        self.index += 1
        if self._cancel.is_set():
            return self._finish(False)
        if self.index >= len(self.steps):
            return self._finish(True)
        step = self.steps[self.index]
        if step.skip_if:
            reason = step.skip_if()
            if reason:
                self.step_state.emit(self.index, "skipped")
                self.log.emit(f"⤼  {step.title}: {reason}", "dim")
                QTimer.singleShot(0, self._next)
                return
        self.step_state.emit(self.index, "running")
        self.log.emit(f"━━━ {self.index + 1}. {step.title}", "head")
        self.progress.emit(0, 0)
        self._step_done = False
        self._step_t0 = time.time()
        try:
            if step.cmd is not None:
                self._start_cmd(step)
            else:
                self._start_func(step)
        except Exception as exc:
            self._end_step(False, str(exc))

    def _start_cmd(self, step):
        cmd = step.cmd() if callable(step.cmd) else step.cmd
        p = QProcess(self)
        p.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        if step.cwd:
            p.setWorkingDirectory(step.cwd)
        if step.env is not None:
            penv = QProcessEnvironment()
            for k, v in step.env.items():
                penv.insert(k, v)
            p.setProcessEnvironment(penv)
        p.readyReadStandardOutput.connect(self._on_output)
        p.finished.connect(self._on_finished)
        p.errorOccurred.connect(self._on_error)
        self.proc, self._buf, self._prog_name = p, "", cmd[0]
        self.log.emit("$ " + " ".join(_quote(a) for a in cmd), "cmd")
        p.start(cmd[0], cmd[1:])

    def _on_output(self):
        if self.proc is None:
            return
        data = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        self._buf += data.replace("\r\n", "\n").replace("\r", "\n")
        *lines, self._buf = self._buf.split("\n")
        for line in lines:
            self._handle_line(line)

    def _handle_line(self, line):
        if not line.strip():
            return
        m = NINJA_RE.match(line)
        if m:
            self.progress.emit(int(m.group(1)), max(1, int(m.group(2))))
        else:
            m = MAKE_RE.match(line)
            if m:
                self.progress.emit(int(m.group(1)), 100)
        self.log.emit(line, classify(line))

    def _on_finished(self, code, status):
        if self._step_done:
            return
        self._on_output()
        if self._buf.strip():
            self._handle_line(self._buf)
        self._buf = ""
        self._step_done = True
        ok = code == 0 and status == QProcess.ExitStatus.NormalExit and not self._cancel.is_set()
        msg = "" if ok else ("Cancelado por el usuario" if self._cancel.is_set()
                             else f"El proceso terminó con código {code}")
        self._end_step(ok, msg)

    def _on_error(self, err):
        if err == QProcess.ProcessError.FailedToStart and not self._step_done:
            self._step_done = True
            self._end_step(False, f"No se pudo iniciar «{self._prog_name}». "
                                  "Revisa la ruta de la herramienta en Ajustes.")

    def _start_func(self, step):
        t = _FuncThread(step.func, self._cancel)
        t.log_signal.connect(self.log)
        t.progress_signal.connect(self.progress)
        t.done.connect(self._on_func_done)
        self.thread = t
        t.start()

    def _on_func_done(self, ok, msg):
        if self.thread is not None:
            self.thread.wait(2000)
        self._end_step(ok, msg)

    def _end_step(self, ok, msg):
        dt = time.time() - self._step_t0
        step = self.steps[self.index]
        if ok:
            self.step_state.emit(self.index, "done")
            self.log.emit(f"✔  {step.title} ({dt:.1f} s)", "ok")
            QTimer.singleShot(0, self._next)
        else:
            self.step_state.emit(self.index, "error")
            self.log.emit(f"✖  {step.title}: {msg}", "err")
            self._finish(False)

    def _finish(self, ok):
        if self._project_lock is not None:
            self._project_lock.unlock()
            self._project_lock = None
        self.running = False
        self.proc = None
        dt = time.time() - self._t0
        m, s = divmod(int(dt), 60)
        self.log.emit(("★ Proceso completado" if ok else "Proceso detenido") + f" · {m} min {s} s",
                      "ok" if ok else "warn")
        self.progress.emit(1 if ok else 0, 1)
        self.finished.emit(ok)
