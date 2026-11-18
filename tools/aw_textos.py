"""Compara los textos (menús y subtítulos) del PC (español de España) con los de 360 (latino) por clave."""
import os, re, sys
sys.path.insert(0, os.path.dirname(__file__))
import aw_doblaje_latino as A
pc = r"H:\Call of Duty Advanced Warfare\spanish"
x = r"H:\cod_aw\assets\spanishna"
RPC = re.compile(rb"\xff\xff\xff\xff\xff\xfd\xfd\xfd\xff\xff\xff\xff\xff\xfd\xfd\xfd([^\x00]*)\x00([A-Z][A-Z0-9_]+)\x00", re.S)
R36 = re.compile(rb"\xff\xff\xff\xff\xff\xff\xff\xff([^\x00]*)\x00([A-Z][A-Z0-9_]+)\x00", re.S)


def strings(zone, rx):
    return {m.group(2).decode(): m.group(1) for m in rx.finditer(zone)}


lat, esp = {}, {}
for n in sorted(os.listdir(x)):
    if n.endswith(".ff") and "mp" not in n:
        try:
            lat.update(strings(A.zone_360(os.path.join(x, n)), R36))
        except Exception as e:
            print("360", n, e)
for n in sorted(os.listdir(pc)):
    if n.endswith(".ff") and "_mp" not in n:
        raw = open(os.path.join(pc, n), "rb").read()
        if raw[:8] != b"S1ffu100":
            continue
        esp.update(strings(A.zone_pc(raw), RPC))
common = set(lat) & set(esp)
diff = [k for k in common if lat[k] != esp[k]]
fits = [k for k in diff if len(lat[k]) <= len(esp[k])]
print("textos: 360=%d PC=%d en común=%d distintos=%d (caben en el mismo espacio: %d)" %
      (len(lat), len(esp), len(common), len(diff), len(fits)))
for k in sorted(diff)[:0]:
    pass
import random
random.seed(1)
for k in random.sample(sorted(diff), min(15, len(diff))):
    print("%s\n   PC : %s\n   360: %s" % (k, esp[k].decode("utf-8", "replace")[:110], lat[k].decode("utf-8", "replace")[:110]))
