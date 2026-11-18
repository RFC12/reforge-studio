"""Voces guardadas completas dentro de los fastfiles (sin pak): FLAC embebido que no es arranque de un tipo 3."""
import os, re, sys, collections
sys.path.insert(0, os.path.dirname(__file__))
import aw_doblaje_latino as A
lang = r"H:\Call of Duty Advanced Warfare\spanish"
cur = {}
for n in os.listdir(lang):
    m = re.match(r"spa_soundfile(\d+)\.pak$", n, re.I)
    if m:
        cur[int(m.group(1))] = os.path.getsize(os.path.join(lang, n))
VO = re.compile(rb"voiceovers/[a-z0-9_/]+\x00")
tot = 0
for n in sorted(os.listdir(lang)):
    if not (n.startswith("spa_") and n.endswith(".ff")) or "_mp" in n:
        continue
    raw = open(os.path.join(lang, n), "rb").read()
    if raw[:8] != b"S1ffu100":
        continue
    z = A.zone_pc(raw)
    primes = set()
    for r in A.refs_pc(z, cur):
        if r["type"] == 3 and r["prime"]:
            primes.add(r["prime"][1])
    flacs = [m.start() for m in re.finditer(b"fLaC", z)]
    loaded = [q for q in flacs if q not in primes]
    names = []
    for q in loaded:
        mm = list(VO.finditer(z, max(0, q - 400), q))
        names.append(mm[-1].group()[:-1].decode() if mm else "?")
    vo = [x for x in names if x.startswith("voiceovers/")]
    tot += len(vo)
    if loaded:
        print("%-28s fLaC=%d primes=%d cargadas=%d (voces: %d)" % (n, len(flacs), len(primes), len(loaded), len(vo)))
        if vo:
            print("     ej.:", ", ".join(vo[:6]))
print("voces cargadas en total:", tot)
