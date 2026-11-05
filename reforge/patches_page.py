"""Página «Parches»: versión instalada del núcleo y gestión de parches."""
import json
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from . import API_VERSION, __version__
from .core import open_path
from .pages import panel, scroll_wrap
from .patches import PATCH_EXT, PatchError, vtuple
from .widgets import label, repolish

STATUS_KIND = {"activo": "", "desactivado": "run", "modo seguro": "run",
               "incompatible": "err", "error": "err", "pendiente": "run"}


def install_info():
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        with open(os.path.join(base, "version.json"), encoding="utf-8") as f:
            d = json.load(f)
        d.setdefault("install_dir", base)
        d["mode"] = "Instalado"
        return d
    except Exception:
        return {"mode": "Portable" if getattr(sys, "frozen", False) else "Desde código fuente",
                "install_dir": base, "version": __version__}


def _changelog_text(info, limit=None):
    out = []
    for entry in (info.changelog or [])[:limit]:
        head = f"v{entry.get('version', '?')}" + (f" · {entry['date']}" if entry.get("date") else "")
        out.append(head)
        for n in entry.get("notes", []):
            out.append(f"   • {n}")
    return "\n".join(out) or "Sin historial de cambios."


class PatchCard(QFrame):
    def __init__(self, page, info):
        super().__init__()
        self.setObjectName("Card")
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 14)
        v.setSpacing(6)
        top = QHBoxLayout()
        top.addWidget(label(info.name, "CardTitle"), 1)
        ver = label(f"v{info.version}", "Chip")
        top.addWidget(ver)
        st = label(info.status.upper(), "Chip")
        st.setProperty("kind", STATUS_KIND.get(info.status, ""))
        top.addWidget(st)
        v.addLayout(top)
        meta = " · ".join(x for x in (info.author and f"por {info.author}", info.id,
                                      info.installed_at and f"instalado {info.installed_at}",
                                      info.requires_core and f"núcleo {info.requires_core}") if x)
        v.addWidget(label(meta, "Hint", wrap=True))
        if info.description:
            v.addWidget(label(info.description, None, wrap=True))
        if info.error:
            err = label(info.error.strip().splitlines()[-1] if info.status == "error" else info.error,
                        "HintErr", wrap=True)
            err.setToolTip(info.error)
            v.addWidget(err)
        latest = (info.changelog or [{}])[0]
        if latest.get("notes"):
            v.addWidget(label("Novedades v" + str(latest.get("version", "")) + ": " +
                              " · ".join(latest["notes"][:3]), "Hint", wrap=True))
        row = QHBoxLayout()
        if info.status != "error" or info.enabled:
            tog = QPushButton("Desactivar" if info.enabled else "Activar")
            tog.clicked.connect(lambda: page.toggle(info))
            row.addWidget(tog)
        det = QPushButton("Detalles")
        det.clicked.connect(lambda: page.details(info))
        row.addWidget(det)
        if info.has_backup:
            rb = QPushButton(f"↶ Revertir a v{info.has_backup}")
            rb.clicked.connect(lambda: page.rollback(info))
            row.addWidget(rb)
        row.addStretch(1)
        rm = QPushButton("Desinstalar")
        rm.setObjectName("Danger")
        rm.clicked.connect(lambda: page.uninstall(info))
        row.addWidget(rm)
        v.addLayout(row)


class PatchesPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.pm = win.patches
        self.pending_restart = False
        self.notices = []
        v = QVBoxLayout(self)
        v.setContentsMargins(36, 10, 36, 30)
        v.setSpacing(14)

        p, pv = panel()
        pv.addWidget(label("REFORGE STUDIO", "Section"))
        h = QHBoxLayout()
        self.core_lbl = label("", "BigNumber")
        h.addWidget(self.core_lbl)
        h.addSpacing(18)
        self.core_meta = label("", "Hint", wrap=True)
        h.addWidget(self.core_meta, 1)
        pv.addLayout(h)
        btns = QHBoxLayout()
        b_inst = QPushButton("⬇  Instalar parche…")
        b_inst.setObjectName("Primary")
        b_inst.clicked.connect(self.pick_and_install)
        b_dir = QPushButton("📁  Carpeta de parches")
        b_dir.clicked.connect(lambda: open_path(self.pm.base))
        b_rs = QPushButton("⟳  Reiniciar")
        b_rs.clicked.connect(lambda: win.restart())
        b_safe = QPushButton("🛡  Reiniciar en modo seguro")
        b_safe.clicked.connect(lambda: win.restart(safe_mode=True))
        b_upd = QPushButton("⬆  Actualizar ReForge Studio…")
        b_upd.setToolTip("Elige un ReForgeStudio-Setup-x.y.z.exe: detecta tu versión y actualiza conservando todo")
        b_upd.clicked.connect(self.update_core)
        for b in (b_inst, b_upd, b_dir, b_rs, b_safe):
            btns.addWidget(b)
        btns.addStretch(1)
        pv.addLayout(btns)
        v.addWidget(p)

        self.banner = label("", "HintErr", wrap=True)
        self.banner.hide()
        v.addWidget(self.banner)

        top = QHBoxLayout()
        top.addWidget(label("PARCHES INSTALADOS", "Section"), 1)
        self.count_lbl = label("", "Hint")
        top.addWidget(self.count_lbl)
        v.addLayout(top)
        holder = QWidget()
        self.list = QVBoxLayout(holder)
        self.list.setSpacing(12)
        self.list.setAlignment(Qt.AlignmentFlag.AlignTop)
        v.addWidget(scroll_wrap(holder), 1)

    # ---------------------------------------------------------------- vista
    def refresh(self):
        info = install_info()
        self.core_lbl.setText(f"v{__version__}")
        lines = [f"{info['mode']} · {info.get('install_dir', '')}",
                 f"API de parches v{API_VERSION} · Parches en {self.pm.base}"]
        if info.get("installed_at"):
            lines.append(f"Instalado/actualizado: {info['installed_at']}")
        if self.pm.safe_mode:
            lines.append("🛡 MODO SEGURO: los parches no se cargaron en esta sesión.")
        self.core_meta.setText("\n".join(lines))
        while self.list.count():
            it = self.list.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        items = list(self.pm.patches.values())
        active = sum(1 for i in items if i.status == "activo")
        self.count_lbl.setText(f"{len(items)} instalado(s) · {active} activo(s)")
        if not items:
            self.list.addWidget(label("No hay parches instalados. Usa «Instalar parche…» o haz doble "
                                      f"clic en un archivo {PATCH_EXT}.", "Hint", wrap=True))
        for i in items:
            self.list.addWidget(PatchCard(self, i))
        msgs = list(self.notices)
        if self.pm.crashed_patch:
            msgs.append(f"⚠ El parche «{self.pm.crashed_patch}» se desactivó porque la aplicación se cerró "
                        "inesperadamente al cargarlo.")
        if self.pending_restart:
            msgs.append("⟳ Reinicia ReForge Studio para aplicar los cambios de parches.")
        self.banner.setText("\n".join(msgs))
        self.banner.setVisible(bool(msgs))

    def _changed(self):
        # Conserva el estado de carga de esta sesión para lo que no cambió
        loaded = {i.id: (i.status, i.error) for i in self.pm.patches.values()}
        self.pm.scan()
        for pid, inf in self.pm.patches.items():
            if pid in loaded and loaded[pid][0] in ("activo", "error", "incompatible", "modo seguro"):
                inf.status, inf.error = loaded[pid][0], inf.error or loaded[pid][1]
            elif inf.status == "pendiente":
                inf.status = "pendiente" if inf.enabled else "desactivado"
        self.pending_restart = True
        self.refresh()
        self.win.update_patch_badge()

    # ---------------------------------------------------------------- acciones
    def pick_and_install(self):
        path, _ = QFileDialog.getOpenFileName(self, "Instalar parche", "",
                                              f"Parches de ReForge (*{PATCH_EXT});;Todos (*)")
        if path:
            self.install_file(path)

    def install_file(self, path):
        try:
            new, old, incompat = self.pm.inspect(path)
        except PatchError as e:
            QMessageBox.critical(self, "Parche no válido", str(e))
            return False
        except Exception as e:
            QMessageBox.critical(self, "Parche no válido", f"No se pudo leer el parche:\n{e}")
            return False
        if incompat:
            QMessageBox.warning(self, "Parche incompatible",
                                f"{new.name} v{new.version}\n\n{incompat}\n\n"
                                "Actualiza ReForge Studio con el instalador más reciente.")
            return False
        if old is None:
            action = "Instalar"
        elif vtuple(new.version) > vtuple(old.version):
            action = f"Actualizar v{old.version} → v{new.version}"
        elif vtuple(new.version) == vtuple(old.version):
            action = f"Reinstalar v{new.version}"
        else:
            action = f"Volver a una versión anterior (v{old.version} → v{new.version})"
        dlg = QDialog(self)
        dlg.setWindowTitle("Instalar parche")
        dlg.setMinimumWidth(560)
        dv = QVBoxLayout(dlg)
        dv.addWidget(label(new.name, "CardTitle"))
        dv.addWidget(label(f"v{new.version} · {new.id}" + (f" · por {new.author}" if new.author else ""), "Hint"))
        if new.description:
            dv.addWidget(label(new.description, None, wrap=True))
        dv.addWidget(label("✔ Integridad verificada (SHA-256) · compatible con este núcleo", "HintOk"))
        if old is not None and vtuple(new.version) < vtuple(old.version):
            dv.addWidget(label("⚠ Vas a instalar una versión más antigua que la actual.", "HintErr"))
        log = QPlainTextEdit(_changelog_text(new, 4))
        log.setReadOnly(True)
        log.setObjectName("Small")
        log.setFixedHeight(160)
        dv.addWidget(log)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(action)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        dv.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False
        try:
            self.pm.install(path)
            self.win.set_bundled_declined(new.id, False)
        except Exception as e:
            QMessageBox.critical(self, "Error al instalar", f"No se instaló el parche. Nada cambió.\n\n{e}")
            return False
        self._changed()
        r = QMessageBox.question(self, "Parche instalado",
                                 f"{new.name} v{new.version} se instaló correctamente.\n\n¿Reiniciar ahora para aplicarlo?")
        if r == QMessageBox.StandardButton.Yes:
            self.win.restart()
        return True

    def update_core(self):
        path, _ = QFileDialog.getOpenFileName(self, "Instalador de ReForge Studio", "",
                                              "Instalador (ReForgeStudio-Setup-*.exe);;Programas (*.exe)")
        if not path:
            return
        if self.win.workshop.runner.running:
            QMessageBox.information(self, "Ocupado", "Espera a que termine la recompilación.")
            return
        r = QMessageBox.question(self, "Actualizar ReForge Studio",
                                 f"Se abrirá {os.path.basename(path)} y ReForge Studio se cerrará para "
                                 "actualizarse. Tus proyectos, ajustes, parches y el SDK se conservan.\n\n¿Continuar?")
        if r != QMessageBox.StandardButton.Yes:
            return
        from PySide6.QtCore import QProcess
        if QProcess.startDetached(path, []):
            self.win.close()
        else:
            QMessageBox.critical(self, "Actualizar", "No se pudo abrir el instalador.")

    def toggle(self, info):
        self.pm.set_enabled(info.id, not info.enabled)
        self._changed()

    def rollback(self, info):
        r = QMessageBox.question(self, "Revertir parche",
                                 f"¿Volver de v{info.version} a v{info.has_backup} en «{info.name}»?")
        if r != QMessageBox.StandardButton.Yes:
            return
        try:
            self.pm.rollback(info.id)
        except Exception as e:
            QMessageBox.critical(self, "No se pudo revertir", str(e))
            return
        self._changed()

    def uninstall(self, info):
        r = QMessageBox.question(self, "Desinstalar parche",
                                 f"¿Desinstalar «{info.name}» v{info.version}?\n\n"
                                 "Sus ajustes se conservan por si lo vuelves a instalar.")
        if r != QMessageBox.StandardButton.Yes:
            return
        self.pm.uninstall(info.id)
        self.win.set_bundled_declined(info.id, True)
        self._changed()

    def details(self, info):
        dlg = QDialog(self)
        dlg.setWindowTitle(info.name)
        dlg.resize(640, 520)
        dv = QVBoxLayout(dlg)
        dv.addWidget(label(f"{info.name}  v{info.version}", "CardTitle"))
        txt = [f"Identificador: {info.id}", f"Estado: {info.status}",
               f"Requiere núcleo: {info.requires_core or '—'} · API v{info.api}",
               f"Carpeta: {info.path}", f"Archivos verificados: {len(info.files)}", ""]
        if info.error:
            txt += ["Error:", info.error, ""]
        txt += ["Historial de cambios:", _changelog_text(info), ""]
        if info.credits:
            txt += ["Créditos:"] + [f"   • {c}" for c in info.credits]
        box = QPlainTextEdit("\n".join(txt))
        box.setReadOnly(True)
        box.setObjectName("Log")
        dv.addWidget(box, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject)
        dv.addWidget(bb)
        dlg.exec()
