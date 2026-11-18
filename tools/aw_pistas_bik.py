"""Idioma de cada pista de un .bik (transcripción) y, en las pistas en español, la prueba del ceceo (θ = España)."""
import re, subprocess, sys, unicodedata
import numpy as np
from faster_whisper import WhisperModel
FF = r"C:\ReForgeBuild\awlat\build\awlat\ffmpeg.exe"
model = WhisperModel("small", device="cpu", compute_type="int8")
f = sys.argv[1]
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 90


def pcm(t, sr):
    r = subprocess.run([FF, "-v", "error", "-i", f, "-map", "0:a:%d" % t, "-t", str(secs), "-ac", "1", "-ar", str(sr),
                        "-f", "f32le", "-"], capture_output=True)
    return np.frombuffer(r.stdout, np.float32)


def hf(x):
    if len(x) < 256:
        return None
    s = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    fr = np.fft.rfftfreq(len(x), 1 / 48000)
    tot = s[(fr > 300) & (fr < 12000)].sum()
    return s[(fr > 4000) & (fr < 11000)].sum() / tot if tot > 0 else None


def strip(w):
    return "".join(c for c in unicodedata.normalize("NFD", w.lower()) if c.isalpha())


r = subprocess.run([FF, "-hide_banner", "-i", f], capture_output=True, text=True, errors="replace").stderr
n = len(re.findall(r"Stream #0:\d+\[0x[0-9a-f]+\]: Audio", r))
sel = [int(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 else range(n)
for t in sel:
    x16 = pcm(t, 16000)
    if len(x16) == 0 or np.abs(x16).max() < 1e-3:
        print("pista %d: silencio" % t, flush=True)
        continue
    segs, info = model.transcribe(x16, beam_size=1, word_timestamps=True)
    segs = list(segs)
    text = " ".join(s.text.strip() for s in segs)
    extra = ""
    if info.language == "es":
        x = pcm(t, 48000)
        th, ss = [], []
        for sg in segs:
            for w in sg.words or []:
                ww = strip(w.word)
                v = hf(x[int(w.start * 48000):int(w.end * 48000)])
                if v is None:
                    continue
                if re.search(r"z|c[ei]", ww) and "s" not in ww:
                    th.append(v)
                elif "s" in ww and not re.search(r"z|c[ei]", ww):
                    ss.append(v)
        if th and ss:
            extra = "  [c/z÷s = %.2f con %d palabras: %s]" % (np.mean(th) / np.mean(ss), len(th),
                                                             "ESPAÑA (θ)" if np.mean(th) / np.mean(ss) < 0.35 else "LATINO (s)")
    safe = text.encode("ascii", "replace").decode()
    print("pista %d [%s %.2f]%s: %s" % (t, info.language, info.language_probability, extra, safe[:160]), flush=True)

