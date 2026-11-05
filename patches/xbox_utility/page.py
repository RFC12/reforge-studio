"""Interfaz del parche Utilidades Xbox."""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QGridLayout,
                               QHBoxLayout, QHeaderView, QInputDialog, QLineEdit, QMessageBox,
                               QProgressBar, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
                               QTabWidget, QVBoxLayout, QWidget)

from . import ops, tools

try:
    from send2trash import send2trash as _trash
except Exception:
    _trash = None


class XboxUtilityPage(QWidget):
    def __init__(self, api):
        super().__init__()
        self.api = api
        self.s = api.settings
        ui = api.ui
        self.ui = ui
        self.runner = api.runner.PipelineRunner(self)
        self.busy_widgets = []

        root = QHBoxLayout(self)
        root.setContentsMargins(36, 10, 36, 30)
        root.setSpacing(20)
        self.tabs = QTabWidget()
        self.tabs.setUsesScrollButtons(False)
        self.tabs.addTab(self._tab_batch_extract(), "ISO → Carpeta")
        self.tabs.addTab(self._tab_batch_create(), "Carpeta → ISO")
        self.tabs.addTab(self._tab_classic(), "Xbox Clásica")
        self.tabs.addTab(self._tab_tools(), "Herramientas")
        self.tabs.addTab(self._tab_ftp(), "FTP")
        self.tabs.addTab(self._tab_clean(), "Limpieza")
        self.tabs.setCurrentIndex(int(self.s.get("tab", 0) or 0))
        self.tabs.currentChanged.connect(lambda i: self.s.set("tab", i))
        root.addWidget(self.tabs, 5)

        rv = QVBoxLayout()
        head = QHBoxLayout()
        self.status = ui.label("Listo", "CardTitle")
        head.addWidget(self.status, 1)
        self.cancel_btn = QPushButton("■  Cancelar")
        self.cancel_btn.setObjectName("Danger")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.runner.cancel)
        head.addWidget(self.cancel_btn)
        rv.addLayout(head)
        self.progress = QProgressBar()
        self.progress.setFixedHeight(8)
        self.progress.setRange(0, 1)
        rv.addWidget(self.progress)
        self.log = ui.LogView()
        rv.addWidget(self.log, 1)
        root.addLayout(rv, 3)

        self.runner.log.connect(self.log.write)
        self.runner.progress.connect(self._on_progress)
        self.runner.finished.connect(self._on_finished)
        self.log.write(f"Utilidades Xbox v{api.patch.version} · parche para ReForge Studio {api.core_version}", "dim")
        self._detect_tools(silent=True)

    # ================================================================ helpers
    def _field(self, key, kind, placeholder="", filt=""):
        pf = self.ui.PathField(kind, filt, placeholder)
        pf.setText(self.s.get(key, ""))
        pf.changed.connect(lambda t, k=key: self.s.set(k, t.strip()))
        return pf

    def _check(self, key, text, default=False):
        cb = QCheckBox(text)
        cb.setChecked(bool(self.s.get(key, default)))
        cb.toggled.connect(lambda v, k=key: self.s.set(k, v))
        return cb

    def _table(self, headers):
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setAlternatingRowColors(True)
        hh = t.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        return t

    def _add_row(self, table, path, cols, checked=True):
        r = table.rowCount()
        table.insertRow(r)
        chk = QTableWidgetItem()
        chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        chk.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        chk.setData(Qt.ItemDataRole.UserRole, path)
        table.setItem(r, 0, chk)
        for c, val in enumerate(cols, 1):
            table.setItem(r, c, QTableWidgetItem(str(val)))

    def _checked(self, table):
        out = []
        for r in range(table.rowCount()):
            it = table.item(r, 0)
            if it.checkState() == Qt.CheckState.Checked:
                out.append(it.data(Qt.ItemDataRole.UserRole))
        return out

    def _select_all(self, table, on):
        for r in range(table.rowCount()):
            table.item(r, 0).setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def _tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        return w, v

    def _primary(self, text, slot):
        b = QPushButton(text)
        b.setObjectName("Primary")
        b.clicked.connect(slot)
        self.busy_widgets.append(b)
        return b

    def _run(self, title, func):
        if self.runner.running:
            return
        self.log.clear_log()
        self.status.setText(title)
        for w in self.busy_widgets:
            w.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.runner.start([self.api.runner.Step("op", title, func=func)])

    def _on_progress(self, v, m):
        self.progress.setRange(0, m)
        if m:
            self.progress.setValue(min(v, m))

    def _on_finished(self, ok):
        for w in self.busy_widgets:
            w.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.status.setText("✔ Terminado" if ok else "Detenido")
        self.api.notify("Utilidades Xbox", "Operación terminada" if ok else "La operación se detuvo")
        for fn in (self._scan_isos, self._scan_folders, self._scan_clean):
            try:
                fn(quiet=True)
            except Exception:
                pass

    # ================================================================ ISO → carpetas
    def _tab_batch_extract(self):
        w, v = self._tab()
        v.addWidget(self.ui.label("EXTRAER ISOS POR LOTES", "Section"))
        v.addWidget(self.ui.label("Xbox 360 y Xbox Clásica. Cada ISO se extrae en una carpeta con su nombre "
                                  "(como el 360 Utility: junto a x_ISO por defecto).", "Hint", wrap=True))
        f = QFormLayout()
        self.iso_dir = self._field("iso_dir", "dir", "Carpeta con las ISOs (p. ej. x_ISO)")
        self.iso_dir.changed.connect(lambda _t: self._scan_isos(quiet=True))
        self.iso_out = self._field("iso_out", "dir", "Vacío = junto a la carpeta de ISOs")
        f.addRow("ISOs", self.iso_dir)
        f.addRow("Destino", self.iso_out)
        v.addLayout(f)
        self.iso_table = self._table(["", "ISO", "Tipo", "Título", "Title ID", "Tamaño"])
        v.addWidget(self.iso_table, 1)
        row = QHBoxLayout()
        b_scan = QPushButton("⟳ Escanear")
        b_scan.clicked.connect(lambda: self._scan_isos())
        b_all = QPushButton("Todas")
        b_all.clicked.connect(lambda: self._select_all(self.iso_table, True))
        b_none = QPushButton("Ninguna")
        b_none.clicked.connect(lambda: self._select_all(self.iso_table, False))
        for b in (b_scan, b_all, b_none):
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        self.iso_over = self._check("iso_overwrite", "Sobrescribir carpetas existentes")
        self.iso_del = self._check("iso_delete", "Borrar cada ISO después de extraerla")
        v.addWidget(self.iso_over)
        v.addWidget(self.iso_del)
        v.addWidget(self._primary("▶  Extraer seleccionadas", self.do_extract))
        return w

    def _scan_isos(self, quiet=False):
        self.iso_table.setRowCount(0)
        d = self.iso_dir.text()
        isos = ops.list_isos(d)
        for iso in isos:
            try:
                i = ops.iso_info(iso)
                cols = [os.path.basename(iso), f"{i['kind']} · {i['layout']}", i.get("title", ""),
                        i.get("title_id", ""), self.api.helpers.human_size(os.path.getsize(iso))]
            except Exception as e:
                cols = [os.path.basename(iso), "✖ no válida", str(e)[:60], "", ""]
            self._add_row(self.iso_table, iso, cols, checked="✖" not in cols[1])
        if not quiet:
            self.log.write(f"{len(isos)} ISO(s) en {d}" if d else "Elige la carpeta de ISOs", "info")

    def _dest_for(self, src_dir, override):
        return override or os.path.dirname(os.path.normpath(src_dir)) or src_dir

    def do_extract(self):
        isos = self._checked(self.iso_table)
        if not isos:
            return QMessageBox.information(self, "Nada seleccionado", "Escanea y marca al menos una ISO.")
        dest = self._dest_for(self.iso_dir.text(), self.iso_out.text())
        delete = self.iso_del.isChecked()
        if delete:
            how = "a la papelera de reciclaje" if _trash else "PERMANENTEMENTE (no hay papelera disponible)"
            if QMessageBox.warning(self, "Borrar ISOs",
                                   f"Las {len(isos)} ISO(s) se enviarán {how} después de extraerse "
                                   "correctamente. ¿Continuar?",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) \
                    != QMessageBox.StandardButton.Yes:
                return
        over = self.iso_over.isChecked()
        self._run(f"Extrayendo {len(isos)} ISO(s)",
                  lambda ctx: ops.extract_isos(ctx, isos, dest, over, delete, _trash))

    # ================================================================ carpetas → ISO
    def _tab_batch_create(self):
        w, v = self._tab()
        v.addWidget(self.ui.label("CREAR ISOS DESDE CARPETAS DE JUEGO", "Section"))
        v.addWidget(self.ui.label("Detecta carpetas con default.xex / default.xbe y crea una ISO XDVDFS por "
                                  "cada una (creador nativo, compatible con extract-xiso).", "Hint", wrap=True))
        f = QFormLayout()
        self.fold_dir = self._field("folders_dir", "dir", "Carpeta que contiene las carpetas de juego")
        self.fold_dir.changed.connect(lambda _t: self._scan_folders(quiet=True))
        self.fold_out = self._field("folders_out", "dir", "Vacío = la misma carpeta")
        f.addRow("Juegos", self.fold_dir)
        f.addRow("Destino", self.fold_out)
        v.addLayout(f)
        self.fold_table = self._table(["", "Carpeta", "Tipo", "Título", "Title ID", "FATX"])
        v.addWidget(self.fold_table, 1)
        row = QHBoxLayout()
        b_scan = QPushButton("⟳ Escanear")
        b_scan.clicked.connect(lambda: self._scan_folders())
        b_all = QPushButton("Todas")
        b_all.clicked.connect(lambda: self._select_all(self.fold_table, True))
        b_none = QPushButton("Ninguna")
        b_none.clicked.connect(lambda: self._select_all(self.fold_table, False))
        for b in (b_scan, b_all, b_none):
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        self.fold_over = self._check("folders_overwrite", "Sobrescribir ISOs existentes")
        v.addWidget(self.fold_over)
        v.addWidget(self.ui.label("ℹ Para grabar la ISO o abrirla en Xbox Image Browser, pásala después por "
                                  "360mpGui (pestaña Herramientas).", "Hint", wrap=True))
        v.addWidget(self._primary("▶  Crear ISOs seleccionadas", self.do_create))
        return w

    def _scan_folders(self, quiet=False):
        self.fold_table.setRowCount(0)
        d = self.fold_dir.text()
        found = ops.list_game_folders(d)
        for path, info in found:
            bad = ops.fatx_problems(path)
            self._add_row(self.fold_table, path,
                          [os.path.basename(path), info["kind"], info.get("title", ""),
                           info.get("title_id", ""), f"⚠ {len(bad)}" if bad else "✔"])
        if not quiet:
            self.log.write(f"{len(found)} carpeta(s) de juego en {d}" if d else "Elige la carpeta de juegos")

    def do_create(self):
        folders = self._checked(self.fold_table)
        if not folders:
            return QMessageBox.information(self, "Nada seleccionado", "Escanea y marca al menos una carpeta.")
        dest = self.fold_out.text() or self.fold_dir.text()
        over = self.fold_over.isChecked()
        self._run(f"Creando {len(folders)} ISO(s)", lambda ctx: ops.create_isos(ctx, folders, dest, over))

    # ================================================================ Xbox Clásica
    def _tab_classic(self):
        w, v = self._tab()
        v.addWidget(self.ui.label("XBOX CLÁSICA · ISO ↔ CARPETA", "Section"))
        v.addWidget(self.ui.label("Convierte una ISO de Xbox original (XISO o Redump) en carpeta lista para el "
                                  "disco duro de la consola o emuladores, y al revés.", "Hint", wrap=True))
        f = QFormLayout()
        self.cl_iso = self._field("classic_iso", "file", "Juego.iso", "Imágenes (*.iso *.ISO);;Todos (*)")
        self.cl_iso.changed.connect(lambda _t: self._classic_info())
        self.cl_out = self._field("classic_out", "dir", "Vacío = junto a la ISO")
        f.addRow("ISO", self.cl_iso)
        f.addRow("Destino", self.cl_out)
        v.addLayout(f)
        self.cl_info = self.ui.label("Selecciona una ISO para ver su título.", "Hint", wrap=True)
        v.addWidget(self.cl_info)
        v.addWidget(self._primary("▶  ISO → Carpeta", self.do_classic_extract))
        v.addSpacing(16)
        f2 = QFormLayout()
        self.cl_folder = self._field("classic_folder", "dir", "Carpeta del juego (con default.xbe)")
        f2.addRow("Carpeta", self.cl_folder)
        v.addLayout(f2)
        v.addWidget(self._primary("▶  Carpeta → ISO", self.do_classic_create))
        self.cl_fatx = QPushButton("Revisar nombres FATX (máx. 42 caracteres)")
        self.cl_fatx.clicked.connect(self.check_fatx)
        v.addWidget(self.cl_fatx)
        v.addStretch(1)
        return w

    def _classic_info(self):
        p = self.cl_iso.text()
        if not os.path.isfile(p):
            self.cl_info.setText("Selecciona una ISO para ver su título.")
            return
        try:
            i = ops.iso_info(p)
            parts = [f"✔ {i['kind']} · {i['layout']}", f"{i['files']} archivos · {self.api.helpers.human_size(i['size'])}"]
            if i.get("title"):
                parts.insert(1, f"«{i['title']}»")
            if i.get("title_id"):
                parts.append(f"Title ID {i['title_id']}")
            if i.get("region"):
                parts.append(i["region"])
            self.cl_info.setText(" · ".join(parts))
        except Exception as e:
            self.cl_info.setText(f"✖ {e}")

    def do_classic_extract(self):
        iso = self.cl_iso.text()
        if not os.path.isfile(iso):
            return QMessageBox.warning(self, "Falta la ISO", "Selecciona una ISO.")
        dest = self.cl_out.text() or os.path.dirname(iso)
        self._run("ISO → Carpeta", lambda ctx: ops.extract_isos(ctx, [iso], dest, overwrite=False))

    def do_classic_create(self):
        d = self.cl_folder.text()
        if not os.path.isdir(d):
            return QMessageBox.warning(self, "Falta la carpeta", "Selecciona la carpeta del juego.")
        dest = os.path.dirname(os.path.normpath(d))
        self._run("Carpeta → ISO", lambda ctx: ops.create_isos(ctx, [d], dest))

    def check_fatx(self):
        d = self.cl_folder.text() or self.ftp_local.text()
        if not os.path.isdir(d):
            return QMessageBox.information(self, "Sin carpeta", "Selecciona una carpeta de juego.")
        bad = ops.fatx_problems(d)
        self.log.write(f"━━━ Nombres FATX en {d}", "head")
        if not bad:
            self.log.write("✔ Todos los nombres son válidos para el disco de la Xbox", "ok")
        for rel, why in bad:
            self.log.write(f"⚠ {rel} — {why}", "warn")

    # ================================================================ herramientas
    def _tab_tools(self):
        w, v = self._tab()
        v.addWidget(self.ui.label("HERRAMIENTAS EXTERNAS", "Section"))
        v.addWidget(self.ui.label("Programas de terceros que ya tienes en tu carpeta x_tool. ReForge Studio "
                                  "solo los abre; no se incluyen en el parche.", "Hint", wrap=True))
        f = QFormLayout()
        self.xtool = self._field("xtool_dir", "dir", r"…\Xbox360-Utility-Create-Extract-1.2\x_tool")
        self.xtool.changed.connect(lambda _t: self._detect_tools(silent=True))
        self.qwix = self._field("qwix_path", "file", "Opcional: ruta a Qwix.exe", "Programas (*.exe)")
        self.qwix.changed.connect(lambda _t: self._detect_tools(silent=True))
        f.addRow("x_tool", self.xtool)
        f.addRow("Qwix", self.qwix)
        v.addLayout(f)
        row = QHBoxLayout()
        det = QPushButton("🔍 Detectar herramientas")
        det.clicked.connect(lambda: self._detect_tools())
        reg = QPushButton("🛡 Registrar MSCOMCTL.OCX")
        reg.setToolTip("Necesario para Xbox Image Browser. Pide permisos de administrador.")
        reg.clicked.connect(self.register_ocx)
        row.addWidget(det)
        row.addWidget(reg)
        row.addStretch(1)
        v.addLayout(row)
        holder = QWidget()
        self.tool_grid = QGridLayout(holder)
        self.tool_grid.setSpacing(10)
        self.tool_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        v.addWidget(self.ui.scroll_wrap(holder), 1)
        return w

    def _detect_tools(self, silent=False):
        if not hasattr(self, "tool_grid"):
            return
        xdir = self.xtool.text()
        while self.tool_grid.count():
            it = self.tool_grid.takeAt(0)
            if it.widget():
                it.widget().hide()
                it.widget().setParent(None)
                it.widget().deleteLater()
        self.tool_paths = {}
        for i, t in enumerate(tools.TOOLS):
            override = self.qwix.text() if t["key"] == "qwix" else ""
            path = tools.find_tool(xdir, t, override)
            self.tool_paths[t["key"]] = path
            card, cv = self.ui.panel()
            card.setObjectName("Card")
            card.setMinimumHeight(170)
            top = QHBoxLayout()
            top.addWidget(self.ui.label(f"{t['glyph']}  {t['name']}", "CardTitle"), 1)
            chip = self.ui.label("LISTO" if path else "NO ENCONTRADO", "Chip")
            chip.setProperty("kind", "" if path else "err")
            top.addWidget(chip)
            cv.addLayout(top)
            cv.addWidget(self.ui.label(t["desc"], "Hint", wrap=True))
            b = QPushButton("Abrir")
            b.setEnabled(bool(path))
            b.clicked.connect(lambda _c=False, tt=t: self.open_tool(tt))
            cv.addWidget(b)
            self.tool_grid.addWidget(card, i // 2, i % 2)
        if not silent:
            n = sum(1 for p in self.tool_paths.values() if p)
            self.log.write(f"Herramientas encontradas: {n}/{len(tools.TOOLS)}", "ok" if n else "warn")
            for t in tools.TOOLS:
                p = self.tool_paths[t["key"]]
                self.log.write(f"  {'✔' if p else '✖'} {t['name']}: {p or 'no encontrado'}", "info" if p else "dim")
        # sugerir x_ISO vecino como carpeta de ISOs
        if xdir and not self.iso_dir.text():
            near = os.path.join(os.path.dirname(os.path.normpath(xdir)), "x_ISO")
            if os.path.isdir(near):
                self.iso_dir.setText(near)

    def open_tool(self, t):
        path = self.tool_paths.get(t["key"])
        try:
            tools.launch(path)
        except Exception as e:
            QMessageBox.warning(self, t["name"], f"No se pudo abrir:\n{e}")
            return
        self.log.write(f"▶ {t['name']} abierto", "ok")
        if t.get("howto"):
            self.log.write(f"  {t['howto']}", "info")

    def register_ocx(self):
        try:
            tools.register_mscomctl(self.xtool.text())
            self.log.write("MSCOMCTL.OCX: se lanzó el registro con permisos de administrador.", "ok")
        except Exception as e:
            QMessageBox.warning(self, "MSCOMCTL.OCX", str(e))

    # ================================================================ FTP
    def _tab_ftp(self):
        w, v = self._tab()
        v.addWidget(self.ui.label("ENVIAR JUEGO A LA XBOX POR FTP", "Section"))
        v.addWidget(self.ui.label("Funciona con cualquier dashboard con servidor FTP (Avalaunch, UnleashX, "
                                  "XBMC, Aurora, FSD…). Revisa los nombres FATX antes de enviar.", "Hint", wrap=True))
        f = QFormLayout()
        self.ftp_host = QLineEdit(self.s.get("ftp_host", "192.168.1.100"))
        self.ftp_host.textChanged.connect(lambda t: self.s.set("ftp_host", t.strip()))
        self.ftp_port = QSpinBox()
        self.ftp_port.setRange(1, 65535)
        self.ftp_port.setValue(int(self.s.get("ftp_port", 21)))
        self.ftp_port.valueChanged.connect(lambda n: self.s.set("ftp_port", n))
        self.ftp_user = QLineEdit(self.s.get("ftp_user", "xbox"))
        self.ftp_user.textChanged.connect(lambda t: self.s.set("ftp_user", t))
        self.ftp_pass = QLineEdit(self.s.get("ftp_pass", "xbox"))
        self.ftp_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.ftp_pass.textChanged.connect(lambda t: self.s.set("ftp_pass", t))
        self.ftp_remote = QComboBox()
        self.ftp_remote.setEditable(True)
        self.ftp_remote.addItems(["/E/Games", "/F/Games", "/G/Games", "/Hdd1/Games", "/Usb0/Games"])
        self.ftp_remote.setCurrentText(self.s.get("ftp_remote", "/E/Games"))
        self.ftp_remote.currentTextChanged.connect(lambda t: self.s.set("ftp_remote", t.strip()))
        self.ftp_local = self._field("ftp_local", "dir", "Carpeta del juego a enviar")
        f.addRow("IP de la Xbox", self.ftp_host)
        f.addRow("Puerto", self.ftp_port)
        f.addRow("Usuario", self.ftp_user)
        f.addRow("Contraseña", self.ftp_pass)
        f.addRow("Carpeta remota", self.ftp_remote)
        f.addRow("Juego", self.ftp_local)
        v.addLayout(f)
        self.ftp_pasv = self._check("ftp_passive", "Modo pasivo", True)
        self.ftp_skip = self._check("ftp_skip_bad", "Omitir archivos con nombres no válidos para FATX", True)
        v.addWidget(self.ftp_pasv)
        v.addWidget(self.ftp_skip)
        row = QHBoxLayout()
        chk = QPushButton("Revisar nombres FATX")
        chk.clicked.connect(self.check_fatx)
        row.addWidget(chk)
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(self._primary("⇪  Enviar a la Xbox", self.do_ftp))
        v.addWidget(self.ui.label("La contraseña se guarda en texto plano en los ajustes del parche.", "Hint"))
        v.addStretch(1)
        return w

    def do_ftp(self):
        local = self.ftp_local.text()
        if not os.path.isdir(local):
            return QMessageBox.warning(self, "Falta la carpeta", "Selecciona la carpeta del juego.")
        args = (self.ftp_host.text().strip(), self.ftp_port.value(), self.ftp_user.text(), self.ftp_pass.text(),
                local, self.ftp_remote.currentText().strip() or "/", self.ftp_pasv.isChecked(),
                self.ftp_skip.isChecked())
        self._run("Enviando por FTP", lambda ctx: ops.ftp_upload(ctx, *args))

    # ================================================================ limpieza
    def _tab_clean(self):
        w, v = self._tab()
        v.addWidget(self.ui.label("LIMPIEZA DE CARPETAS DE JUEGO", "Section"))
        v.addWidget(self.ui.label("Solo lista carpetas que contienen .xex o .xbe. x_tool y x_ISO se excluyen "
                                  "siempre. Por defecto van a la papelera de reciclaje.", "Hint", wrap=True))
        f = QFormLayout()
        self.clean_dir = self._field("clean_dir", "dir", "Carpeta a revisar")
        self.clean_dir.changed.connect(lambda _t: self._scan_clean(quiet=True))
        f.addRow("Carpeta", self.clean_dir)
        v.addLayout(f)
        self.clean_table = self._table(["", "Carpeta", "Tipo", "Título", "Tamaño"])
        v.addWidget(self.clean_table, 1)
        row = QHBoxLayout()
        b = QPushButton("⟳ Escanear")
        b.clicked.connect(lambda: self._scan_clean())
        row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        btns = QHBoxLayout()
        b_trash = self._primary("🗑  Mover a la papelera", lambda: self.do_clean(permanent=False))
        b_trash.setEnabled(_trash is not None)
        if _trash is None:
            b_trash.setToolTip("send2trash no está disponible en esta instalación")
        b_perm = QPushButton("Eliminar permanentemente…")
        b_perm.setObjectName("Danger")
        b_perm.clicked.connect(lambda: self.do_clean(permanent=True))
        self.busy_widgets.append(b_perm)
        btns.addWidget(b_trash, 1)
        btns.addWidget(b_perm)
        v.addLayout(btns)
        return w

    def _scan_clean(self, quiet=False):
        self.clean_table.setRowCount(0)
        d = self.clean_dir.text()
        found = ops.list_game_folders(d)
        for path, info in found:
            size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _d, fn in os.walk(path) for f in fn)
            self._add_row(self.clean_table, path,
                          [os.path.basename(path), info["kind"], info.get("title", ""),
                           self.api.helpers.human_size(size)], checked=False)
        if not quiet:
            self.log.write(f"{len(found)} carpeta(s) de juego en {d}" if d else "Elige una carpeta")

    def do_clean(self, permanent):
        folders = self._checked(self.clean_table)
        if not folders:
            return QMessageBox.information(self, "Nada seleccionado", "Marca las carpetas a eliminar.")
        names = "\n".join("• " + os.path.basename(f) for f in folders[:15])
        if len(folders) > 15:
            names += f"\n… y {len(folders) - 15} más"
        if permanent:
            text, ok = QInputDialog.getText(
                self, "Eliminar permanentemente",
                f"Se borrarán SIN posibilidad de recuperar:\n\n{names}\n\nEscribe ELIMINAR para confirmar:")
            if not ok or text.strip().upper() != "ELIMINAR":
                return
            trash = None
        else:
            if QMessageBox.question(self, "Mover a la papelera", f"¿Mover a la papelera?\n\n{names}") \
                    != QMessageBox.StandardButton.Yes:
                return
            trash = _trash
        self._run("Limpiando carpetas", lambda ctx: ops.delete_folders(ctx, folders, trash))
