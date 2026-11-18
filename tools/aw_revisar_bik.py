import os, sys, struct
sys.path.insert(0, os.path.dirname(__file__))
import aw_doblaje_latino as A
pc = r"H:\Call of Duty Advanced Warfare"
rdir = os.path.join(pc, "spanish", A.BACKUP_DIR, A.ROOT_BACKUP)
patched = set(os.listdir(rdir)) if os.path.isdir(rdir) else set()
for n in sorted(os.listdir(pc)):
    if not n.lower().endswith(".bik"):
        continue
    head = open(os.path.join(pc, n), "rb").read(1 << 16)
    try:
        h = A.bik_parse(head)
    except Exception:
        h = None
    if not h:
        print("%-40s ? (no se pudo leer)" % n)
        continue
    ids = h["ids"]
    if len(ids) <= 2 and n not in patched:
        continue
    print("%-40s pistas=%-50s %s" % (n, ",".join("%x" % i for i in ids), "PARCHEADO" if n in patched else ""))
