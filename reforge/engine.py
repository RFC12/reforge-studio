"""Detección del motor del juego y su perfil de rendimiento.

Se reconoce el motor por los archivos del juego (assets) y se ajusta lo que más pesa en ese motor dentro
del runtime de rexglue, además de lo que ya ajusta el optimizador según tu PC (VRAM, hilos de CPU…).

Unreal Engine 3 (Gears of War, Mass Effect, Bioshock, Batman, Borderlands…): usa sin parar consultas de
oclusión por hardware. En rexglue cada consulta cierra el envío de comandos a la GPU y espera a que
termine (D3D12CommandProcessor::EndGuestOcclusionQuery): cientos de esperas CPU↔GPU por fotograma, que
se notan como tirones y caídas en los shooters. Con las consultas simuladas el juego recibe «visible» al
instante (query_occlusion_fake_sample_count) y no hay esperas. Además pide datos de «fetch» no válidos en
muchos títulos (pantallas negras/cierres si no se permiten).
"""
import os

ENGINES = {
    "ue3": {
        "name": "Unreal Engine 3",
        "kind": "Shooter / acción en tercera o primera persona",
        "occlusion": "fake",
        "invalid_fetch": True,
        "why": ["Consultas de oclusión simuladas: evitan una espera CPU↔GPU por cada consulta (tirones).",
                "Datos de «fetch» no válidos permitidos (muchos juegos UE3 los necesitan)."],
    },
    "iw": {"name": "IW Engine (Call of Duty)", "kind": "Shooter en primera persona", "why": []},
    "frostbite": {"name": "Frostbite", "kind": "Shooter / acción", "why": []},
    "cryengine": {"name": "CryEngine", "kind": "Shooter / acción", "why": []},
    "source": {"name": "Source", "kind": "Shooter / acción", "why": []},
    "renderware": {"name": "RenderWare", "kind": "Acción / mundo abierto", "why": []},
    "mtframework": {"name": "MT Framework (Capcom)", "kind": "Acción", "why": []},
    "generic": {"name": "Motor no reconocido", "kind": "", "why": []},
}


def detect_engine(root, limit=40000):
    """Clave del motor según los archivos del juego en assets/."""
    base = os.path.join(root, "assets")
    score = dict.fromkeys(ENGINES, 0)
    n = 0
    for dp, dn, fn in os.walk(base):
        for d in dn:
            dl = d.lower()
            if dl == "cookedxenon":
                score["ue3"] += 50
            elif dl in ("zone", "main") and any(f.lower().endswith(".ff") for f in os.listdir(os.path.join(dp, d))[:200]):
                score["iw"] += 30
            elif dl == "nativexbox360":
                score["mtframework"] += 30
        for f in fn:
            n += 1
            if n > limit:
                break
            fl = f.lower()
            ext = os.path.splitext(fl)[1]
            if ext in (".xxx", ".upk") or fl.startswith("coalesced"):
                score["ue3"] += 2
            elif ext == ".ff":
                score["iw"] += 2
            elif ext in (".sb", ".cas") or fl.endswith(".fbrb"):
                score["frostbite"] += 2
            elif fl.endswith(".360.vpk"):
                score["source"] += 5
            elif ext in (".rws", ".txd", ".dff"):
                score["renderware"] += 1
            elif ext == ".arc":
                score["mtframework"] += 1
            elif ext == ".pak" and "cry" in fl:
                score["cryengine"] += 3
        if n > limit:
            break
    best = max(score, key=score.get)
    return best if score[best] >= 4 else "generic"


def engine_info(key):
    return ENGINES.get(key or "generic", ENGINES["generic"])


def ensure_engine(root, options):
    """Detecta el motor si aún no se sabe (se guarda en las opciones del juego). Devuelve la clave."""
    if not getattr(options, "engine", ""):
        options.engine = detect_engine(root)
    return options.engine


def profile_values(options):
    """Cvars del perfil del motor (las elecciones manuales del jugador mandan)."""
    info = engine_info(getattr(options, "engine", ""))
    occl = getattr(options, "occlusion", "auto")
    if occl == "auto":
        occl = info.get("occlusion", "")      # sin preferencia del motor: lo que traiga rexglue
    return {"occlusion_query_enable": occl != "fake"} if occl in ("fake", "real") else {}


def apply_engine_profile(root, log=None):
    """Detecta el motor y aplica su perfil a las opciones del juego (solo lo que sigue en automático).
    Devuelve la clave del motor."""
    from .game_options import GameOptions
    o = GameOptions.load(root)
    before = o.engine
    key = ensure_engine(root, o)
    info = engine_info(key)
    changed = []
    if info.get("invalid_fetch") and not o.allow_invalid_fetch and o.preset() == "auto":
        o.allow_invalid_fetch = True
        changed.append("datos no válidos permitidos")
    if changed or before != key:
        o.save(root)
    if log and key != "generic" and (before != key or changed):
        log(f"Motor detectado: {info['name']} ({info['kind']}). Perfil aplicado: "
            + " ".join(info["why"] or ["ajustes generales según tu PC."]), "ok")
    return key
