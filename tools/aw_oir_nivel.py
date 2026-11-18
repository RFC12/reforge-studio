"""Transcribe las voces que un nivel reproduce ahora (las añadidas al final de los paks) para ver si son latinas."""
import os, re, subprocess, sys
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
import aw_doblaje_latino as A
from faster_whisper import WhisperModel
FF = r"C:\ReForgeBuild\awlat\build\awlat\ffmpeg.exe"
lang = r"H:\Call of Duty Advanced Warfare\spanish"
bdir = os.path.join(lang, A.BACKUP_DIR)
cur, orig = {}, {}
for n in os.listdir(lang):
    m = re.match(r"spa_soundfile(\d+)\.pak$", n, re.I)
    if m:
        i = int(m.group(1)); cur[i] = os.path.getsize(os.path.join(lang, n))
        b = os.path.join(bdir, n); orig[i] = os.path.getsize(b) if os.path.exists(b) else cur[i]
name, count = sys.argv[1], int(sys.argv[2])
z = A.zone_pc(open(os.path.join(lang, name), "rb").read())
zb = A.zone_pc(open(os.path.join(bdir, name), "rb").read())
old = {}
for r in A.refs_pc(zb, orig):
    old.setdefault(r["alias"], r)
refs = [r for r in A.refs_pc(z, cur) if r["len"] > 40000]
refs.sort(key=lambda r: -r["len"])
model = WhisperModel("medium", device="cpu", compute_type="int8")
ESP = re.compile(r"\b(vosotros|vosotras|os|vuestr\w*|\w+[aáeé]is|\w+[aáeéií]steis|vale|tío|joder|cabrón|coño)\b", re.I)


def text_of(idx, off, ln):
    with open(os.path.join(lang, "spa_soundfile%d.pak" % idx), "rb") as f:
        f.seek(off); data = f.read(ln)
    r = subprocess.run([FF, "-v", "error", "-i", "-", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], input=data,
                       capture_output=True)
    x = np.frombuffer(r.stdout, np.float32)
    segs, _ = model.transcribe(x, language="es", beam_size=3)
    return " ".join(s.text.strip() for s in segs)


seen = set()
n = 0
for r in refs:
    if r["alias"] in seen:
        continue
    seen.add(r["alias"])
    now = text_of(r["idx"], r["off"], r["len"])
    o = old.get(r["alias"])
    before = text_of(o["idx"], o["off"], o["len"]) if o else "?"
    tag = "LATINO?" if r["off"] >= orig[r["idx"]] else "ESPAÑA (puntero original)"
    print("%s [%s]\n   ahora : %s %s\n   antes : %s %s" % (r["alias"], tag, now, ESP.findall(now), before, ESP.findall(before)))
    sys.stdout.flush()
    n += 1
    if n >= count:
        break
