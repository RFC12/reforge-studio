"""Perfiles por título: resolución por Title ID, perfil genérico utilizable y aislamiento entre juegos."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reforge import titleprofiles as tp  # noqa: E402

fallos = []


def check(cond, msg):
    print(("  ✔ " if cond else "  ✘ ") + msg)
    if not cond:
        fallos.append(msg)


print("Perfil a medida de Asura's Wrath por su Title ID (43430817)")
tp.identity = lambda root: {"title_id": "43430817", "media_id": "", "version": ""}
root = tempfile.mkdtemp()
p = tp.resolve(root)
check(p.id == "asura_wrath" and p.name == "Asura's Wrath", "resuelve el perfil de Asura")
check(p.theme.bg == "#17120E" and p.theme.accent == "#C8793C", "trae su tema carbón/cobre")
check(not p.generic and len(p.adaptations) >= 1, "es a medida y lista adaptaciones verificadas (SEH 210/210…)")

print("Las opciones llevan su contrato: quién aplica, cuándo y cómo se comprueba")
res = next(o for o in p.options if o.id == "resolution_scale")
check(res.applied_by == "runtime" and "render target" in res.verify,
      "resolución interna: la aplica el runtime y comprueba las dimensiones del render target")
check(any(o.quick for o in p.options), "hay opciones de vista rápida")

print("Las mejoras no verificadas NO se ofrecen como listas para este título")
fps = next(o for o in p.options if o.id == "fps_mode")
ultra = next(o for o in p.options if o.id == "widescreen")
check(fps.verified is False and ultra.verified is False, "FPS alto y ultrapanorámica están definidas pero sin verificar")

print("Perfil genérico utilizable para un juego sin perfil a medida")
tp.identity = lambda root: {"title_id": "ABCD1234", "media_id": "", "version": ""}
otro = os.path.join(tempfile.mkdtemp(), "castlevania_sotn")
os.makedirs(otro)
g = tp.resolve(otro)
check(g.generic and g.id.startswith("generic:"), "cae en un perfil genérico")
check(g.name == "Castlevania Sotn", "saca el nombre del proyecto")
check(g.theme is tp.DEFAULT_THEME and len(g.quick_options()) >= 1, "tema por defecto y opciones generales utilizables")

print("Aislamiento entre juegos: ningún hook/adaptación de Asura se cuela en otro juego")
check(not any("SEH" in a for a in g.adaptations), "el perfil genérico no hereda adaptaciones de Asura")
check(tp.resolve(otro).title_id != tp.ASURA.title_id, "otro Title ID no resuelve al perfil de Asura")

print("Huella del XEX: dos revisiones del mismo Title ID comparten tema, no sus adaptaciones")
demo = tp.TitleProfile(
    id="demo", title_id="43430817", name="Demo", theme=tp.ASURA.theme,
    adaptations=[
        tp.Adaptation("Adaptación global (ambas revisiones)."),
        tp.Adaptation("Parche solo de la revisión A.", variants=("aaaa1111",)),
        tp.Adaptation("Parche solo de la revisión B.", variants=("bbbb2222",)),
    ])
revA = {"title_id": "43430817", "media_id": "", "version": "", "fingerprint": "aaaa1111"}
revB = {"title_id": "43430817", "media_id": "", "version": "", "fingerprint": "bbbb2222"}
adaptA = [a.text for a in demo.adaptations_for(revA)]
adaptB = [a.text for a in demo.adaptations_for(revB)]
check("Adaptación global (ambas revisiones)." in adaptA and "Adaptación global (ambas revisiones)." in adaptB,
      "ambas revisiones reciben la adaptación global (y el mismo tema)")
check("Parche solo de la revisión A." in adaptA and "Parche solo de la revisión A." not in adaptB,
      "la revisión A recibe solo su parche")
check("Parche solo de la revisión B." in adaptB and "Parche solo de la revisión B." not in adaptA,
      "la revisión B recibe solo su parche")
check(demo.theme is tp.ASURA.theme, "el tema se comparte entre revisiones")

print("status muestra los DOS resultados por separado")
tp.identity = lambda root: {"title_id": "43430817", "media_id": "", "version": ""}
st = tp.status(root, p)
check("visual" in st and "playable" in st, "perfil visual y compatibilidad jugable son campos distintos")
check(st["visual"] == "a medida", "para Asura, el perfil visual es a medida")

print()
if fallos:
    print(f"FALLOS: {len(fallos)}")
    sys.exit(1)
print("OK")
