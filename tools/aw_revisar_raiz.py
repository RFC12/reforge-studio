"""Voces localizadas (paks spa_) referenciadas desde fastfiles que NO están en la carpeta spanish."""
import os, re, sys, collections
sys.path.insert(0, os.path.dirname(__file__))
import aw_doblaje_latino as A
pc = r"H:\Call of Duty Advanced Warfare"
lang = os.path.join(pc, "spanish")
bdir = os.path.join(lang, A.BACKUP_DIR)
cur, orig = {}, {}
for n in os.listdir(lang):
    m = re.match(r"spa_soundfile(\d+)\.pak$", n, re.I)
    if m:
        i = int(m.group(1))
        cur[i] = os.path.getsize(os.path.join(lang, n))
        b = os.path.join(bdir, n)
        orig[i] = os.path.getsize(b) if os.path.exists(b) else cur[i]
import struct
def zone_any(d):
    total = struct.unpack_from("<Q", d, 0x2C)[0]
    p = 0x38
    while p < min(len(d), 64 << 20):
        cs, us = struct.unpack_from("<II", d, p)
        if 0 < us <= 0x10000 and 0 < cs <= 0x10100:
            try:
                b = A._lz4_dec(d, p + 8, cs, us)
                if len(b) == us:
                    break
            except Exception:
                pass
        p += 4
    out = bytearray()
    while len(out) < total and p + 8 <= len(d):
        p = (p + 3) & ~3
        cs, us = struct.unpack_from("<II", d, p)
        if us == 0 or us > 0x10000:
            break
        b = A._lz4_dec(d, p + 8, cs, us)
        if len(b) != us:
            break
        out += b
        p += 8 + cs
    return bytes(out)
dirs = [pc] + [os.path.join(pc, d) for d in ("main", "zone") if os.path.isdir(os.path.join(pc, d))]
for d in dirs:
    for n in sorted(os.listdir(d)):
        if not n.endswith(".ff") or "mp" in n:
            continue
        raw = open(os.path.join(d, n), "rb").read()
        if raw[:4] != b"S1ff":
            continue
        try:
            z = zone_any(raw)
        except Exception as e:
            print(n, "no se pudo abrir", e)
            continue
        refs = A.refs_pc(z, cur)
        if refs:
            c = collections.Counter("latino" if r["off"] >= orig.get(r["idx"], 1 << 62) else "espana" for r in refs)
            al = sorted(set(r["alias"] for r in refs if r["off"] < orig.get(r["idx"], 1 << 62)))
            print("%s\\%-30s %s  ej.: %s" % (os.path.basename(d), n, dict(c), ", ".join(al[:8])))
print("fin")

