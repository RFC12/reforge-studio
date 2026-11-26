"""El diálogo «Ports de la comunidad» se construye sin errores y muestra los puertos registrados."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from reforge import communityports as cp          # noqa: E402
from reforge.communityports_ui import CommunityPortsDialog  # noqa: E402

print("El diálogo se construye con los puertos registrados")
d = CommunityPortsDialog()
check(d is not None, "se construye sin lanzar")
# debe haber una tarjeta por puerto (más el stretch)
n_puertos = len(cp.all_ports())
textos = " ".join(w.text() for w in d.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel))
check("Crash of the Titans" in textos, "muestra el puerto de Crash of the Titans")
check("Forza Horizon" in textos, "muestra el puerto de Forza Horizon")
check(n_puertos >= 2, "hay al menos dos puertos")
d.deleteLater()

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
