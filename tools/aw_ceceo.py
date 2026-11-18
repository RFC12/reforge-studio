"""Distingue español latino de España: energía de alta frecuencia en las "c/z" (θ en España, /s/ en Latinoamérica)
comparada con las "s" de la misma pista."""
import re, subprocess, sys, unicodedata
import numpy as np
from faster_whisper import WhisperModel
FF = r"C:\ReForgeBuild\awlat\build\awlat\ffmpeg.exe"
model = WhisperModel("small", device="cpu", compute_type="int8")


def pcm(f, t, sr=48000):
    r = subprocess.run([FF, "-v", "error", "-i", f, "-map", "0:a:%d" % t, "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                       capture_output=True)
    return np.frombuffer(r.stdout, np.float32)


def hf_ratio(x, sr=48000):
    if len(x) < 256:
        return None
    s = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / sr)
    tot = s[(f > 300) & (f < 12000)].sum()
    return s[(f > 5000) & (f < 11000)].sum() / tot if tot > 0 else None


def strip(w):
    return "".join(c for c in unicodedata.normalize("NFD", w.lower()) if c.isalpha())


def analyze(f, t):
    x = pcm(f, t)
    import tempfile, os, soundfile
    segs, _ = model.transcribe(x[::3].copy(), language="es", word_timestamps=True, beam_size=1)
    th, ss = [], []
    for sg in segs:
        for w in sg.words:
            ww = strip(w.word)
            a, b = int(w.start * 48000), int(w.end * 48000)
            r = hf_ratio(x[a:b])
            if r is None:
                continue
            if re.search(r"z|c[ei]", ww) and "s" not in ww:
                th.append(r)
            elif "s" in ww and not re.search(r"z|c[ei]", ww):
                ss.append(r)
    return np.mean(th) if th else float("nan"), np.mean(ss) if ss else float("nan"), len(th), len(ss)


for f in sys.argv[1:]:
    for t in (4, 5):
        z, s, nz, ns = analyze(f, t)
        print("%s pista %d: c/z=%.3f (%d palabras)  s=%.3f (%d)  relación c/z÷s=%.2f"
              % (f.split("\\")[-1], t, z, nz, s, ns, z / s), flush=True)
