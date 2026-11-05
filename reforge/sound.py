"""Sonido de la notificación de logros.

* «ReForge»: un timbre propio generado aquí (sin recursos de terceros).
* «Personalizado»: un archivo del usuario (WAV directamente; MP3/OGG/… se convierten con el decodificador
  de Qt o, si no puede, con ffmpeg si está instalado).
Siempre se guarda como WAV PCM de 16 bits, sin el silencio inicial (suena justo al aparecer la
notificación) y con el volumen normalizado; el juego lo reproduce con PlaySound (Windows) o SDL.
"""
import array
import math
import os
import shutil
import subprocess
import sys
import tempfile
import wave

from .core import config_dir

RATE = 48000


def profile_dir():
    return os.path.join(config_dir(), "profile")


def reforge_chime_path():
    return os.path.join(profile_dir(), "reforge_chime.wav")


def custom_sound_path():
    return os.path.join(profile_dir(), "achievement.wav")


def _write_wav(path, samples, channels=2, rate=RATE):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with wave.open(tmp, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes() if sys.byteorder == "little" else _swapped(samples).tobytes())
    os.replace(tmp, path)


def _swapped(a):
    b = array.array("h", a)
    b.byteswap()
    return b


def generate_reforge_chime(path=None):
    """Timbre propio de ReForge: dos notas de campana (Mi6 → Si6) con eco suave, ~1,1 s."""
    path = path or reforge_chime_path()
    n = int(RATE * 1.15)
    out = array.array("h", bytes(4 * n))
    notes = [(0.00, 1318.5, 0.55), (0.11, 1975.5, 0.60)]       # (inicio s, frecuencia Hz, amplitud)
    for i in range(n):
        t = i / RATE
        v = 0.0
        for start, f, amp in notes:
            dt = t - start
            if dt < 0:
                continue
            env = (1 - math.exp(-dt * 400)) * math.exp(-dt * 4.2)
            v += amp * env * (math.sin(2 * math.pi * f * dt) + 0.25 * math.sin(2 * math.pi * 2.01 * f * dt)
                              + 0.08 * math.sin(2 * math.pi * 3.0 * f * dt))
            if dt > 0.09:   # eco
                e = dt - 0.09
                v += 0.18 * amp * math.exp(-e * 5) * math.sin(2 * math.pi * f * e)
        s = int(max(-1.0, min(1.0, v * 0.55)) * 32767)
        out[2 * i] = s
        out[2 * i + 1] = s
    _write_wav(path, out)
    return path


def _read_pcm16(path):
    """(muestras int16 entrelazadas, canales, frecuencia). Acepta WAV PCM de 8/16/24/32 bits."""
    with wave.open(path, "rb") as w:
        ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if width == 2:
        a = array.array("h")
        a.frombytes(raw)
        if sys.byteorder != "little":
            a.byteswap()
    elif width == 1:
        a = array.array("h", ((b - 128) << 8 for b in raw))
    elif width in (3, 4):
        a = array.array("h", (int.from_bytes(raw[i + width - 2:i + width], "little", signed=True)
                              for i in range(0, len(raw), width)))
    else:
        raise ValueError(f"Formato WAV no soportado ({width * 8} bits)")
    return a, ch, rate


def process(samples, channels, rate, threshold_db=-45.0, peak_db=-3.0, max_seconds=4.0, volume=1.0):
    """Quita el silencio inicial y final, limita la duración y normaliza el pico."""
    thr = int(32767 * 10 ** (threshold_db / 20))
    frames = len(samples) // channels
    loud = [i for i in range(frames) if max(abs(samples[i * channels + c]) for c in range(channels)) > thr]
    if not loud:
        raise ValueError("El sonido está en silencio")
    first = max(0, loud[0] - int(rate * 0.005))
    last = min(frames, loud[-1] + int(rate * 0.25), first + int(rate * max_seconds))
    seg = samples[first * channels:last * channels]
    peak = max(1, max(abs(x) for x in seg))
    gain = (32767 * 10 ** (peak_db / 20)) / peak * max(0.0, min(1.0, volume))
    fade = int(rate * 0.04)
    out = array.array("h", bytes(2 * len(seg)))
    n = len(seg) // channels
    for i in range(n):
        f = min(1.0, (n - i) / fade) if fade else 1.0
        for c in range(channels):
            out[i * channels + c] = int(max(-32768, min(32767, seg[i * channels + c] * gain * f)))
    return out


def _decode_with_qt(src, dst):
    try:
        from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer, QUrl
        from PySide6.QtMultimedia import QAudioDecoder, QAudioFormat
    except ImportError:
        return False
    app = QCoreApplication.instance()
    if app is None:
        return False
    fmt = QAudioFormat()
    fmt.setSampleRate(RATE)
    fmt.setChannelCount(2)
    fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
    dec = QAudioDecoder()
    dec.setAudioFormat(fmt)
    dec.setSource(QUrl.fromLocalFile(os.path.abspath(src)))
    chunks, state = [], {"err": False}
    loop = QEventLoop()

    def ready():
        buf = dec.read()
        data = buf.constData()
        chunks.append(bytes(data) if data is not None else b"")

    def err(*_a):
        state["err"] = True
        loop.quit()
    dec.bufferReady.connect(ready)
    dec.finished.connect(loop.quit)
    dec.error.connect(err)
    QTimer.singleShot(15000, loop.quit)
    dec.start()
    loop.exec()
    data = b"".join(chunks)
    if state["err"] or not data:
        return False
    a = array.array("h")
    a.frombytes(data[: len(data) // 2 * 2])
    _write_wav(dst, a)
    return True


def _decode_with_ffmpeg(src, dst):
    exe = shutil.which("ffmpeg")
    if not exe:
        return False
    r = subprocess.run([exe, "-v", "error", "-y", "-i", src, "-ac", "2", "-ar", str(RATE), "-sample_fmt", "s16", dst],
                       capture_output=True, stdin=subprocess.DEVNULL,
                       creationflags=0x08000000 if os.name == "nt" else 0)
    return r.returncode == 0 and os.path.isfile(dst)


def import_sound(src, dst=None):
    """Convierte el archivo elegido por el usuario al WAV de la notificación. Devuelve la ruta."""
    dst = dst or custom_sound_path()
    work = src
    tmp = None
    try:
        try:
            samples, ch, rate = _read_pcm16(src)
        except (wave.Error, EOFError, ValueError):
            fd, tmp = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            if not (_decode_with_qt(src, tmp) or _decode_with_ffmpeg(src, tmp)):
                raise RuntimeError("No se pudo leer ese audio. Usa un WAV, o instala ffmpeg para MP3/OGG.")
            work = tmp
            samples, ch, rate = _read_pcm16(work)
        _write_wav(dst, process(samples, ch, rate), ch, rate)
        return dst
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)


def sound_for_profile(profile):
    """WAV que corresponde al perfil (genera el timbre de ReForge si hace falta) o '' si va sin sonido."""
    kind = getattr(profile, "toast_sound", "reforge")
    if kind == "none":
        return ""
    if kind == "custom" and os.path.isfile(custom_sound_path()):
        return custom_sound_path()
    p = reforge_chime_path()
    if not os.path.isfile(p):
        generate_reforge_chime(p)
    return p


def export_for_game(profile, exe_dir):
    """Copia el sonido (con el volumen elegido) junto al juego. Devuelve el nombre del archivo o ''."""
    src = sound_for_profile(profile)
    dst = os.path.join(exe_dir, "reforge_achievement.wav")
    if not src:
        if os.path.exists(dst):
            try:
                os.remove(dst)
            except OSError:
                pass
        return ""
    vol = max(0, min(100, int(getattr(profile, "toast_volume", 80)))) / 100.0
    samples, ch, rate = _read_pcm16(src)
    out = array.array("h", (int(s * vol) for s in samples))
    _write_wav(dst, out, ch, rate)
    return os.path.basename(dst)
