"""Teclado y ratón por juego: repartos de teclas según el tipo de juego.

rexglue emula un mando de Xbox 360 con el teclado (los cvars `keybind_*`) y, si se
quiere, con el ratón como stick derecho (`mnk_mouse`, `mnk_sensitivity`). El reparto
que trae el SDK sirve para probar, no para jugar: la puntería va en las flechas, A
está en la tecla «ñ» y el ratón ni se usa. Un shooter así es injugable.

Aquí se guardan los repartos por tipo de juego y la lista de qué juego usa cuál, para
que Gears of War 2 o Call of Duty se jueguen como cualquier shooter de PC (ratón para
apuntar, clic izquierdo disparar, clic derecho apuntar, WASD, Espacio saltar) sin que
el jugador tenga que escribir veinticuatro teclas a mano.

Nombres válidos (los del driver mnk del SDK): las letras y los números, `Space`,
`Return`, `Tab`, `Escape`, `Backspace`, `LeftShift`, `LeftCtrl`, `LeftAlt`,
`Up` `Down` `Left` `Right`, `F1`…`F12`, `Numpad0`…, `Semicolon`, `Quote`, `CapsLock`,
`Insert`, `Delete`, `Home`, `End`, `PageUp`, `PageDown`, y los del ratón:
`MouseLeft`, `MouseRight`, `MouseMiddle`, `MouseX1`, `MouseX2`.
Varias teclas para un mismo botón se separan por coma; una combinación lleva `+`.
"""
import os
import re

AUTO = "auto"

# Cada reparto: teclas que cambian respecto al del SDK, si usa el ratón, y la sensibilidad.
LAYOUTS = {
    "clasico": {
        "titulo": "Clásico (el del SDK)",
        "ayuda": "El reparto que trae rexglue. Sirve para probar un juego, no para jugarlo: la puntería "
                 "va en las flechas y no se usa el ratón.",
        "mouse": False,
        "sens": 1.0,
        "sens_x": 1.0, "sens_y": 1.0,
        "keys": {},
    },
    "shooter": {
        "titulo": "Shooter en primera persona",
        "ayuda": "Ratón para apuntar, clic izquierdo disparar, clic derecho apuntar. WASD, Espacio saltar, "
                 "Ctrl agacharse, R recargar, F cambiar arma, G granada, Mayús correr.",
        "mouse": True,
        "sens": 5.0,
        "sens_x": 1.0, "sens_y": 0.8,
        "keys": {
            "keybind_right_trigger": "MouseLeft",
            "keybind_left_trigger": "MouseRight",
            "keybind_a": "Space",
            "keybind_b": "LeftCtrl,C",
            "keybind_x": "R,E",
            "keybind_y": "F",
            "keybind_left_shoulder": "Q",
            "keybind_right_shoulder": "G",
            "keybind_lstick_up": "W", "keybind_lstick_down": "S",
            "keybind_lstick_left": "A", "keybind_lstick_right": "D",
            "keybind_lstick_press": "LeftShift",
            "keybind_rstick_up": "Numpad8", "keybind_rstick_down": "Numpad2",
            "keybind_rstick_left": "Numpad4", "keybind_rstick_right": "Numpad6",
            "keybind_rstick_press": "V,MouseMiddle",
            "keybind_dpad_up": "Up", "keybind_dpad_down": "Down",
            "keybind_dpad_left": "Left", "keybind_dpad_right": "Right",
            "keybind_back": "Tab",
            "keybind_start": "Return,Escape",
        },
    },
    "cobertura": {
        "titulo": "Shooter de coberturas (tercera persona)",
        "ayuda": "Como el de shooter, con A en Espacio para cubrirse y correr, y el cuerpo a cuerpo en V "
                 "o en el botón lateral del ratón. Pensado para Gears of War y parecidos.",
        "mouse": True,
        "sens": 5.0,
        "sens_x": 1.0, "sens_y": 0.8,
        "keys": {
            "keybind_right_trigger": "MouseLeft",
            "keybind_left_trigger": "MouseRight",
            "keybind_a": "Space",
            "keybind_b": "V,MouseX1",
            "keybind_x": "R,E",
            "keybind_y": "F",
            "keybind_left_shoulder": "Q",
            "keybind_right_shoulder": "G",
            "keybind_lstick_up": "W", "keybind_lstick_down": "S",
            "keybind_lstick_left": "A", "keybind_lstick_right": "D",
            "keybind_lstick_press": "LeftShift",
            "keybind_rstick_up": "Numpad8", "keybind_rstick_down": "Numpad2",
            "keybind_rstick_left": "Numpad4", "keybind_rstick_right": "Numpad6",
            "keybind_rstick_press": "MouseMiddle",
            "keybind_dpad_up": "Up", "keybind_dpad_down": "Down",
            "keybind_dpad_left": "Left", "keybind_dpad_right": "Right",
            "keybind_back": "Tab",
            "keybind_start": "Return,Escape",
        },
    },
    "accion": {
        "titulo": "Acción y aventura en tercera persona",
        "ayuda": "El ratón mueve la cámara, clic izquierdo ataque rápido, clic derecho ataque fuerte. "
                 "Espacio saltar, Ctrl esquivar, Mayús bloquear, E usar.",
        "mouse": True,
        "sens": 5.0,
        "sens_x": 1.0, "sens_y": 0.8,
        "keys": {
            "keybind_x": "MouseLeft",
            "keybind_y": "MouseRight",
            "keybind_a": "Space",
            "keybind_b": "LeftCtrl,C",
            "keybind_left_trigger": "Q",
            "keybind_right_trigger": "E",
            "keybind_left_shoulder": "LeftShift",
            "keybind_right_shoulder": "F",
            "keybind_lstick_up": "W", "keybind_lstick_down": "S",
            "keybind_lstick_left": "A", "keybind_lstick_right": "D",
            "keybind_lstick_press": "LeftAlt",
            "keybind_rstick_up": "Numpad8", "keybind_rstick_down": "Numpad2",
            "keybind_rstick_left": "Numpad4", "keybind_rstick_right": "Numpad6",
            "keybind_rstick_press": "MouseMiddle",
            "keybind_dpad_up": "Up", "keybind_dpad_down": "Down",
            "keybind_dpad_left": "Left", "keybind_dpad_right": "Right",
            "keybind_back": "Tab",
            "keybind_start": "Return,Escape",
        },
    },
    "carreras": {
        "titulo": "Conducción",
        "ayuda": "W acelerar, S frenar, A y D girar (también las flechas). Espacio freno de mano, "
                 "C cámara, R reiniciar, Q y E las marchas. Sin ratón.",
        "mouse": False,
        "sens": 1.0,
        "sens_x": 1.0, "sens_y": 1.0,
        "keys": {
            "keybind_right_trigger": "W",
            "keybind_left_trigger": "S",
            "keybind_lstick_left": "A,Left", "keybind_lstick_right": "D,Right",
            "keybind_lstick_up": "Up", "keybind_lstick_down": "Down",
            "keybind_lstick_press": "LeftShift",
            "keybind_a": "Space",
            "keybind_b": "LeftCtrl",
            "keybind_x": "R",
            "keybind_y": "C",
            "keybind_left_shoulder": "Q",
            "keybind_right_shoulder": "E",
            "keybind_rstick_up": "I", "keybind_rstick_down": "K",
            "keybind_rstick_left": "J", "keybind_rstick_right": "L",
            "keybind_rstick_press": "O",
            "keybind_dpad_up": "Shift+Up", "keybind_dpad_down": "Shift+Down",
            "keybind_dpad_left": "Shift+Left", "keybind_dpad_right": "Shift+Right",
            "keybind_back": "Tab",
            "keybind_start": "Return,Escape",
        },
    },
    "lucha": {
        "titulo": "Lucha",
        "ayuda": "WASD y las flechas para moverse; U I O y J K L para los seis botones, P y Ñ para los "
                 "gatillos. Sin ratón.",
        "mouse": False,
        "sens": 1.0,
        "sens_x": 1.0, "sens_y": 1.0,
        "keys": {
            "keybind_x": "U", "keybind_y": "I", "keybind_left_shoulder": "O",
            "keybind_a": "J", "keybind_b": "K", "keybind_right_shoulder": "L",
            "keybind_left_trigger": "P", "keybind_right_trigger": "Semicolon",
            "keybind_lstick_up": "W", "keybind_lstick_down": "S",
            "keybind_lstick_left": "A", "keybind_lstick_right": "D",
            "keybind_lstick_press": "LeftShift",
            "keybind_rstick_up": "Numpad8", "keybind_rstick_down": "Numpad2",
            "keybind_rstick_left": "Numpad4", "keybind_rstick_right": "Numpad6",
            "keybind_rstick_press": "Numpad5",
            "keybind_dpad_up": "Up", "keybind_dpad_down": "Down",
            "keybind_dpad_left": "Left", "keybind_dpad_right": "Right",
            "keybind_back": "Tab",
            "keybind_start": "Return,Escape",
        },
    },
    "teclado": {
        "titulo": "Teclado (plataformas, deportes, arcade)",
        "ayuda": "WASD y las flechas para moverse, Espacio y J K L I para los botones, Q y E los bumpers. "
                 "Sin ratón: para juegos que no necesitan apuntar.",
        "mouse": False,
        "sens": 1.0,
        "sens_x": 1.0, "sens_y": 1.0,
        "keys": {
            "keybind_a": "Space,J",
            "keybind_b": "LeftShift,K",
            "keybind_x": "L",
            "keybind_y": "I",
            "keybind_left_trigger": "1", "keybind_right_trigger": "3",
            "keybind_left_shoulder": "Q", "keybind_right_shoulder": "E",
            "keybind_lstick_up": "W", "keybind_lstick_down": "S",
            "keybind_lstick_left": "A", "keybind_lstick_right": "D",
            "keybind_lstick_press": "F",
            "keybind_rstick_up": "Numpad8", "keybind_rstick_down": "Numpad2",
            "keybind_rstick_left": "Numpad4", "keybind_rstick_right": "Numpad6",
            "keybind_rstick_press": "V",
            "keybind_dpad_up": "Up", "keybind_dpad_down": "Down",
            "keybind_dpad_left": "Left", "keybind_dpad_right": "Right",
            "keybind_back": "Tab",
            "keybind_start": "Return,Escape",
        },
    },
    "puntero": {
        "titulo": "Puntero (puzles, pinball, apuntar con el ratón)",
        "ayuda": "El ratón mueve el stick derecho como si fuera un puntero y el clic izquierdo es A. "
                 "Para juegos que en la consola se jugaban apuntando con el stick.",
        "mouse": True,
        "sens": 4.0,
        "sens_x": 1.2, "sens_y": 1.2,
        "keys": {
            "keybind_a": "MouseLeft,Space",
            "keybind_b": "MouseRight,Backspace",
            "keybind_x": "L", "keybind_y": "P",
            "keybind_left_trigger": "Q", "keybind_right_trigger": "E",
            "keybind_left_shoulder": "1", "keybind_right_shoulder": "3",
            "keybind_lstick_up": "W", "keybind_lstick_down": "S",
            "keybind_lstick_left": "A", "keybind_lstick_right": "D",
            "keybind_lstick_press": "F",
            "keybind_rstick_up": "Numpad8", "keybind_rstick_down": "Numpad2",
            "keybind_rstick_left": "Numpad4", "keybind_rstick_right": "Numpad6",
            "keybind_rstick_press": "MouseMiddle",
            "keybind_dpad_up": "Up", "keybind_dpad_down": "Down",
            "keybind_dpad_left": "Left", "keybind_dpad_right": "Right",
            "keybind_back": "Tab",
            "keybind_start": "Return,Escape",
        },
    },
}

ORDER = ("clasico", "shooter", "cobertura", "accion", "carreras", "lucha", "teclado", "puntero")

# Qué reparto usa cada juego. Se compara sobre el nombre sin espacios ni signos, así que
# «gearsofwar2latino», «Gears of War 2» y «gears_of_war_2» caen en la misma entrada.
# Primero las entradas más concretas: gana la primera que coincida.
GAMES = (
    ("cobertura", (
        "gearsofwar", "masseffect", "vanquish", "binarydomain", "specops",
        "armyoftwo", "kaneandlynch", "kaneylynch", "darksector", "inversion", "thebureau",
        "quantumofsolace", "blacklist", "splintercell", "wanted", "frontlines", "section8",
    )),
    ("shooter", (
        "callofduty", "modernwarfare", "blackops", "worldatwar", "advancedwarfare", "codghosts",
        "halo", "bioshock", "borderlands", "rainbowsix", "battlefield", "badcompany", "crysis",
        "farcry", "doom", "quake", "wolfenstein", "left4dead", "fear", "bulletstorm", "singularity",
        "homefront", "medalofhonor", "turok", "timeshift", "thedarkness", "rage", "killingfloor",
        "serioussam", "dukenukem", "perfectdark", "goldeneye", "brothersinarms", "operationflashpoint",
        "stalker", "metro2033", "prey", "haze", "blacksite", "shadowrun",
    )),
    ("carreras", (
        "forza", "needforspeed", "nfs", "dirt", "colinmcrae", "grid", "burnout", "midnightclub",
        "blur", "splitsecond", "nascar", "motogp", "testdrive", "projectgotham", "pgr", "flatout",
        "juiced", "hotpursuit", "mostwanted", "carbon", "undercover", "prostreet", "racedriver",
        "rally", "superstarsv8", "sonicallstarsracing", "sonicandsegaallstarsracing",
    )),
    ("lucha", (
        "streetfighter", "mortalkombat", "tekken", "soulcalibur", "marvelvs", "blazblue",
        "kingoffighters", "guiltygear", "deadoralive", "injustice", "ufcundisputed", "smackdown",
        "fightnight", "virtuafighter", "naruto", "dragonball", "supersmash", "wwe",
    )),
    ("accion", (
        "assassinscreed", "batman", "arkham", "devilmaycry", "bayonetta", "darksiders",
        "castlevania", "lordsofshadow", "princeofpersia", "darksouls", "demonssouls", "ninjagaiden",
        "godofwar", "forceunleashed", "starwars", "tombraider", "deadspace", "residentevil",
        "silenthill", "alanwake", "prototype", "saintsrow", "grandtheftauto", "gta", "reddead",
        "justcause", "crackdown", "sleepingdogs", "mafia", "maxpayne", "enslaved", "ben10",
        "transformers", "spiderman", "xmen", "lego", "sonicunleashed", "sonicgenerations",
        "theadventuresoftintin", "dantesinferno", "bulletwitch", "alicemadnessreturns",
    )),
    ("puntero", (
        "angrybirds", "peggle", "pinball", "worms", "bejeweled", "zuma", "puzzle", "solitaire",
        "boomboomrocket", "geometrywars", "fieldrunners", "plantsvszombies",
    )),
    ("teclado", (
        "fifa", "proevolution", "pes20", "madden", "nba", "nhl", "mlb", "tigerwoods", "skate",
        "tonyhawk", "rayman", "sonicthehedgehog", "banjo", "viva", "kameo", "trials", "braid",
        "limbo", "castleofillusion", "shadowcomplex", "supermeatboy", "scottpilgrim",
    )),
)

# Identidades ya vistas por ReForge (Title ID del XEX). Manda sobre el nombre.
TITLE_IDS = {
    "415608E4": "puntero",     # Angry Birds Trilogy
}


def _norm(text):
    """«Gears of War 2 (latino)» → «gearsofwar2latino»."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def suggest(name="", title_id="", exe=""):
    """Reparto que le toca a un juego: («shooter», «Call of Duty…») o («», '') si no se reconoce."""
    tid = (title_id or "").strip().upper()
    if tid in TITLE_IDS:
        return TITLE_IDS[tid], "identidad del juego"
    hay = _norm(name) + " " + _norm(exe)
    for layout, claves in GAMES:
        for clave in claves:
            if clave in hay:
                return layout, clave
    return "", ""


def keybinds(layout):
    """Las 24 teclas del reparto (las que no cambia hereda las del SDK)."""
    from .game_options import DEFAULT_KEYBINDS
    kb = dict(DEFAULT_KEYBINDS)
    kb.update({k: v for k, v in LAYOUTS.get(layout, {}).get("keys", {}).items() if k in DEFAULT_KEYBINDS})
    return kb


def apply(options, layout):
    """Escribe el reparto en unas opciones de juego. Devuelve True si se aplicó."""
    if layout not in LAYOUTS:
        return False
    data = LAYOUTS[layout]
    options.keybinds = keybinds(layout)
    options.mnk_mouse = bool(data["mouse"])
    options.mnk_sensitivity = float(data["sens"])
    options.mnk_sensitivity_x = float(data["sens_x"])
    options.mnk_sensitivity_y = float(data["sens_y"])
    options.mnk_layout = layout
    return True


def title(layout):
    return LAYOUTS.get(layout, {}).get("titulo", layout)


def describe(layout):
    data = LAYOUTS.get(layout)
    return f"{data['titulo']}: {data['ayuda']}" if data else ""


def for_game(root, exe="", name=""):
    """El reparto que le toca a un proyecto («teclado» si el juego no se reconoce)."""
    from .game_options import title_id_for_exe
    tid = ""
    if exe:
        try:
            tid = title_id_for_exe(exe) or ""
        except Exception:      # noqa: BLE001
            tid = ""
    base = os.path.splitext(os.path.basename(exe))[0] if exe else ""
    layout, _ = suggest(name or os.path.basename(os.path.normpath(root or "")), tid, base)
    return layout or "teclado"


def configure(root, exe="", name=""):
    """Deja el teclado y el ratón listos para jugar y lo guarda en las opciones del proyecto.

    Se llama al terminar de compilar: es el momento en el que ya se sabe qué juego es y el jugador
    todavía no ha tocado nada. Si el reparto ya está elegido (porque lo puso a mano o porque se compiló
    antes) no se toca: solo se rellena la primera vez.

    Devuelve (reparto, texto) o ("", "") si no había nada que hacer.
    """
    from .game_options import GameOptions
    o = GameOptions.load(root)
    if not getattr(o, "mnk_auto", True) or getattr(o, "mnk_layout", AUTO) in LAYOUTS:
        return "", ""
    layout = for_game(root, exe, name)
    o.mnk_mode = True
    apply(o, layout)                 # deja mnk_layout con el reparto concreto, visible y editable
    o.save(root)
    data = LAYOUTS[layout]
    texto = f"Teclado y ratón · {data['titulo']}: {data['ayuda']}"
    if data["mouse"]:
        texto += " El mando sigue funcionando a la vez."
    return layout, texto
