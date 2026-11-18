"""Busca en un fastfile cualquier referencia (pak, desplazamiento, tamaño) a la zona ORIGINAL (España) de los paks
spa_, sin exigir el prefijo exacto que reconoce el parche."""
import os, re, struct, sys, collections
sys.path.insert(0, os.path.dirname(__file__))
import aw_doblaje_latino as A
lang = r"H:\Call of Duty Advanced Warfare\spanish"
bdir = os.path.join(lang, A.BACKUP_DIR)
cur, orig = {}, {}
for n in os.listdir(lang):
    m = re.match(r"spa_soundfile(\d+)\.pak$", n, re.I)
    if m:
        i = int(m.group(1)); cur[i] = os.path.getsize(os.path.join(lang, n))
        b = os.path.join(bdir, n); orig[i] = os.path.getsize(b) if os.path.exists(b) else cur[i]
name = sys.argv[1]
z = A.zone_pc(open(os.path.join(lang, name), "rb").read())
known = {r["pos"] for r in A.refs_pc(z, cur)}
hits = collections.Counter()
samples = []
for idx in orig:
    pat = struct.pack("<H", idx)
    for m in re.finditer(re.escape(pat), z):
        p = m.start()
        if p + 26 > len(z):
            continue
        off, ln = struct.unpack_from("<QQ", z, p + 6)
        if ln and off % 2048 == 0 and off + ln <= orig[idx] and ln < 50 << 20:
            pos = p - 2
            if pos in known:
                continue
            pre = z[p - 18:p + 2]
            hits[pre[-4:].hex()] += 1
            if len(samples) < 12:
                samples.append((p, idx, off, ln, z[p - 24:p + 30].hex(), A._alias_near(z, p)))
print(name, "referencias a audio de España sin reconocer:", sum(hits.values()))
print("prefijos:", hits.most_common(8))
for s in samples:
    print(s)
