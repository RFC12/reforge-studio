"""Compara el timbre de pistas contra dos referencias de la misma sesión (democracy.bik: 13 latino, 15 España)."""
import subprocess, sys
import numpy as np
FF = r"C:\ReForgeBuild\awlat\build\awlat\ffmpeg.exe"
B = r"H:\Call of Duty Advanced Warfare\spanish\_reforge_respaldo\_raiz"


def pcm(f, t):
    r = subprocess.run([FF, "-v", "error", "-i", f, "-map", "0:a:%d" % t, "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                       capture_output=True)
    return np.frombuffer(r.stdout, np.float32)


def fb():
    f = np.linspace(0, 8000, 257)
    mel = lambda x: 2595 * np.log10(1 + x / 700)
    pts = 700 * (10 ** (np.linspace(mel(60), mel(7600), 42) / 2595) - 1)
    m = np.zeros((40, 257))
    for i in range(40):
        a, b, c = pts[i:i + 3]
        m[i] = np.clip(np.minimum((f - a) / (b - a), (c - f) / (c - b)), 0, None)
    return m


FB = fb()
DCT = np.cos(np.pi / 40 * (np.arange(40)[None, :] + 0.5) * np.arange(1, 20)[:, None])


def feats(x):
    fr = np.lib.stride_tricks.sliding_window_view(x, 512)[::160] * np.hanning(512)
    p = np.abs(np.fft.rfft(fr)) ** 2
    e = p.sum(1)
    p = p[e > np.percentile(e, 55)]
    c = np.log(p @ FB.T + 1e-9) @ DCT.T
    return c - c.mean(0)


def model(c):
    return c.mean(0), np.cov(c.T) + np.eye(c.shape[1]) * 1e-3


def ll(c, m):
    mu, cov = m
    inv = np.linalg.inv(cov)
    _, ld = np.linalg.slogdet(cov)
    d = c - mu
    return -0.5 * (np.einsum("ij,jk,ik->i", d, inv, d) + ld).mean()


dl, de = pcm(B + r"\democracy.bik", 13), pcm(B + r"\democracy.bik", 15)
hl, he = len(dl) // 2, len(de) // 2
ML, ME = model(feats(dl[:hl])), model(feats(de[:he]))
tests = [("democracy 13 (latino, control)", dl[hl:]), ("democracy 15 (Espana, control)", de[he:])]
for spec in sys.argv[1:]:
    f, ts = spec.split("@")
    for t in ts.split(","):
        tests.append(("%s pista %s" % (f.split("\\")[-1], t), pcm(f, int(t))))
for name, x in tests:
    c = feats(x)
    a, b = ll(c, ML), ll(c, ME)
    print("%-38s latino %.2f / Espana %.2f  ->  %s (margen %.2f)" % (name, a, b, "LATINO" if a > b else "ESPANA", a - b),
          flush=True)
