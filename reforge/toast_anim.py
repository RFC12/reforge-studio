"""Línea de tiempo de la notificación de logros.

Es la misma que ComputeToastFrame() en la extensión C++ (ext_cpp.py, bloque «toast-render»): la vista
previa de la página Perfil la usa para enseñar exactamente lo que verás en el juego, y una prueba
compila la versión C++ y compara los valores.

Fases: el círculo aparece con rebote y una onda → la cápsula se despliega con chispas → los textos
entran deslizándose y los G cuentan → un destello recorre la cápsula → la insignia alterna logo ↔ icono
con un giro → al final vuelve al logo, se repliega, late y desaparece.
"""
import math
from dataclasses import dataclass


def clamp01(v):
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def seg(t, a, b):
    return clamp01((t - a) / (b - a))


def out_cubic(t):
    return 1.0 - (1.0 - t) ** 3


def in_cubic(t):
    return t * t * t


def out_back(t):
    c1 = 1.70158
    c3 = c1 + 1.0
    u = t - 1.0
    return 1.0 + c3 * u ** 3 + c1 * u ** 2


@dataclass
class ToastFrame:
    alpha: float
    circle: float
    open: float
    title_a: float
    label_a: float
    title_in: float
    label_in: float
    count: float
    shine: float
    wave: float
    wave2: float
    sparks: float
    ring: float
    squash: float
    face: int        # 0 = logo del perfil, 1 = icono del logro / trofeo


FIELDS = ("alpha", "circle", "open", "title_a", "label_a", "title_in", "label_in", "count", "shine", "wave",
          "wave2", "sparks", "ring", "squash", "face")


def compute(age, total, has_badge):
    alpha = seg(age, 0.0, 0.08) * (1.0 - seg(age, total - 0.12, total))
    k = seg(age, total - 0.40, total)
    if k <= 0.0:
        circle = out_back(seg(age, 0.0, 0.38))
    elif k < 0.35:
        circle = 1.0 + 0.15 * out_cubic(k / 0.35)
    else:
        circle = 1.15 * (1.0 - in_cubic((k - 0.35) / 0.65))
    open_ = out_cubic(seg(age, 0.28, 0.74)) * (1.0 - in_cubic(seg(age, total - 0.90, total - 0.40)))
    out = 1.0 - seg(age, total - 1.10, total - 0.85)
    title_in = out_cubic(seg(age, 0.55, 0.90))
    label_in = out_cubic(seg(age, 0.68, 1.05))
    squash, face = 1.0, (0 if has_badge else 1)
    if has_badge and age > 1.4:
        freeze = total - 1.0
        ph = max(0.0, min(age, freeze) - 1.4) / 1.8
        n = int(ph)
        fr = ph - n
        face = n % 2
        if fr > 0.84:
            g = (fr - 0.84) / 0.16
            if age < freeze:
                squash = abs(math.cos(math.pi * g))
            if g >= 0.5 or age >= freeze:
                face ^= 1
        if age >= freeze and face == 1:
            g = seg(age, freeze, freeze + 0.22)
            squash = abs(math.cos(math.pi * g))
            if g >= 0.5:
                face = 0
    return ToastFrame(alpha=alpha, circle=circle, open=open_, title_a=title_in * out, label_a=label_in * out,
                      title_in=title_in, label_in=label_in, count=out_cubic(seg(age, 0.75, 1.55)),
                      shine=seg(age, 0.85, 1.55), wave=seg(age, 0.04, 0.80), wave2=seg(age, total - 0.40, total - 0.05),
                      sparks=seg(age, 0.30, 1.25), ring=age * 3.6, squash=squash, face=face)
