"""Vistas rápida y avanzada del launcher, dibujadas desde UNA sola definición de opciones (el perfil del
título). La misma lista alimenta la vista rápida, la avanzada y —por los mismos `id`— el menú dentro del juego.

Navegable con mando/teclado/ratón: foco visible, ayuda por opción y se conserva la selección al alternar vistas
(ambas vistas leen y escriben el mismo estado `self.values`)."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QStackedWidget, QTabWidget, QVBoxLayout, QWidget)


WHEN = {"instant": "al instante", "restart": "al reiniciar", "rebuild": "al recompilar"}


class OptionsPanel(QWidget):
    """Panel con vista rápida y avanzada construidas desde `profile.options`. `values` es un dict id->valor."""
    changed = Signal(str, object)     # (id, valor)

    def __init__(self, profile, values=None, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.values = dict(values or {})
        self.controls = {}
        self._build()

    # ------------------------------------------------------------------ construcción
    def _build(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)

        # Alternador vista rápida / avanzada (conserva selección: ambas usan self.values)
        seg = QHBoxLayout()
        self.btn_quick = QPushButton("Vista rápida")
        self.btn_adv = QPushButton("Vista avanzada")
        for b in (self.btn_quick, self.btn_adv):
            b.setCheckable(True)
            b.setObjectName("Seg")
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        grp.addButton(self.btn_quick)
        grp.addButton(self.btn_adv)
        self.btn_quick.setChecked(True)
        self.btn_quick.clicked.connect(lambda: self._show(0))
        self.btn_adv.clicked.connect(lambda: self._show(1))
        seg.addWidget(self.btn_quick)
        seg.addWidget(self.btn_adv)
        seg.addStretch(1)
        v.addLayout(seg)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._quick_view())
        self.stack.addWidget(self._advanced_view())
        v.addWidget(self.stack, 1)

        # Ayuda de la opción enfocada / seleccionada
        self.help = QLabel("Elige una opción para ver qué hace.")
        self.help.setObjectName("Help")
        self.help.setWordWrap(True)
        self.help.setMinimumHeight(46)
        v.addWidget(self.help)

    def _control_for(self, opt):
        """Crea el control de una opción y lo conecta a self.values. Devuelve el widget."""
        if opt.kind == "bool":
            cb = QCheckBox(opt.label)
            cb.setChecked(bool(self.values.get(opt.id, False)))
            cb.toggled.connect(lambda val, o=opt: self._set(o, val))
            cb.installEventFilter(self)
            self.controls[opt.id] = cb
            cb.setProperty("optid", opt.id)
            return cb
        combo = QComboBox()
        for val, lbl in opt.values:
            combo.addItem(lbl, val)
        cur = self.values.get(opt.id, opt.values[0][0] if opt.values else None)
        combo.setCurrentIndex(max(0, combo.findData(cur)))
        if not opt.verified:
            combo.setEnabled(False)
        combo.currentIndexChanged.connect(lambda _i, o=opt, c=combo: self._set(o, c.currentData()))
        combo.installEventFilter(self)
        combo.setProperty("optid", opt.id)
        self.controls[opt.id] = combo
        return combo

    def _row(self, grid, r, opt):
        name = QLabel(opt.label + ("" if opt.verified else "  (no verificado)"))
        name.setProperty("optid", opt.id)
        grid.addWidget(name, r, 0)
        ctrl = self._control_for(opt)
        if isinstance(ctrl, QCheckBox):
            ctrl.setText("")
        grid.addWidget(ctrl, r, 1)
        tag = QLabel(WHEN.get(opt.applied_when, ""))
        tag.setObjectName("Tag")
        grid.addWidget(tag, r, 2)

    def _quick_view(self):
        w = QWidget()
        g = QGridLayout(w)
        g.setColumnStretch(1, 1)
        quick = self.profile.quick_options()
        for r, opt in enumerate(quick):
            self._row(g, r, opt)
        g.setRowStretch(len(quick), 1)
        return w

    def _advanced_view(self):
        tabs = QTabWidget()
        groups = self.profile.by_group()
        from .titleprofiles import GROUPS
        for grp_name in GROUPS:
            opts = groups.get(grp_name, [])
            if not opts:
                continue
            page = QWidget()
            g = QGridLayout(page)
            g.setColumnStretch(1, 1)
            for r, opt in enumerate(opts):
                self._row(g, r, opt)
            g.setRowStretch(len(opts), 1)
            tabs.addTab(page, grp_name)
        return tabs

    # ------------------------------------------------------------------ estado / ayuda
    def _set(self, opt, val):
        self.values[opt.id] = val
        self._explain(opt)
        self.changed.emit(opt.id, val)

    def _explain(self, opt):
        extra = f"  ·  se aplica {WHEN.get(opt.applied_when, '')}  ·  lo aplica: {opt.applied_by}"
        if opt.verify:
            extra += f"  ·  se comprueba: {opt.verify}"
        self.help.setText(opt.help + extra)

    def _opt(self, oid):
        for o in self.profile.options:
            if o.id == oid:
                return o
        return None

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.FocusIn:
            oid = obj.property("optid")
            opt = self._opt(oid) if oid else None
            if opt:
                self._explain(opt)
        return super().eventFilter(obj, event)

    def _show(self, i):
        self.stack.setCurrentIndex(i)
        self.btn_quick.setChecked(i == 0)
        self.btn_adv.setChecked(i == 1)


# Estilo del panel: foco bien visible (requisito del piloto) y tema del perfil.
def panel_qss(accent, bg):
    return f"""
    QWidget {{ color: #e8e2d9; }}
    #Help {{ color: #c9c0b6; font-size: 13px; padding: 8px 10px; background: rgba(255,255,255,0.05);
             border-radius: 8px; }}
    #Tag {{ color: #8f8678; font-size: 11px; }}
    QPushButton#Seg {{ padding: 6px 16px; border-radius: 8px; background: rgba(255,255,255,0.06);
                       color: #cfc7bb; }}
    QPushButton#Seg:checked {{ background: {accent}; color: #0b0b0b; font-weight: 700; }}
    QComboBox {{ background: #241c16; border: 1px solid rgba(255,255,255,0.14); border-radius: 6px;
                 color: #e8e2d9; padding: 5px 8px; min-height: 20px; }}
    QComboBox:disabled {{ color: #6b6459; background: #1c1712; }}
    QComboBox QAbstractItemView {{ background: #241c16; color: #e8e2d9;
                                   selection-background-color: {accent}; selection-color: #0b0b0b; }}
    QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 4px;
                            border: 1px solid rgba(255,255,255,0.3); background: #241c16; }}
    QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}
    QTabWidget::pane {{ background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08);
                        border-radius: 10px; top: -1px; }}
    QTabBar::tab {{ background: transparent; color: #b7ad9f; padding: 8px 18px; margin-right: 2px; }}
    QTabBar::tab:selected {{ color: {accent}; border-bottom: 2px solid {accent}; }}
    QComboBox:focus, QCheckBox:focus, QPushButton:focus, QTabBar::tab:focus {{
        border: 2px solid {accent}; border-radius: 6px;
    }}
    """
