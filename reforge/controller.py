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
