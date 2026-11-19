"""Opciones del juego recompilado (cvars del runtime de rexglue) y gancho de rutas.

El runtime lee al arrancar «<carpeta del exe>/<nombre>.toml» (rex::cvar::LoadConfig).
Solo se escriben cvars que existen en el SDK 0.10 de Windows (verificadas en los binarios).

Ojo: game_data_root NO se puede poner en ese .toml (el runtime resuelve rutas antes de leerlo),
por eso se añade un gancho OnConfigurePaths al src/<proyecto>_app.h que busca «assets» solo.
"""
import glob
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field, fields

OPTIONS_FILE = "reforge_game.json"

# Teclas por defecto del SDK (src/input/mnk/mnk_input_driver.cpp)
DEFAULT_KEYBINDS = {
    "keybind_a": "Semicolon,Space", "keybind_b": "Quote,Backspace", "keybind_x": "L", "keybind_y": "P",
    "keybind_left_trigger": "Q,I", "keybind_right_trigger": "E,O",
    "keybind_left_shoulder": "1", "keybind_right_shoulder": "3",
    "keybind_lstick_up": "W", "keybind_lstick_down": "S", "keybind_lstick_left": "A",
    "keybind_lstick_right": "D", "keybind_lstick_press": "F",
    "keybind_rstick_up": "Up", "keybind_rstick_down": "Down", "keybind_rstick_left": "Left",
    "keybind_rstick_right": "Right", "keybind_rstick_press": "K",
    "keybind_dpad_up": "Shift+Up", "keybind_dpad_down": "Shift+Down",
    "keybind_dpad_left": "Shift+Left", "keybind_dpad_right": "Shift+Right",
    "keybind_back": "Z,Tab", "keybind_start": "X,Return",
}
KEYBIND_LABELS = {
    "keybind_a": "A", "keybind_b": "B", "keybind_x": "X", "keybind_y": "Y",
    "keybind_left_trigger": "Gatillo izquierdo (LT)", "keybind_right_trigger": "Gatillo derecho (RT)",
    "keybind_left_shoulder": "Bumper izquierdo (LB)", "keybind_right_shoulder": "Bumper derecho (RB)",
    "keybind_lstick_up": "Stick izq. ↑", "keybind_lstick_down": "Stick izq. ↓",
    "keybind_lstick_left": "Stick izq. ←", "keybind_lstick_right": "Stick izq. →",
    "keybind_lstick_press": "Stick izq. (clic)",
    "keybind_rstick_up": "Stick der. ↑", "keybind_rstick_down": "Stick der. ↓",
    "keybind_rstick_left": "Stick der. ←", "keybind_rstick_right": "Stick der. →",
    "keybind_rstick_press": "Stick der. (clic)",
    "keybind_dpad_up": "Cruceta ↑", "keybind_dpad_down": "Cruceta ↓",
    "keybind_dpad_left": "Cruceta ←", "keybind_dpad_right": "Cruceta →",
    "keybind_back": "Back", "keybind_start": "Start",
}
PRESENT_EFFECTS = [("bilinear", "Bilineal (estándar)"), ("cas", "AMD CAS (nitidez)"),
                   ("fsr", "AMD FSR 1 (escalado)")]
POST_EFFECTS = [("none", "Ninguno"), ("fxaa", "FXAA"), ("fxaa_extreme", "FXAA extremo")]


@dataclass
class GameOptions:
    # Gráficos
    gpu_plugin: str = "xenos"
    fullscreen: bool = False
    vsync: bool = True
    resolution_scale: int = 1
    resolution_auto: bool = True   # el Taller elige la escala interna según tu tarjeta (y la baja si no llega)
    scale_ceiling: int = 0         # escala máxima que este juego aguantó (0 = sin probar)
    present_effect: str = "bilinear"
    swap_post_effect: str = "none"
    anisotropic_override: int = 3
    present_letterbox: bool = True
    # Compatibilidad gráfica (pantallas negras). render_path: "" automático, "rtv" rápido, "rov" preciso
    render_path: str = ""
    path_trial: str = ""           # «rtv»: probando la ruta rápida tras ir lento en ROV (se confirma o se revierte)
    rov_required: bool = False     # este juego necesita ROV (falló con RTV o es un caso conocido)
    readback_resolve: bool = False
    readback_mode: str = ""        # lectura de resolves aprendida por el guardián de imagen ("some"/"fast"/"full")
    image_guard: bool = True       # guardián de imagen dentro del juego
    allow_invalid_fetch: bool = False
    ask_engine_on_play: bool = False   # menú de motor antes de jugar (por defecto no: autoconfiguración)
    # Optimizador de rendimiento: "fluido", "sin_parpadeo" u "off"
    perf_mode: str = "fluido"
    # Perfil del motor (engine.py): motor detectado, consultas de oclusión y compilación para tu CPU
    engine: str = ""
    occlusion: str = "auto"        # auto (según el motor) / real / fake (simuladas: sin esperas CPU↔GPU)
    cpu_native: bool = False       # compilar el juego con -march=native (instrucciones de tu procesador)
    # Optimización del código recompilado (registros como variables locales, como XenonRecomp/Unleashed Recompiled):
    # "auto" = Segura y baja sola si el juego falla · "max" (experimental) · "safe" · "off"
    codegen_opt: str = "auto"
    codegen_opt_level: str = "safe"  # nivel que usa «auto» ahora mismo
    codegen_opt_verified: bool = False   # ya se jugó una partida completa sin cierres con ese nivel
    # Fotogramas (pc_enhance.py): "60" VSync a 60 · "monitor" VSync a los Hz del monitor · "unlimited" sin límite
    fps_mode: str = ""             # "" = según la casilla VSync de versiones anteriores
    pc_enhanced: bool = False      # se aplicaron las mejoras para PC de la base de datos (FPS, correcciones)
    fps_unlocked: bool = False     # hay un parche de FPS desbloqueados activo (lo anota cheats.apply_cheats)
    fps_cap: float = 0.0           # tope del ritmo automático que fija el Taller si el juego no aguanta más (0 = sin tope)
    hide_cursor: bool = True       # esconder el puntero del ratón mientras se juega con mando
    guide_menu: bool = True        # menú Guía con el botón Xbox/PS del mando (o la tecla Inicio)
    button_style: str = "auto"     # iconos de botones: auto (según el mando conectado) / xbox / playstation
    mods_disabled: list = field(default_factory=list)  # packs de mods/ desactivados (los demás se aplican)
    diagnostics: bool = False      # diagnóstico de tirones: log detallado + tiempos de fotograma
    ask_engine_chosen: bool = False  # el jugador pidió el menú de motor a mano
    diag_done: bool = False        # (1.18.0, ya no se usa)
    diag_cooldown: int = 0         # partidas que faltan para que el Taller pueda volver a diagnosticar solo
    audio_queue: int = 0           # fotogramas de audio en cola (audio_maxqframes); 0 = el del optimizador
    heap_size_mb: int = 0          # montón del CRT del juego (rexcrt_heap_size_mb); 0 = el de rexglue
    auto_tune: bool = True         # el Taller ajusta solo tras cada partida (audio, diagnóstico, avisos)
    input_backend_chosen: bool = False  # el jugador eligió SDL/XInput a mano (no se cambia a automático)
    pc_offer_dismissed: bool = False
    # Controles
    input_backend: str = "auto"    # auto: XInput si hay un mando tipo Xbox conectado, si no SDL
    mnk_mode: bool = False
    mnk_mouse: bool = False
    mnk_sensitivity: float = 1.0
    keybinds: dict = field(default_factory=lambda: dict(DEFAULT_KEYBINDS))
    mnk_layout: str = "auto"       # reparto de teclas (reforge/mnklayouts.py); «auto» = el del tipo de juego
    mnk_auto: bool = True          # encender el teclado y el ratón solo cuando no hay ningún mando conectado
    # Audio e idioma (-1 = automático: el de Windows · 0 = el que decida el juego)
    audio_mute: bool = False
    language: int = -1
    country: int = 0           # región (user_country de rexglue); 0 = la natural del idioma
    # ReForge
    license: str = "auto"          # licencia del contenido (license_mask): auto / trial / full / all
    reforge_ext: bool = True       # extensión C++: perfil, Live simulado, idioma real y notificación de logros
    live_offline: bool = False     # este juego se cerraba con Live simulado (funciones online vacías): sin conexión
    auto_repair: bool = True
    repair_max_rounds: int = 100
    repair_watch_seconds: int = 45

    @classmethod
    def load(cls, root):
        o = cls()
        try:
            with open(os.path.join(root, OPTIONS_FILE), encoding="utf-8") as f:
                data = json.load(f)
            names = {f.name for f in fields(cls)}
            for k, v in data.items():
                if k in names:
                    setattr(o, k, v)
            if data.get("ask_engine_on_play") and not data.get("ask_engine_chosen"):
                o.ask_engine_on_play = False  # antes venía activado: ahora se configura solo al abrir
            if data.get("input_backend") == "sdl" and not data.get("input_backend_chosen"):
                o.input_backend = "auto"      # «sdl» era el valor por defecto de versiones anteriores
            kb = dict(DEFAULT_KEYBINDS)
            kb.update({k: v for k, v in (o.keybinds or {}).items() if k in DEFAULT_KEYBINDS})
            o.keybinds = kb
        except Exception:
            pass
        return o

    def save(self, root):
        path = os.path.join(root, OPTIONS_FILE)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)

    # ---------------------------------------------------------------- runtime .toml
    def runtime_values(self):
        scale = max(1, min(3, int(self.resolution_scale)))
        vals = {
            "gpu_plugin": self.gpu_plugin,
            "fullscreen": bool(self.fullscreen),
            "draw_resolution_scale_x": scale,
            "draw_resolution_scale_y": scale,
            "present_effect": self.present_effect,
            "swap_post_effect": self.swap_post_effect,
            "anisotropic_override": int(self.anisotropic_override),
            "present_letterbox": bool(self.present_letterbox),
            "input_backend": resolve_input_backend(self.input_backend),
            # El botón Xbox/PS llega a la extensión de ReForge (menú Guía); al juego nunca se le pasa.
            "guide_button": bool(self.guide_menu and self.reforge_ext),
            "mnk_mode": bool(self.mnk_mode),
            "mnk_mouse": bool(self.mnk_mouse),
            "mnk_sensitivity": float(self.mnk_sensitivity),
            "audio_mute": bool(self.audio_mute),
        }
        vals.update({k: v for k, v in self.keybinds.items() if k in DEFAULT_KEYBINDS})
        from .pc_enhance import frame_values
        vals.update(frame_values(self.frame_mode(), self.fps_unlocked, cap=self.fps_cap))
        if self.diagnostics:
            vals["log_level"] = "debug"   # rexglue anota shaders, texturas, disco… para cruzarlo con los tirones
        lang, country = self.effective_language()
        if lang > 0:
            vals["user_language"] = lang
            vals["user_country"] = country
        if self.render_path in ("rtv", "rov"):
            vals["render_target_path_d3d12"] = self.render_path
        if self.readback_resolve:
            vals["d3d12_readback_resolve"] = True
        if self.readback_mode in ("fast", "some", "full"):
            vals["readback_resolve"] = self.readback_mode
        if self.allow_invalid_fetch:
            vals["gpu_allow_invalid_fetch_constants"] = True
        try:
            from .engine import profile_values
            vals.update(profile_values(self))
        except Exception:      # noqa: BLE001
            pass
        try:
            from .optimizer import cached_hardware, tuned_values
            vals.update(tuned_values(cached_hardware(), self.perf_mode))
        except Exception:      # noqa: BLE001 — sin optimizador, valores de rexglue
            pass
        if self.audio_queue:      # ajuste propio del juego (lo sube el ajuste automático si el audio se corta)
            vals["audio_maxqframes"] = max(4, min(64, int(self.audio_queue)))
        if self.heap_size_mb:     # solo si al juego se le acabó el montón en una partida anterior
            vals["rexcrt_heap_enable"] = True
            vals["rexcrt_heap_size_mb"] = max(64, min(1024, int(self.heap_size_mb)))
        return vals

    def codegen_level(self):
        """Nivel de optimización del código que hay que aplicar: 'max', 'safe' u 'off'."""
        if self.codegen_opt in ("max", "safe", "off"):
            return self.codegen_opt
        return self.codegen_opt_level if self.codegen_opt_level in ("max", "safe", "off") else "safe"

    def frame_mode(self):
        """Ritmo de fotogramas: "auto", "60", "monitor" o "unlimited"."""
        if self.fps_mode in ("auto", "60", "monitor", "unlimited"):
            return self.fps_mode
        return "auto" if self.vsync else "unlimited"

    def effective_language(self):
        """(idioma, país) que recibirá el juego; (0, 0) = el que decida el juego."""
        lang = int(self.language if self.language is not None else -1)
        if lang < 0:
            return windows_language()
        if lang == 0:
            return 0, 0
        return lang, int(self.country or DEFAULT_COUNTRY.get(lang, 103))

    # ---------------------------------------------------------------- perfiles de arranque
    def preset(self):
        from .optimizer import RENDER_LADDER
        for key, _t, path, rb, inv in RENDER_LADDER:
            if key != "compat" and (self.render_path, self.readback_resolve, self.allow_invalid_fetch) == (path, rb, inv):
                return key
        if self.render_path == "rov" and self.readback_resolve and self.allow_invalid_fetch:
            return "compat"
        if self.render_path == "rov" and not self.readback_resolve and not self.allow_invalid_fetch:
            return "rov"
        if not self.render_path and not self.readback_resolve and not self.allow_invalid_fetch:
            return "auto"
        return "custom"

    def apply_preset(self, key):
        from .optimizer import RENDER_LADDER
        ladder = {k: (path, rb, inv) for k, _t, path, rb, inv in RENDER_LADDER}
        if key in ladder and key not in ("rtv", "compat"):
            self.render_path, self.readback_resolve, self.allow_invalid_fetch = ladder[key]
        elif key == "auto":
            self.render_path, self.readback_resolve, self.allow_invalid_fetch = "", False, False
        elif key == "rtv":
            self.render_path, self.readback_resolve, self.allow_invalid_fetch = "rtv", False, False
        elif key == "rov":
            self.render_path, self.readback_resolve, self.allow_invalid_fetch = "rov", False, False
        elif key == "compat":
            self.render_path, self.readback_resolve, self.allow_invalid_fetch = "rov", True, True


# Idiomas del Xbox 360 (rex::system::XLanguage) y códigos que suelen aparecer en los archivos del juego
LANGUAGES = [
    (1, "English", ("en", "eng", "english", "en-us", "en-gb", "enus", "engb", "int")),
    (2, "日本語 (Japonés)", ("ja", "jp", "jpn", "japanese", "ja-jp")),
    (3, "Deutsch (Alemán)", ("de", "ger", "deu", "german", "de-de")),
    (4, "Français (Francés)", ("fr", "fre", "fra", "french", "fr-fr")),
    (5, "Español", ("es", "spa", "esp", "spanish", "es-es", "es-mx", "esmx", "eses", "mx", "mex", "las",
                    "latam", "es-419", "es419", "esn", "esm")),
    (6, "Italiano", ("it", "ita", "italian", "it-it")),
    (7, "한국어 (Coreano)", ("ko", "kor", "korean", "ko-kr")),
    (8, "繁體中文 (Chino tradicional)", ("zh-tw", "tw", "cht", "tchinese", "zh-hant")),
    (9, "Português", ("pt", "por", "portuguese", "pt-br", "pt-pt", "ptbr", "ptb")),
    (10, "简体中文 (Chino simplificado)", ("zh-cn", "cn", "chs", "schinese", "zh-hans", "zh", "chn")),
    (11, "Polski (Polaco)", ("pl", "pol", "polish", "pl-pl")),
    (12, "Русский (Ruso)", ("ru", "rus", "russian", "ru-ru")),
]
LANGUAGE_NAMES = {i: n for i, n, _c in LANGUAGES}

# País/región del Xbox 360 según las tablas de rexglue (xam_locale.cpp): XamGetLocale lo usa y algunos
# juegos eligen con él la variante (p. ej. español latinoamericano con México).
COUNTRY_US, COUNTRY_ES, COUNTRY_MX = 103, 31, 71
DEFAULT_COUNTRY = {1: 103, 2: 53, 3: 24, 4: 34, 5: 31, 6: 50, 7: 56, 8: 101, 9: 13, 10: 20, 11: 82, 12: 88}
# (clave, idioma, país, nombre)
LANGUAGE_CHOICES = [
    ("1:103", 1, 103, "English"),
    ("2:53", 2, 53, "日本語 (Japonés)"),
    ("3:24", 3, 24, "Deutsch (Alemán)"),
    ("4:34", 4, 34, "Français (Francés)"),
    ("5:31", 5, 31, "Español (España)"),
    ("5:71", 5, 71, "Español (México / Latinoamérica)"),
    ("6:50", 6, 50, "Italiano"),
    ("7:56", 7, 56, "한국어 (Coreano)"),
    ("8:101", 8, 101, "繁體中文 (Chino tradicional)"),
    ("9:13", 9, 13, "Português (Brasil)"),
    ("10:20", 10, 20, "简体中文 (Chino simplificado)"),
    ("11:82", 11, 82, "Polski (Polaco)"),
    ("12:88", 12, 88, "Русский (Ruso)"),
]
CHOICE_NAMES = {k: n for k, _l, _c, n in LANGUAGE_CHOICES}


# Idioma de Windows → idioma y país del Xbox 360 (LANGID: idioma principal en los 10 bits bajos)
_WIN_PRIMARY = {0x09: 1, 0x11: 2, 0x07: 3, 0x0C: 4, 0x0A: 5, 0x10: 6, 0x12: 7, 0x16: 9, 0x15: 11, 0x19: 12}
_POSIX = {"en": 1, "ja": 2, "de": 3, "fr": 4, "es": 5, "it": 6, "ko": 7, "pt": 9, "pl": 11, "ru": 12}


def xinput_pad_connected():
    """¿Hay un mando tipo Xbox (XInput) conectado? None si no se puede saber (fuera de Windows)."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        class _State(ctypes.Structure):
            _fields_ = [("packet", ctypes.c_uint32), ("buttons", ctypes.c_uint16), ("lt", ctypes.c_uint8),
                        ("rt", ctypes.c_uint8), ("lx", ctypes.c_int16), ("ly", ctypes.c_int16),
                        ("rx", ctypes.c_int16), ("ry", ctypes.c_int16)]
        for dll in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
            try:
                x = ctypes.WinDLL(dll)
                break
            except OSError:
                continue
        else:
            return None
        st = _State()
        return any(x.XInputGetState(i, ctypes.byref(st)) == 0 for i in range(4))
    except Exception:      # noqa: BLE001
        return None


def resolve_input_backend(value):
    """«auto» → xinput con un mando tipo Xbox conectado (más estable en rexglue 0.10), si no sdl."""
    if value in ("sdl", "xinput"):
        return value
    return "xinput" if xinput_pad_connected() else "sdl"


def windows_language():
    """(idioma, país) del sistema. El español de España usa España; el de América, México (español latino
    en los juegos de Xbox 360). El chino distingue Taiwán/Hong Kong (tradicional) y China (simplificado)."""
    try:
        if sys.platform == "win32":
            import ctypes
            langid = int(ctypes.windll.kernel32.GetUserDefaultUILanguage())
            primary, sub = langid & 0x3FF, langid >> 10
            if primary == 0x04:
                return (8, 101) if sub in (1, 3, 5) else (10, 20)
            lang = _WIN_PRIMARY.get(primary, 1)
            if lang == 5:
                return 5, (COUNTRY_ES if sub in (1, 3) else COUNTRY_MX)
            return lang, DEFAULT_COUNTRY.get(lang, 103)
        env = (os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or "").lower()
        code, _, region = env.split(".")[0].partition("_")
        lang = _POSIX.get(code, 1)
        if lang == 5:
            return 5, (COUNTRY_ES if region in ("", "es") else COUNTRY_MX)
        if code == "zh":
            return (8, 101) if region in ("tw", "hk", "mo") else (10, 20)
        return lang, DEFAULT_COUNTRY.get(lang, 103)
    except Exception:      # noqa: BLE001
        return 1, 103


def language_key(options):
    """Clave «idioma:país» de unas opciones ('' = el que elija el juego, 'auto' = el de Windows)."""
    lang = int(getattr(options, "language", 0) if getattr(options, "language", 0) is not None else -1)
    if lang < 0:
        return "auto"
    if lang == 0:
        return ""
    return f"{lang}:{int(getattr(options, 'country', 0) or DEFAULT_COUNTRY.get(lang, 103))}"


def set_language_key(options, key):
    if key == "auto":
        options.language, options.country = -1, 0
        return
    if not key:
        options.language, options.country = 0, 0
        return
    lang, _, country = str(key).partition(":")
    options.language = int(lang)
    options.country = int(country or DEFAULT_COUNTRY.get(int(lang), 103))


def detect_language_choices(root):
    """Opciones de idioma para el combo: las del juego (el español ofrece España y México) o todas."""
    ids = detect_languages(root)
    if not ids:
        return [k for k, *_r in LANGUAGE_CHOICES]
    return [k for k, lang, _c, _n in LANGUAGE_CHOICES if lang in ids]


def detect_languages(root, limit=20000):
    """Idiomas que el juego trae en sus archivos (assets): carpetas o archivos llamados en, es, fr,
    speech/es.cfg, text_es.xml… Devuelve una lista de IDs ordenada; vacía si no se reconoce ninguno."""
    code_to_id = {c: i for i, _n, codes in LANGUAGES for c in codes}
    found = set()
    base = os.path.join(root, "assets")
    n = 0
    for dp, dn, fn in os.walk(base):
        for name in list(dn) + fn:
            n += 1
            if n > limit:
                return sorted(found)
            stem = os.path.splitext(name)[0].lower()
            tokens = [stem] + re.split(r"[_.\-\s]+", stem)
            for t in tokens:
                if t in code_to_id and len(t) >= 2:
                    found.add(code_to_id[t])
    return sorted(found)


# Cvars avanzadas: solo se escriben si el runtime/plugin del juego las trae (si no, se omiten).
ADVANCED_CVARS = ("render_target_path_d3d12", "d3d12_readback_resolve", "gpu_allow_invalid_fetch_constants",
                  "async_shader_compilation", "d3d12_pipeline_creation_threads", "texture_cache_memory_limit_soft",
                  "texture_cache_memory_limit_hard", "texture_cache_memory_limit_render_to_texture",
                  "texture_cache_memory_limit_soft_lifetime", "d3d12_queue_priority",
                  "occlusion_query_enable", "video_mode_refresh_rate", "audio_maxqframes",
                  "d3d12_allow_variable_refresh_rate_and_tearing",
                  "gpu_debug_markers", "kernel_debug_monitor", "rexcrt_heap_enable", "rexcrt_heap_size_mb")


def supported_cvars(exe):
    """Nombres de cvars avanzadas presentes en las DLL junto al .exe; None si no hay DLL que revisar."""
    d = os.path.dirname(exe)
    dlls = [f for f in glob.glob(os.path.join(d, "*.dll"))
            if os.path.basename(f).lower().startswith(("rexgpu", "rexruntime"))]
    if not dlls:
        return None
    found = set()
    for f in dlls:
        try:
            data = open(f, "rb").read()
        except OSError:
            continue
        found |= {c for c in ADVANCED_CVARS if c.encode() + b"\0" in data}
    return found


def present_effects_supported(exe):
    """Efectos de escalado que trae el runtime junto al .exe ({"bilinear"} si se compiló sin FidelityFX);
    None si no hay DLL que revisar."""
    d = os.path.dirname(exe)
    dlls = [f for f in glob.glob(os.path.join(d, "*.dll")) if os.path.basename(f).lower().startswith("rexruntime")]
    if not dlls:
        return None
    try:
        data = open(dlls[0], "rb").read()
    except OSError:
        return None
    return {"bilinear", "cas", "fsr"} if b"Guest output effect: bilinear, cas, fsr" in data else {"bilinear"}


# ---------------------------------------------------------------- licencia (XBLA)
# Igual que la opción license_mask de Xenia (rexglue tiene la misma cvar): lo que responde
# XamContentGetLicenseMask. 0 = sin licencia (los Arcade se quedan en versión de prueba), 1 = la licencia
# principal (juego completo), 0xFFFFFFFF = todas. Para jugar a tus Arcade comprados como en tu consola.
LICENSE_CHOICES = [
    ("auto", "Automática (juego completo en los Arcade)"),
    ("full", "Juego completo (licencia 1)"),
    ("all", "Todas las licencias (si «completo» no basta)"),
    ("trial", "Versión de prueba (sin licencia)"),
]
LICENSE_VALUES = {"trial": 0, "full": 1, "all": 0xFFFFFFFF}


def is_arcade_title(title_id):
    """Los Title ID de Xbox Live Arcade empiezan por 0x5841 («XA»)."""
    return str(title_id or "").upper().startswith("5841")


def title_id_for_exe(exe):
    """Title ID del juego al que pertenece el .exe (assets/default.xex de su proyecto)."""
    d = os.path.dirname(os.path.abspath(exe))
    for _ in range(5):
        xex = os.path.join(d, "assets", "default.xex")
        if os.path.isfile(xex):
            try:
                from .xex import read_xex_info
                return read_xex_info(xex).get("title_id", "")
            except Exception:      # noqa: BLE001
                return ""
        d = os.path.dirname(d)
    return ""


def license_value(options, title_id):
    """Valor de license_mask o None (no tocar: el del runtime)."""
    choice = getattr(options, "license", "auto")
    if choice == "auto":
        return 1 if is_arcade_title(title_id) else None
    return LICENSE_VALUES.get(choice)


def _toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return f"{v:.3f}"
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


BEGIN = "# >>> ReForge Studio (opciones del juego) >>>"
END = "# <<< ReForge Studio <<<"


def runtime_config_path(exe):
    return os.path.join(os.path.dirname(exe), os.path.splitext(os.path.basename(exe))[0] + ".toml")


def write_runtime_config(exe, options):
    """Escribe el bloque gestionado en <exe>.toml conservando cualquier otra línea del usuario."""
    path = runtime_config_path(exe)
    old = ""
    if os.path.isfile(path):
        old = open(path, encoding="utf-8-sig", errors="replace").read().replace("\ufeff", "")
        old = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", "", old, flags=re.S)
    values = options.runtime_values()
    sup = supported_cvars(exe)
    if sup is not None:
        values = {k: v for k, v in values.items() if k not in ADVANCED_CVARS or k in sup}
    lic = license_value(options, title_id_for_exe(exe))
    if lic is not None:
        values["license_mask"] = lic
    effects = present_effects_supported(exe)
    if effects is not None and values.get("present_effect") not in effects:
        values["present_effect"] = "bilinear"      # FSR/CAS no vienen en este runtime: se ignoraría
    managed = set(values) | set(ADVANCED_CVARS) | {"license_mask"}
    # quitar del texto del usuario las claves que ahora gestiona ReForge (evita claves duplicadas)
    keep = [ln for ln in old.splitlines()
            if not re.match(r"^\s*([A-Za-z0-9_]+)\s*=", ln) or re.match(r"^\s*([A-Za-z0-9_]+)", ln).group(1) not in managed]
    block = [BEGIN, "# Generado por ReForge Studio. Cámbialo desde «Opciones del juego»."]
    block += [f"{k} = {_toml_value(v)}" for k, v in values.items()]
    block.append(END)
    text = "\n".join(block) + "\n" + ("\n".join(keep).strip() + "\n" if any(s.strip() for s in keep) else "")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    try:      # perfil, Live, idioma y notificaciones para la extensión de ReForge (reforge_ext.cpp)
        from .profile import write_ext_ini
        write_ext_ini(exe, options)
    except Exception:      # noqa: BLE001 — nunca impedir que el juego arranque por esto
        pass
    return path


# ---------------------------------------------------------------- gancho de rutas
HOOK_BEGIN = "  // >>> ReForge Studio: carpeta del juego automática (no editar este bloque)"
HOOK_END = "  // <<< ReForge Studio"


def app_header(root):
    c = sorted(glob.glob(os.path.join(root, "src", "*_app.h")))
    return c[0] if c else ""


def ensure_paths_hook(root):
    """Hace que el .exe encuentre «assets» aunque se abra con doble clic (y «update» si hay una actualización
    instalada). Devuelve True si cambió."""
    path = app_header(root)
    if not path:
        return False
    txt = open(path, encoding="utf-8").read()
    assets = os.path.join(os.path.abspath(root), "assets").replace("\\", "/")
    hook = (f"{HOOK_BEGIN}\n"
            "  void OnConfigurePaths(rex::PathConfig& paths) override {\n"
            "    if (paths.game_data_root.empty()) {\n"
            "      const std::filesystem::path exe_dir = rex::filesystem::GetExecutableFolder();\n"
            "      const std::filesystem::path candidates[] = {\n"
            "          exe_dir / \"assets\", exe_dir.parent_path() / \"assets\",\n"
            f"          std::filesystem::path(u8\"{assets}\")}};\n"
            "      for (const auto& c : candidates) {\n"
            "        std::error_code ec;\n"
            "        if (std::filesystem::is_directory(c, ec)) { paths.game_data_root = c; break; }\n"
            "      }\n"
            "    }\n"
            "    // actualización del juego instalada por ReForge: <proyecto>/update se monta como «update:»\n"
            "    if (paths.update_data_root.empty() && !paths.game_data_root.empty()) {\n"
            "      std::filesystem::path g = paths.game_data_root;\n"
            "      if (g.filename().empty()) g = g.parent_path();\n"
            "      std::error_code ec;\n"
            "      if (std::filesystem::is_directory(g.parent_path() / \"update\", ec))\n"
            "        paths.update_data_root = g.parent_path() / \"update\";\n"
            "    }\n"
            "  }\n"
            f"{HOOK_END}\n")
    if HOOK_BEGIN in txt:
        new = re.sub(re.escape(HOOK_BEGIN) + r".*?" + re.escape(HOOK_END) + r"\n", lambda _m: hook, txt, flags=re.S)
    else:
        if re.search(r"^\s*void\s+OnConfigurePaths\s*\(", txt, re.M):
            return False          # el usuario ya tiene su propia versión: no se toca
        m = re.search(r"^(\s*using rex::ReXApp::ReXApp;\s*\n)", txt, re.M)
        if not m:
            return False
        new = txt[:m.end()] + "\n" + hook + txt[m.end():]
    for inc in ("#include <rex/filesystem.h>", "#include <filesystem>"):
        if inc not in new:
            new = new.replace("#include <rex/rex_app.h>", "#include <rex/rex_app.h>\n" + inc, 1)
    if new == txt:
        return False
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new)
    os.replace(tmp, path)
    return True
