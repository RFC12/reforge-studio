"""API pública para parches (contrato v1).

Un parche solo debería usar lo que expone este objeto. Mientras API_VERSION no cambie,
todo lo que hay aquí se mantiene compatible entre versiones del núcleo.

Ejemplo mínimo de plugin.py:

    def register(api):
        page = api.ui.QWidget()
        api.add_page("mi-pagina", "★   Mi página", "Título", page)
        api.add_home_tile("★", "Mi parche", "Descripción", lambda: api.go("mi-pagina"))
"""
import json
import os
import types

from PySide6 import QtCore, QtGui, QtWidgets

from . import API_VERSION, __version__, core, runner, widgets, xex, xiso
from .pages import panel, scroll_wrap


class PatchSettings:
    """Ajustes persistentes de un parche (sobreviven a actualizaciones del parche)."""

    def __init__(self, path):
        self.path = path
        try:
            with open(path, encoding="utf-8") as f:
                self._d = json.load(f)
        except Exception:
            self._d = {}

    def get(self, key, default=None):
        return self._d.get(key, default)

    def set(self, key, value):
        self._d[key] = value
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._d, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)


class PluginAPI:
    API_VERSION = API_VERSION

    def __init__(self, window, info, data_root):
        self._win = window
        self.patch = info
        self.core_version = __version__
        self.data_dir = os.path.join(data_root, info.id)
        os.makedirs(self.data_dir, exist_ok=True)
        self.settings = PatchSettings(os.path.join(self.data_dir, "settings.json"))
        self._pages, self._tiles = [], []
        # Módulos y componentes disponibles para los parches
        self.ui = types.SimpleNamespace(
            QtCore=QtCore, QtGui=QtGui, QtWidgets=QtWidgets,
            Tile=widgets.Tile, LogView=widgets.LogView, PathField=widgets.PathField,
            StepTracker=widgets.StepTracker, label=widgets.label, repolish=widgets.repolish,
            panel=panel, scroll_wrap=scroll_wrap,
        )
        self.runner = types.SimpleNamespace(PipelineRunner=runner.PipelineRunner, Step=runner.Step)
        self.formats = types.SimpleNamespace(xiso=xiso, xex=xex)
        self.helpers = types.SimpleNamespace(
            human_size=core.human_size, open_path=core.open_path, sanitize_name=core.sanitize_name,
            copy_tree=core.copy_tree, NO_WINDOW=core.NO_WINDOW)

    # ---------------------------------------------------------------- interfaz
    def add_page(self, key, nav_text, title, widget):
        key = f"{self.patch.id}:{key}"
        self._win.add_page(key, nav_text, title, widget, owner=self.patch.id)
        self._pages.append(key)
        return key

    def add_home_tile(self, glyph, title, subtitle, callback):
        self._win.home.add_patch_tile(glyph, title, subtitle, callback, owner=self.patch.id)
        self._tiles.append(title)

    def go(self, key):
        full = key if ":" in key else f"{self.patch.id}:{key}"
        self._win.go(full)

    def notify(self, title, message):
        self._win.notify(title, message)

    @property
    def app_config(self):
        """Configuración del núcleo (solo lectura recomendada)."""
        return self._win.cfg

    @property
    def main_window(self):
        return self._win

    # ---------------------------------------------------------------- interno
    def _rollback(self):
        for key in self._pages:
            self._win.remove_page(key)
        self._win.home.remove_patch_tiles(self.patch.id)
        self._pages, self._tiles = [], []
