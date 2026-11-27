"""Perfiles por título y variante: la infraestructura para que elegir un juego produzca su propia experiencia.

Un perfil define, para un juego concreto (y, si hace falta, una revisión suya), su TEMA visual, sus OPCIONES
disponibles —con quién las aplica, cuándo y cómo se comprueba el valor efectivo— y las ADAPTACIONES ya
verificadas. El launcher de PC y el menú dentro del juego comparten esta MISMA definición de opciones, así que
un ajuste significa lo mismo en los dos sitios.

Elegir un juego en el Taller resuelve su perfil por el **Title ID** (y la variante por la huella del XEX:
media_id/version). Si el juego no tiene un perfil a medida, se genera uno **básico pero utilizable** a partir
del proyecto (nombre, recursos locales, opciones generales y diagnóstico de compilación). Añadir un perfil a
`PROFILES` basta para personalizar un segundo juego, sin duplicar el launcher.

Dos resultados DISTINTOS, que se muestran por separado (ver `status`):
  * «perfil visual»   → a medida o básico; se crea siempre.
  * «compatibilidad jugable» → hasta dónde llega el juego de verdad (ver reforge/milestones.py).
"""
import os
from dataclasses import dataclass, field

GROUPS = ["Juego", "Pantalla", "Gráficos", "Audio", "Controles"]


@dataclass
class OptionSpec:
    """Una opción, con su contrato: quién la aplica, cuándo y cómo se comprueba el valor efectivo."""
    id: str                       # campo de GameOptions o id sintético compartido con el menú del juego
    label: str
    group: str = "Juego"          # uno de GROUPS
    kind: str = "choice"          # "bool" | "choice"
    values: list = field(default_factory=list)   # [(valor, etiqueta)] si kind=="choice"
    help: str = ""                # explicación breve y concreta del efecto
    applied_by: str = "launcher"  # launcher | runtime | codegen
    applied_when: str = "restart"  # instant | restart | rebuild
    verify: str = ""              # cómo se comprueba el valor efectivo (lo que el runtime debe registrar)
    verified: bool = True         # ¿está verificada para este título/variante? (si no, no se ofrece como lista)
    quick: bool = False           # aparece en la vista rápida del launcher


@dataclass
class Theme:
    name: str
    bg: str                       # fondo
    accent: str                   # acento principal
    accent2: str                  # acento secundario


@dataclass
class Adaptation:
    """Una adaptación verificada. `variants` vacío = aplica a todas las revisiones del mismo Title ID; si no,
    solo a las que coincidan por media_id, version o huella del XEX."""
    text: str
    variants: tuple = ()


@dataclass
class TitleProfile:
    id: str
    title_id: str
    name: str
    theme: Theme
    options: list = field(default_factory=list)         # [OptionSpec]
    adaptations: list = field(default_factory=list)     # [Adaptation]
    variants: dict = field(default_factory=dict)        # media_id/version/huella -> etiqueta
    notes: str = ""
    generic: bool = False

    def quick_options(self):
        return [o for o in self.options if o.quick]

    def by_group(self):
        out = {g: [] for g in GROUPS}
        for o in self.options:
            out.setdefault(o.group, []).append(o)
        return out

    def adaptations_for(self, ident):
        """Las adaptaciones aplicables a ESTA revisión: las globales más las de su variante. El TEMA se comparte
        entre revisiones; las adaptaciones no."""
        keys = {ident.get("media_id", ""), ident.get("version", ""), ident.get("fingerprint", "")}
        keys.discard("")
        out = []
        for a in self.adaptations:
            if not a.variants or (set(a.variants) & keys):
                out.append(a)
        return out


DEFAULT_THEME = Theme(name="ReForge", bg="#121417", accent="#19d3a2", accent2="#2d7ff9")


# --------------------------------------------------------------------------- opciones comunes (base)
def _common_options():
    """Opciones generales utilizables por casi cualquier juego. Una sola definición para launcher y menú."""
    return [
        OptionSpec("fullscreen", "Pantalla completa", "Pantalla", "bool", quick=True,
                   help="Ocupa toda la pantalla. En ventana, usa el tamaño elegido.",
                   applied_by="launcher", applied_when="restart",
                   verify="ventana: tamaño de la imagen presentada"),
        OptionSpec("resolution_scale", "Resolución interna", "Pantalla", "choice",
                   values=[(1, "1× (1280×720)"), (2, "2× (2560×1440)"), (3, "3× (3840×2160)")], quick=True,
                   help="Resolución a la que se DIBUJA el juego (render target), independiente del tamaño de la "
                        "ventana. Subirla da más nitidez y cuesta GPU.",
                   applied_by="runtime", applied_when="restart",
                   verify="runtime: dimensiones del render target vs. imagen presentada"),
        OptionSpec("present_effect", "Escalado de imagen", "Gráficos", "choice",
                   values=[("bilinear", "Bilineal"), ("cas", "CAS (nitidez)"), ("fsr", "FSR 1")], quick=False,
                   help="Cómo se escala la imagen interna a la ventana. FSR/CAS dan más nitidez al ampliar.",
                   applied_by="runtime", applied_when="restart",
                   verify="runtime: filtro de escalado aplicado en la presentación"),
        OptionSpec("audio_mute", "Silenciar", "Audio", "bool", quick=True,
                   help="Silencia el juego al instante.",
                   applied_by="runtime", applied_when="instant",
                   verify="runtime: mezclador silenciado"),
        OptionSpec("input_backend", "Dispositivo de entrada", "Controles", "choice",
                   values=[("auto", "Automático"), ("xinput", "Mando Xbox (XInput)"),
                           ("sdl", "Mando SDL (PS/Switch/genérico)")], quick=True,
                   help="Cómo lee ReForge el mando. Automático elige según el mando conectado.",
                   applied_by="launcher", applied_when="restart",
                   verify="runtime: backend de entrada activo"),
    ]


def _fps_option(verified):
    return OptionSpec("fps_mode", "Límite de FPS", "Juego", "choice",
                      values=[("", "Del juego (base)"), ("60", "60 FPS"), ("120", "120 FPS")],
                      quick=verified, verified=verified,
                      help="Sube el límite de fotogramas. En juegos atados al framerate puede acelerar físicas, "
                           "animaciones y la ventana de los QTE: se habilita por variante solo cuando se verifica "
                           "que la duración de la secuencia y la ventana de entrada no cambian.",
                      applied_by="codegen", applied_when="rebuild",
                      verify="comparar duración de la misma secuencia/QTE y ventana de entrada con la base")


def _ultrawide_option(verified):
    return OptionSpec("widescreen", "Ultrapanorámica", "Pantalla", "choice",
                      values=[("auto", "Automática"), ("on", "Forzar"), ("off", "16:9")],
                      quick=False, verified=verified,
                      help="Relación de aspecto ultrapanorámica. Antes de habilitarla se revisan por separado "
                           "cámara, HUD, vídeos y prompts, que a menudo necesitan ajustes propios.",
                      applied_by="runtime", applied_when="restart",
                      verify="revisar por separado cámara, HUD, vídeos y prompts")


# --------------------------------------------------------------------------- registro de perfiles a medida
ASURA = TitleProfile(
    id="asura_wrath",
    title_id="43430817",
    name="Asura's Wrath",
    theme=Theme(name="Asura · carbón y cobre", bg="#17120E", accent="#C8793C", accent2="#7A1E12"),
    options=_common_options() + [_fps_option(verified=False), _ultrawide_option(verified=False)],
    adaptations=[
        Adaptation("Compilación completa (SEH_TRY/SEH_CATCH/SEH_END resuelto): 210/210 funciones con "
                   "manejadores."),
        Adaptation("Cierre intermitente al arrancar (carrera asíncrona del runtime): el launcher reintenta solo "
                   "hasta 8 veces; Asura llegó a necesitarlas."),
    ],
    notes="Piloto de la infraestructura de perfiles. Las mejoras de FPS alto y ultrapanorámica están definidas "
          "pero NO verificadas para este título: se ofrecerán cuando se compruebe su comportamiento (QTE, "
          "cámara/HUD/vídeos).",
)

PROFILES = [ASURA]


# --------------------------------------------------------------------------- identidad y resolución
def xex_fingerprint(root):
    """Huella estable de la revisión del juego: SHA-1 (16 hex) del primer MB del default.xex. '' si no se puede.

    Distingue revisiones con el MISMO Title ID (que comparten tema) para darle a cada una solo sus adaptaciones
    compatibles."""
    import hashlib
    xex = os.path.join(root, "assets", "default.xex")
    try:
        h = hashlib.sha1()
        with open(xex, "rb") as f:
            h.update(f.read(1 << 20))
        return h.hexdigest()[:16]
    except OSError:
        return ""


def identity(root):
    """(title_id, media_id, version, fingerprint) del juego del proyecto. Vacíos si no se puede leer."""
    out = {"title_id": "", "media_id": "", "version": "", "fingerprint": ""}
    try:
        from .xex import read_xex_info
        xex = os.path.join(root, "assets", "default.xex")
        if os.path.isfile(xex):
            info = read_xex_info(xex)
            for k in ("title_id", "media_id", "version"):
                out[k] = info.get(k, "") or ""
            out["fingerprint"] = xex_fingerprint(root)
    except Exception:      # noqa: BLE001
        pass
    return out


def _project_name(root):
    try:
        from . import game
        n = game.manifest_project_name(root)
        if n:
            return n
    except Exception:      # noqa: BLE001
        pass
    return os.path.basename(os.path.normpath(root)).replace("_", " ").strip().title() or "Juego"


def local_resources(root):
    """Recursos locales disponibles para la presentación del launcher (carátula, icono…)."""
    res = {}
    assets = os.path.join(root, "assets")
    res["xex"] = os.path.isfile(os.path.join(assets, "default.xex"))
    res["cover"] = res["xex"]     # la carátula sale del XEX (gameicon)
    return res


def generic_profile(root, ident=None):
    """Perfil básico PERO utilizable para un juego sin perfil a medida: nombre, recursos, opciones generales."""
    ident = ident or identity(root)
    return TitleProfile(
        id="generic:" + (ident.get("title_id") or os.path.basename(os.path.normpath(root))),
        title_id=ident.get("title_id", ""),
        name=_project_name(root),
        theme=DEFAULT_THEME,
        options=_common_options(),      # solo lo general y verificable; sin mejoras por-título sin comprobar
        adaptations=[],
        notes="Perfil básico generado automáticamente. Añade un perfil a medida en reforge/titleprofiles.py "
              "para darle tema, opciones y adaptaciones propias.",
        generic=True,
    )


def resolve(root):
    """El perfil del juego del proyecto: a medida por Title ID (y variante), o uno genérico utilizable."""
    ident = identity(root)
    tid = (ident.get("title_id") or "").upper()
    if tid:
        for p in PROFILES:
            if p.title_id.upper() == tid:
                return p
    return generic_profile(root, ident)


def variant_label(profile, ident):
    """Etiqueta de la variante (revisión) del juego según media_id/version, si el perfil la distingue."""
    for key in (ident.get("media_id", ""), ident.get("version", "")):
        if key and key in profile.variants:
            return profile.variants[key]
    return ""


def theme_for(root):
    return resolve(root).theme


def _exe_for(root):
    try:
        from . import game
        return game.game_exe(root, _project_name(root))
    except Exception:      # noqa: BLE001
        return ""


def status(root, profile=None):
    """Los DOS estados, por separado: «perfil visual» (a medida/básico, siempre creado) y «compatibilidad
    jugable» (hasta dónde llega el juego, por hitos). Devuelve un dict legible para la interfaz."""
    profile = profile or resolve(root)
    exe = _exe_for(root)
    summ = {"best_level": 0, "best_desc": "sin datos", "best_evidence": "", "last_desc": "sin datos",
            "last_first_error": "", "attempts": 0, "triage": ""}
    try:
        from . import milestones
        summ = milestones.summary(exe)
    except Exception:      # noqa: BLE001
        pass
    return {
        "visual": "a medida" if not profile.generic else "básico",
        "visual_ok": True,                 # el perfil visual siempre se crea
        "playable": summ["best_desc"],
        "playable_level": summ["best_level"],
        "evidence": summ.get("best_evidence", ""),
        "last": summ.get("last_desc", ""),
        "first_error": summ.get("last_first_error", ""),
        "attempts": summ.get("attempts", 0),
        "triage": summ.get("triage", ""),
        "exe": exe,
        "built": bool(exe),
    }
