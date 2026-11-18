"""¿Qué pista de un .bik tiene al actor latino de Irons? Compara el timbre (MFCC) con frases de Irons:
latinas (las traídas de 360, al final de los paks) y de España (las originales del PC)."""
import os, re, subprocess, sys
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
import aw_doblaje_latino as A
FF = r"C:\ReForgeBuild\awlat\build\awlat\ffmpeg.exe"
lang = r"H:\Call of Duty Advanced Warfare\spanish"
bdir = os.path.join(lang, A.BACKUP_DIR)
cur, orig = {}, {}
for n in os.listdir(lang):
    m = re.match(r"spa_soundfile(\d+)\.pak$", n, re.I)
    if m:
        i = int(m.group(1)); cur[i] = os.path.getsize(os.path.join(lang, n))
        b = os.path.join(bdir, n); orig[i] = os.path.getsize(b) if os.path.exists(b) else cur[i]


def decode(data_or_path, track=None, sr=16000):
    if isinstance(data_or_path, bytes):
        r = subprocess.run([FF, "-v", "error", "-i", "-", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                           input=data_or_path, capture_output=True)
    else:
        r = subprocess.run([FF, "-v", "error", "-i", data_or_path, "-map", "0:a:%d" % track, "-ac", "1", "-ar", str(sr),
                            "-f", "f32le", "-"], capture_output=True)
    return np.frombuffer(r.stdout, np.float32)


def mel_fb(sr=16000, n=512, m=40):
    f = np.linspace(0, sr / 2, n // 2 + 1)
    mel = lambda x: 2595 * np.log10(1 + x / 700)
    pts = 700 * (10 ** (np.linspace(mel(60), mel(7600), m + 2) / 2595) - 1)
    fb = np.zeros((m, len(f)))
    for i in range(m):
        a, b, c = pts[i:i + 3]
        fb[i] = np.clip(np.minimum((f - a) / (b - a), (c - f) / (c - b)), 0, None)
    return fb


FB = mel_fb()


def mfcc(x):
    n, hop = 512, 160
    if len(x) < n:
        return None
    fr = np.lib.stride_tricks.sliding_window_view(x, n)[::hop] * np.hanning(n)
    p = np.abs(np.fft.rfft(fr)) ** 2
    e = p.sum(1)
    keep = e > np.percentile(e, 60)  # solo tramos con voz
    lm = np.log(p[keep] @ FB.T + 1e-9)
    k = np.arange(40)
    dct = np.cos(np.pi / 40 * (k[None, :] + 0.5) * np.arange(1, 20)[:, None])
    c = lm @ dct.T
    c -= c.mean(0)  # quita el canal (CMN) y se queda con la forma
    return c


def stats(c):
    return np.concatenate([c.std(0)])


lat, esp = [], []
pak = {}
for name in sorted(os.listdir(lang)):
    if not (name.startswith("spa_") and name.endswith(".ff")) or "_mp" in name or "patch" in name:
        continue
    z = A.zone_pc(open(os.path.join(lang, name), "rb").read())
    zb = A.zone_pc(open(os.path.join(bdir, name), "rb").read()) if os.path.exists(os.path.join(bdir, name)) else None
    if zb is None:
        continue
    rn = [r for r in A.refs_pc(z, cur) if "_irs_" in r["alias"]]
    ro = {r["alias"]: r for r in A.refs_pc(zb, orig) if "_irs_" in r["alias"]}
    print(name, len(rn), len(ro))
    for r in rn:
        o = ro.get(r["alias"])
        if not o or r["len"] < 20000 or o["off"] == r["off"]:
            continue
        f = pak.get(r["idx"]) or pak.setdefault(r["idx"], open(os.path.join(lang, "spa_soundfile%d.pak" % r["idx"]), "rb"))
        f.seek(r["off"]); dl = f.read(r["len"])
        f2 = pak.get(o["idx"]) or pak.setdefault(o["idx"], open(os.path.join(lang, "spa_soundfile%d.pak" % o["idx"]), "rb"))
        f2.seek(o["off"]); do = f2.read(o["len"])
        lat.append(decode(dl)); esp.append(decode(do))
        if len(lat) >= 25:
            break
    if len(lat) >= 25:
        break
print("frases de Irons: %d latinas, %d de España" % (len(lat), len(esp)))
L = mfcc(np.concatenate(lat)); E = mfcc(np.concatenate(esp))
ml, me = L.mean(0) * 0 + np.concatenate([L.std(0)]), np.concatenate([E.std(0)])
# modelo simple: media y covarianza de los MFCC con CMN por frase
def model(chunks):
    cs = [mfcc(x) for x in chunks]
    cs = [c for c in cs if c is not None]
    allc = np.concatenate(cs)
    return allc.mean(0), np.cov(allc.T) + np.eye(allc.shape[1]) * 1e-3
mL, cL = model(lat); mE, cE = model(esp)
def loglik(c, m, cov):
    inv = np.linalg.inv(cov); _, ld = np.linalg.slogdet(cov)
    d = c - m
    return -0.5 * (np.einsum("ij,jk,ik->i", d, inv, d) + ld).mean()
for f in sys.argv[1:]:
    path, tracks = f.split("@")
    for t in [int(x) for x in tracks.split(",")]:
        x = decode(path, t)
        segs = [x[i:i + 16000 * 4] for i in range(0, len(x), 16000 * 4)]
        c = np.concatenate([mfcc(s) for s in segs if mfcc(s) is not None])
        dl, de = loglik(c, mL, cL), loglik(c, mE, cE)
        print("%s pista %d: parecido latino %.1f · España %.1f  ->  %s" % (os.path.basename(path), t, dl, de,
              "LATINO" if dl > de else "ESPAÑA"), flush=True)


