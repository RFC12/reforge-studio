"""Los diálogos caben en la pantalla y se llega a sus botones.

Una pantalla de 2560x1080 deja unos 1040 píxeles de alto útiles, y con el escalado de Windows al 125 %
se queda en unos 830. Un diálogo que pida más altura que eso se abre con Guardar y Cancelar por debajo
del borde, donde no hay forma de pulsarlos.
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication      # noqa: E402

from reforge.core import AppConfig, Project                        # noqa: E402

ALTO_UTIL = 830        # lo que queda en 1080 con el escalado al 125 %
fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


# Qt se traga las excepciones de los slots: sin esto, un error al construir el diálogo solo saldría
# por pantalla y la prueba pasaría igual.
_errores = []
_hook = sys.excepthook
sys.excepthook = lambda t, v, tb: (_errores.append(f"{t.__name__}: {v}"), _hook(t, v, tb))

app = QApplication.instance() or QApplication([])
TMP = tempfile.mkdtemp(prefix="reforge-dlg-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
cfg = AppConfig.load()
proyecto = Project(name="Gears of War 2", root=tempfile.mkdtemp(prefix="reforge-dlg-"))


def revisa(nombre, dlg):
    alto = dlg.minimumSizeHint().height()
    check(alto <= ALTO_UTIL, f"{nombre}: pide {alto} px de alto como mínimo (caben {ALTO_UTIL})")
    # La última fila del diálogo (la de los botones) tiene que quedar dentro de la ventana.
    dlg.show()
    app.processEvents()
    lay = dlg.layout()
    item = lay.itemAt(lay.count() - 1) if lay and lay.count() else None
    caja = item.geometry() if item is not None else None
    check(caja is not None, f"{nombre}: la última fila se puede medir")
    if caja is not None:
        check(0 < caja.bottom() <= dlg.height(),
              f"{nombre}: los botones acaban en y={caja.bottom()} y la ventana mide {dlg.height()}")
    dlg.hide()


print("Opciones del juego")
from reforge.game_options_ui import GameOptionsDialog               # noqa: E402

revisa("Opciones del juego", GameOptionsDialog(None, cfg, proyecto, exe=""))

print("Optimizar")
from reforge.optimizer_ui import OptimizeDialog                    # noqa: E402

revisa("Optimizar", OptimizeDialog(None, cfg, proyecto.root, proyecto.name, "", ""))

check(not _errores, f"ningún diálogo lanza errores al construirse ({'; '.join(_errores[:3])})")

print()
print(f"{len(fallos)} fallos" if fallos else "0 fallos")
sys.exit(1 if fallos else 0)
