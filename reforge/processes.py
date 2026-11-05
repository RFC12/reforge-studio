"""Cancelación de procesos sin dejar compiladores activos en Windows."""
import os
import signal
import subprocess
import sys


def stop_process_tree(pid, grouped=False):
    if not pid:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
    elif grouped:
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
