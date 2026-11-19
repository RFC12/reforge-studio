"""¿Qué mando está conectado? Para elegir los iconos de botones (Xbox o PlayStation).

Se mira el hardware presente (no lo que ve el juego): un DualSense/DualShock usado a través de DS4Windows,
DSX o Steam aparece ante el juego como «Mando Xbox 360», pero su identificador de Sony (VID 054C) sigue en la
lista de dispositivos de Windows, por USB o por Bluetooth.
"""
import re
import sys
import time

SONY_RE = re.compile(r"VID[_&](?:0002)?054C", re.I)
NINTENDO_RE = re.compile(r"VID[_&](?:0002)?057E", re.I)
_cache = {"t": 0.0, "ids": None}


def present_device_ids():
    """Identificadores de instancia de todos los dispositivos presentes (Windows; [] en otros sistemas)."""
    if sys.platform != "win32":
        return []
    if _cache["ids"] is not None and time.time() - _cache["t"] < 20:
        return _cache["ids"]
    import ctypes
    from ctypes import wintypes
    cm = ctypes.WinDLL("cfgmgr32")
    flags = 0x00000100        # CM_GETIDLIST_FILTER_PRESENT
    size = wintypes.ULONG(0)
    ids = []
    if cm.CM_Get_Device_ID_List_SizeW(ctypes.byref(size), None, flags) == 0 and size.value:
        buf = ctypes.create_unicode_buffer(size.value)
        if cm.CM_Get_Device_ID_ListW(None, buf, size.value, flags) == 0:
            ids = [s for s in ctypes.wstring_at(ctypes.addressof(buf), size.value).split("\0") if s]
    _cache.update(t=time.time(), ids=ids)
    return ids


def detect(ids=None):
    """'playstation', 'nintendo' o 'xbox' (por defecto) según los mandos conectados."""
    ids = present_device_ids() if ids is None else ids
    if any(SONY_RE.search(i) for i in ids):
        return "playstation"
    if any(NINTENDO_RE.search(i) and ("HID" in i.upper() or "BTHENUM" in i.upper()) for i in ids):
        return "nintendo"
    return "xbox"


def resolve(style, ids=None):
    """Estilo de iconos a usar: el elegido, o el del mando conectado si es «auto»."""
    if style in ("xbox", "playstation"):
        return style
    found = detect(ids)
    return "playstation" if found == "playstation" else "xbox"


# DualSense / DualSense Edge por su identificador de producto de Sony (VID 054C).
DUALSENSE_RE = re.compile(r"VID[_&](?:0002)?054C&PID[_&](?:0CE6|0DF2)", re.I)


def dualsense_present(ids=None):
    """True si hay un DualSense o DualSense Edge conectado (por USB o Bluetooth)."""
    ids = present_device_ids() if ids is None else ids
    return any(DUALSENSE_RE.search(i) for i in ids)


def advice(ids=None):
    """Consejo breve si hay un mando Sony y sus botones pueden salir mal en el juego, o '' si no aplica.

    La causa más común en PC (la misma que detecta ShiftGlue en su driver SDL) es que **Steam Input** toma el
    DualSense y se lo presenta al juego como un mando virtual de Xbox: entonces los botones de cara, el panel
    táctil o los gatillos salen cambiados. ReForge ya deja una base de mapeos SDL al día junto al juego, pero
    si Steam Input está activo esa base no se aplica, porque el juego ya no ve el DualSense real.
    """
    ids = present_device_ids() if ids is None else ids
    if not any(SONY_RE.search(i) for i in ids):
        return ""
    return ("Veo un mando Sony conectado. Si los botones salen cambiados dentro del juego, casi siempre es "
            "Steam Input, que se queda con el DualSense y se lo pasa al juego como un mando de Xbox. "
            "Solución: en Steam, propiedades del juego → Controlador → «Desactivar Steam Input», o cierra "
            "Steam mientras juegas. ReForge ya dejó una base de mapeos SDL al día junto al juego para el resto "
            "de casos.")
