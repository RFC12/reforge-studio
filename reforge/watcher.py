"""Vigilante de juegos: detecta el juego recompilado que está abierto (da igual cómo se lanzó: .bat, acceso
directo, doble clic o lanzador) leyendo los logs que el runtime escribe en build/logs, y actúa si falla:

* «Call to invalid or unregistered function» → cierra el juego colgado y lo repara en el Taller.
* «Graphics device lost» u otro [FATAL] gráfico → propone el asistente de imagen (⚡ Optimizar).
* Cualquier otro [FATAL] → lo explica con las últimas líneas del log.

Si el juego lo vigila otra parte de ReForge (Taller o lanzador del juego), no interviene dos veces.
"""
import glob
import os
import re
import subprocess
import sys
import time

from PySide6.QtCore import QObject, QTimer, Signal

from . import game

MARKER = ".reforge_watching"        # lo crea el lanzador del juego mientras lo vigila (logs/.reforge_watching)
GPU_FATAL_RE = re.compile(r"device lost|DXGI_ERROR|D3D12.*(removed|hung)|graphics device", re.I)


def marker_path(exe):
    return os.path.join(game.game_log_dir(exe), MARKER)


def write_marker(exe):
    try:
        os.makedirs(game.game_log_dir(exe), exist_ok=True)
        with open(marker_path(exe), "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass


def clear_marker(exe):
    try:
        os.remove(marker_path(exe))
    except OSError:
        pass


def marker_active(exe, max_age=30.0):
    """El lanzador renueva la marca mientras vigila; una marca vieja (lanzador cerrado) no cuenta."""
    try:
        return time.time() - os.path.getmtime(marker_path(exe)) < max_age
    except OSError:
        return False


def kill_by_exe(exe):
    """Cierra el proceso del juego (Windows lo deja colgado en el cuadro de error tras un [FATAL])."""
    name = os.path.basename(exe)
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/IM", name, "/T", "/F"], capture_output=True, stdin=subprocess.DEVNULL,
                           creationflags=0x08000000, timeout=30)
        else:
            subprocess.run(["pkill", "-f", exe], capture_output=True, timeout=30)
    except Exception:      # noqa: BLE001
        pass


class _Track:
    def __init__(self, project, exe, log):
        from .perfdiag import LiveLog
        self.project, self.exe, self.log = project, exe, log
        self.pos = 0
        self.handled = False
        self.started = time.time()
        self.live = LiveLog(log)


class GameWatcher(QObject):
    detected = Signal(object, str)              # proyecto, exe
    finished = Signal(object)                   # proyecto
    crashed = Signal(object, str, dict)         # proyecto, exe, análisis
    stats = Signal(object, str, dict, float)    # proyecto, exe, estadísticas en vivo, segundos jugados
    ended = Signal(object, str, dict)           # proyecto, exe, análisis de la partida (si nadie más la atendió)

    def __init__(self, library_fn, busy_fn=None, interval_ms=2000):
        super().__init__()
        self.library_fn = library_fn            # () -> lista de proyectos
        self.busy_fn = busy_fn or (lambda project: False)
        self.known = {}                          # ruta de log -> (mtime, tamaño) ya vistos
        self.active = {}                         # ruta de log -> _Track
        self._open_at_start = set()              # juegos que ya estaban abiertos al iniciar ReForge
        self.timer = QTimer(self)
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self.poll)
        self._prime()

    def start(self):
        self.timer.start()

    def stop(self):
        self.timer.stop()

    def _logs(self):
        for p in self.library_fn():
            try:
                exe = game.game_exe(p.root, p.name)
            except Exception:      # noqa: BLE001
                continue
            if not exe:
                continue
            for log in glob.glob(os.path.join(game.game_log_dir(exe), "*.log")):
                yield p, exe, log

    def _prime(self):
        """Los logs que ya existen al abrir ReForge son de partidas anteriores: no se tratan. Salvo el del juego
        que ya está abierto (se abrió antes que ReForge): ese se vigila desde ahora."""
        now = time.time()
        newest = {}
        for _p, exe, log in self._logs():
            try:
                st = os.stat(log)
            except OSError:
                continue
            self.known[log] = (st.st_mtime, st.st_size)
            if exe not in newest or st.st_mtime > newest[exe][1]:
                newest[exe] = (log, st.st_mtime)
        for exe, (log, mtime) in newest.items():
            if now - mtime < 600 and self._running(exe):
                self.known.pop(log, None)        # juego ya abierto: poll() lo detecta
                self._open_at_start.add(log)

    def poll(self):
        now = time.time()
        for p, exe, log in self._logs():
            try:
                st = os.stat(log)
            except OSError:
                continue
            sig = (st.st_mtime, st.st_size)
            if log in self.active:
                t = self.active[log]
                self._read(t)
                self.stats.emit(t.project, t.exe, dict(t.live.feed()), now - t.started)
                continue
            if self.known.get(log) == sig:
                continue
            self.known[log] = sig
            if now - st.st_mtime < 20 or log in self._open_at_start:   # hay un juego en marcha
                self._open_at_start.discard(log)
                t = _Track(p, exe, log)
                self.active[log] = t
                self.detected.emit(p, exe)
                self._read(t)
        for log, t in list(self.active.items()):
            try:
                idle = now - os.path.getmtime(log)
            except OSError:
                idle = 999
            if t.handled or (idle > 15 and not self._running(t.exe)):
                self.active.pop(log, None)
                try:
                    st = os.stat(log)
                    self.known[log] = (st.st_mtime, st.st_size)
                except OSError:
                    pass
                if not t.handled:
                    self.finished.emit(t.project)
                    # Partida lanzada por fuera (acceso directo, .bat, doble clic): análisis y mantenimiento aquí.
                    if not (marker_active(t.exe) or self.busy_fn(t.project)):
                        try:
                            info = game.session_result(t.exe, t.log, t.started)
                        except Exception:      # noqa: BLE001
                            info = {"kind": "nolog", "address": None, "lines": [], "path": t.log}
                        self.ended.emit(t.project, t.exe, info)

    def _running(self, exe):
        name = os.path.basename(exe)
        try:
            if sys.platform == "win32":
                r = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"], capture_output=True,
                                   text=True, errors="replace", stdin=subprocess.DEVNULL,
                                   creationflags=0x08000000, timeout=15)
                return name.lower() in (r.stdout or "").lower()
            r = subprocess.run(["pgrep", "-f", exe], capture_output=True, timeout=15)
            return r.returncode == 0
        except Exception:      # noqa: BLE001
            return False

    def _read(self, t):
        try:
            with open(t.log, encoding="utf-8", errors="replace") as f:
                f.seek(t.pos)
                chunk = f.read()
                t.pos = f.tell()
        except OSError:
            return
        if t.handled or "[FATAL]" not in chunk:
            return
        if marker_active(t.exe) or self.busy_fn(t.project):
            t.handled = True                     # lo atiende el lanzador o el Taller
            return
        t.handled = True
        time.sleep(0.3)
        info = game.analyze_runtime_log(t.log)
        if info["kind"] == "fatal" and any(GPU_FATAL_RE.search(ln) for ln in info.get("lines", [])):
            info["kind"] = "gpu"
        self.crashed.emit(t.project, t.exe, info)
