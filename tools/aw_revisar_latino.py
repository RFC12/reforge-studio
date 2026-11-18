"""Qué voces de la campaña siguen apuntando al audio original (España) tras el parche latino."""
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
tot = collections.Counter()
for n in sorted(os.listdir(lang)):
    if not (n.startswith("spa_") and n.endswith(".ff")) or "_mp" in n:
        continue
    raw = open(os.path.join(lang, n), "rb").read()
    if raw[:8] != b"S1ffu100":
        continue
    z = A.zone_pc(raw)
    refs = A.refs_pc(z, cur)
    left = collections.Counter()
    names = []
    for r in refs:
        new = r["off"] >= orig.get(r["idx"], 1 << 62)
        if new:
            left["latino_t%d" % r["type"]] += 1
        else:
            left["espana_t%d" % r["type"]] += 1
            nm = A._prime_name(z, r) if r["type"] == 3 else (r.get("alias") or b"").decode("ascii", "replace") if isinstance(r.get("alias"), bytes) else str(r.get("alias"))
            names.append(nm)
    tot.update(left)
    if left:
        print("%-28s %s" % (n, dict(left)))
        esp = [x for x in names if x]
        if esp:
            print("      ej.:", ", ".join(sorted(set(esp))[:12]))
print("TOTAL", dict(tot))
