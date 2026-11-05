"""Operaciones del parche Utilidades Xbox. Todas reciben ctx(log, progress, cancelled)."""
import ftplib
import os
import shutil

from reforge.core import human_size
from reforge.xex import read_xex_info
from reforge.xiso import XisoImage

from .xbe import read_xbe_info, read_xbe_info_bytes
from .xiso_writer import create_xiso, plan

EXCLUDED = {"x_tool", "x_iso"}
FATX_MAX = 42
FATX_BAD = set('<>:"/\\|*?')


# ---------------------------------------------------------------- utilidades
def game_info_from_folder(folder):
    """Detecta el ejecutable de la raíz y devuelve dict(kind, title, title_id, exe)."""
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    lower = {n.lower(): n for n in names}
    if "default.xex" in lower:
        p = os.path.join(folder, lower["default.xex"])
        try:
            i = read_xex_info(p)
        except Exception:
            i = {}
        return {"kind": "Xbox 360", "title": "", "title_id": i.get("title_id", ""), "exe": p}
    if "default.xbe" in lower:
        p = os.path.join(folder, lower["default.xbe"])
        try:
            i = read_xbe_info(p)
        except Exception:
            i = {}
        return {"kind": "Xbox Clásica", "title": i.get("title", ""), "title_id": i.get("title_id", ""),
                "exe": p}
    for n in names:
        if n.lower().endswith((".xex", ".xbe")):
            return {"kind": "Xbox 360" if n.lower().endswith(".xex") else "Xbox Clásica",
                    "title": "", "title_id": "", "exe": os.path.join(folder, n)}
    return None


def iso_info(path):
    with XisoImage(path) as img:
        xbe = img.find("default.xbe")
        xex = img.find("default.xex")
        info = {"layout": img.layout, "files": len(img.files()), "size": img.total_size(),
                "kind": "Xbox 360" if xex else ("Xbox Clásica" if xbe else "Desconocido"),
                "title": "", "title_id": ""}
        if xbe:
            try:
                d = read_xbe_info_bytes(img.read_file(xbe, 256 * 1024))
                info.update(title=d["title"], title_id=d["title_id"], region=d.get("region", ""))
            except Exception:
                pass
        elif xex:
            try:
                from reforge.xex import read_xex_info_bytes
                info["title_id"] = read_xex_info_bytes(img.read_file(xex, 1024 * 1024)).get("title_id", "")
            except Exception:
                pass
        return info


def list_isos(folder):
    if not os.path.isdir(folder):
        return []
    return sorted(os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(".iso"))


def list_game_folders(base, recursive_exe=True):
    """Subcarpetas de `base` que contienen .xex/.xbe (excluye x_tool y x_ISO)."""
    out = []
    if not os.path.isdir(base):
        return out
    for n in sorted(os.listdir(base)):
        full = os.path.join(base, n)
        if not os.path.isdir(full) or n.lower() in EXCLUDED:
            continue
        info = game_info_from_folder(full)
        if info is None and recursive_exe:
            for dp, _dn, fn in os.walk(full):
                if any(f.lower().endswith((".xex", ".xbe")) for f in fn):
                    info = {"kind": "?", "title": "", "title_id": "", "exe": ""}
                    break
        if info is not None:
            out.append((full, info))
    return out


def fatx_problems(root):
    """Nombres no válidos para FATX (disco duro de la Xbox): >42 caracteres o símbolos prohibidos."""
    bad = []
    for dp, dn, fn in os.walk(root):
        for n in dn + fn:
            reason = ""
            if len(n) > FATX_MAX:
                reason = f"{len(n)} caracteres (máx. {FATX_MAX})"
            elif any(c in FATX_BAD for c in n) or any(ord(c) < 32 or ord(c) > 126 for c in n):
                reason = "caracteres no permitidos"
            if reason:
                bad.append((os.path.relpath(os.path.join(dp, n), root), reason))
    return bad


def _pct(ctx, done, total):
    ctx.progress(int(done * 1000 / max(total, 1)), 1000)


# ---------------------------------------------------------------- ISO → carpeta
def extract_isos(ctx, isos, dest_dir, overwrite=False, delete_after=False, trash=None):
    ok = fail = skip = 0
    grand = 0
    for iso in isos:
        try:
            grand += os.path.getsize(iso)
        except OSError:
            pass
    base_done = 0
    for n, iso in enumerate(isos, 1):
        if ctx.cancelled():
            break
        name = os.path.splitext(os.path.basename(iso))[0]
        out = os.path.join(dest_dir, name)
        ctx.log(f"[{n}/{len(isos)}] {os.path.basename(iso)}", "head")
        if os.path.exists(out) and not overwrite:
            ctx.log(f"  OMITIDO: ya existe la carpeta {out}", "warn")
            skip += 1
            base_done += os.path.getsize(iso)
            continue
        try:
            info = iso_info(iso)
            label = f"{info['kind']} · {info['layout']}"
            if info.get("title"):
                label += f" · «{info['title']}»"
            if info.get("title_id"):
                label += f" · ID {info['title_id']}"
            ctx.log(f"  {label} · {info['files']} archivos · {human_size(info['size'])}")
            size_iso = os.path.getsize(iso)
            with XisoImage(iso) as img:
                img.extract(out, cancelled=ctx.cancelled,
                            progress=lambda d, t, b=base_done, s=size_iso: _pct(
                                ctx, b + d * s / max(t, 1), grand))
            base_done += size_iso
            ctx.log(f"  ✔ Extraído en {out}", "ok")
            ok += 1
            if delete_after:
                if trash:
                    trash(iso)
                    ctx.log("  ISO enviada a la papelera", "warn")
                else:
                    os.remove(iso)
                    ctx.log("  ISO eliminada permanentemente", "warn")
        except Exception as e:
            fail += 1
            ctx.log(f"  ✖ {e}", "err")
            if os.path.isdir(out) and not os.listdir(out):
                os.rmdir(out)
    ctx.log(f"Resumen: {ok} extraída(s) · {skip} omitida(s) · {fail} con error", "ok" if not fail else "warn")
    if fail and not ok:
        raise RuntimeError("Ninguna ISO se pudo extraer")


# ---------------------------------------------------------------- carpeta → ISO
def create_isos(ctx, folders, dest_dir, overwrite=False):
    ok = fail = skip = 0
    plans = []
    total = 0
    for f in folders:
        try:
            _r, _d, _f, size = plan(f)
            plans.append((f, size))
            total += size
        except Exception as e:
            ctx.log(f"✖ {os.path.basename(f)}: {e}", "err")
            fail += 1
    done = 0
    for n, (folder, size) in enumerate(plans, 1):
        if ctx.cancelled():
            break
        name = os.path.basename(os.path.normpath(folder))
        out = os.path.join(dest_dir, name + ".iso")
        ctx.log(f"[{n}/{len(plans)}] {name}", "head")
        if os.path.exists(out) and not overwrite:
            ctx.log(f"  OMITIDO: ya existe {out}", "warn")
            skip += 1
            done += size
            continue
        bad = fatx_problems(folder)
        if bad:
            ctx.log(f"  ⚠ {len(bad)} nombre(s) no válidos para FATX (solo afecta al copiarlo al disco de la Xbox)",
                    "warn")
        try:
            files, data, iso_size = create_xiso(
                folder, out, cancelled=ctx.cancelled,
                progress=lambda d, t, b=done: _pct(ctx, b + d, total))
            done += size
            ctx.log(f"  ✔ {out} · {files} archivos · {human_size(iso_size)}", "ok")
            ok += 1
        except Exception as e:
            fail += 1
            ctx.log(f"  ✖ {e}", "err")
    ctx.log(f"Resumen: {ok} creada(s) · {skip} omitida(s) · {fail} con error", "ok" if not fail else "warn")
    if fail and not ok:
        raise RuntimeError("No se pudo crear ninguna ISO")


# ---------------------------------------------------------------- limpieza
def delete_folders(ctx, folders, trash=None):
    for i, f in enumerate(folders, 1):
        if ctx.cancelled():
            break
        has_exe = any(n.lower().endswith((".xex", ".xbe"))
                      for _dp, _dn, fn in os.walk(f) for n in fn)
        if not has_exe:
            ctx.log(f"OMITIDO (no contiene .xex/.xbe): {f}", "warn")
            continue
        if trash:
            trash(f)
            ctx.log(f"🗑 A la papelera: {f}", "ok")
        else:
            shutil.rmtree(f)
            ctx.log(f"✖ Eliminado permanentemente: {f}", "warn")
        ctx.progress(i, len(folders))


# ---------------------------------------------------------------- FTP a la Xbox
def ftp_upload(ctx, host, port, user, password, local_dir, remote_dir, passive=True, skip_bad=True):
    total = sum(os.path.getsize(os.path.join(dp, f)) for dp, _d, fn in os.walk(local_dir) for f in fn)
    bad = {p for p, _r in fatx_problems(local_dir)}
    if bad:
        ctx.log(f"⚠ {len(bad)} nombre(s) no válidos para FATX" +
                (" se omitirán" if skip_bad else ""), "warn")
    ctx.log(f"Conectando a {host}:{port}…")
    ftp = ftplib.FTP()
    ftp.connect(host, int(port), timeout=20)
    ftp.login(user, password)
    ftp.set_pasv(passive)
    ctx.log(f"Conectado · {ftp.getwelcome()[:80]}", "ok")

    made = set()

    def ensure(path):
        parts = [p for p in path.replace("\\", "/").split("/") if p]
        cur = "/" if path.startswith("/") else ""
        for p in parts:
            cur = (cur.rstrip("/") + "/" + p) if cur else p
            if cur in made:
                continue
            try:
                ftp.mkd(cur)
            except ftplib.error_perm:
                pass
            made.add(cur)
        return cur

    game = os.path.basename(os.path.normpath(local_dir))
    target_root = ensure(remote_dir.rstrip("/") + "/" + game)
    done = 0
    sent = 0
    try:
        for dp, dn, fn in os.walk(local_dir):
            rel = os.path.relpath(dp, local_dir)
            if rel != "." and any(rel == b or rel.startswith(b + os.sep) for b in bad) and skip_bad:
                dn[:] = []
                continue
            rdir = target_root if rel == "." else ensure(target_root + "/" + rel.replace(os.sep, "/"))
            for f in fn:
                if ctx.cancelled():
                    raise RuntimeError("Transferencia cancelada")
                relf = os.path.normpath(os.path.join(rel, f)) if rel != "." else f
                full = os.path.join(dp, f)
                if relf in bad and skip_bad:
                    ctx.log(f"  omitido (FATX): {relf}", "warn")
                    done += os.path.getsize(full)
                    continue
                ctx.log(f"  {relf}", "dim")

                def cb(block):
                    nonlocal done
                    done += len(block)
                    _pct(ctx, done, total)
                with open(full, "rb") as fh:
                    ftp.storbinary(f"STOR {rdir}/{f}", fh, blocksize=1 << 20, callback=cb)
                sent += 1
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()
    ctx.log(f"✔ {sent} archivo(s) · {human_size(total)} enviados a {target_root}", "ok")
