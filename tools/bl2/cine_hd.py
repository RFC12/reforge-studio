"""ReForge Cine HD: reescala con IA las cinemáticas Bink 1 de un juego y las vuelve a codificar en Bink 1
conservando todas las pistas de audio (idiomas) con sus mismos identificadores.

Uso: python cine_hd.py <carpeta Movies> <carpeta de trabajo> Nombre1 Nombre2 ...   (sin .bik)
     --instalar   copia los resultados al juego (los originales se guardan en Movies\\_original)
     --conservar  no borra los fotogramas intermedios
"""
import os, re, shutil, subprocess, sys, time

FF = r"C:\ReForgeBuild\awlat\build\awlat\ffmpeg.exe"
ESR = r"C:\Users\roger\AppData\Local\Temp\awlat\esrgan\realesrgan-ncnn-vulkan.exe"
RAD = r"C:\Users\roger\AppData\Local\Temp\awlat\rad\RADVideo\radvideo64.exe"


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", **kw)
    if r.returncode != 0:
        print("FALLÓ:", " ".join(map(str, cmd)))
        print(r.stdout[-3000:], r.stderr[-3000:])
        raise SystemExit(1)
    return r


def rad_busy():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq radvideo64.exe"], capture_output=True).stdout
    return b"radvideo64" in out.lower()


def rad(args, out, timeout=7200):
    """RAD Video Tools trabaja en segundo plano: se espera a que el archivo quede terminado."""
    for f in (out, out + ".tmp"):
        if os.path.exists(f):
            os.remove(f)
    subprocess.run([RAD] + args + ["/O"], capture_output=True)
    t0, last = time.time(), -1
    while time.time() - t0 < timeout:
        time.sleep(3)
        busy = rad_busy()
        if os.path.exists(out) and not os.path.exists(out + ".tmp"):
            sz = os.path.getsize(out)
            if sz == last:
                # la ventana de RAD a veces se queda abierta en "Done!": se cierra
                subprocess.run(["taskkill", "/F", "/IM", "radvideo64.exe"], capture_output=True)
                time.sleep(1)
                return
            last = sz
        elif not busy and time.time() - t0 > 20:
            raise SystemExit("RAD falló: " + " ".join(args))
    raise SystemExit("RAD tardó demasiado")


def probe(path):
    r = subprocess.run([FF, "-hide_banner", "-i", path], capture_output=True, text=True, errors="replace")
    t = r.stderr
    v = re.search(r"Video: binkvideo.*?, (\d+)x(\d+), ([\d.]+) fps", t)
    if not v:
        return None
    audio = [(int(m.group(1)), int(m.group(2), 16), int(m.group(3))) for m in
             re.finditer(r"Stream #0:(\d+)\[0x([0-9a-f]+)\]: Audio: \w+, (\d+) Hz", t)]
    dur = re.search(r"Duration: (\d+):(\d+):([\d.]+)", t)
    secs = int(dur.group(1)) * 3600 + int(dur.group(2)) * 60 + float(dur.group(3))
    return int(v.group(1)), int(v.group(2)), float(v.group(3)), audio, secs


ULTRA = None  # (ancho, alto) de una pantalla panorámica: los vídeos 16:9 se recortan arriba/abajo para llenarla


def crop_for(w, h):
    """Recorte centrado de la fuente con la proporción de la pantalla panorámica (o None)."""
    if not ULTRA or h > 720 or h < 600:
        return None
    ch = int(round(w * ULTRA[1] / ULTRA[0])) // 2 * 2
    if ch >= h:
        return None
    return w, ch, 0, (h - ch) // 2


def target(w, h):
    """Escala de la IA y tamaño final (1080p para los 720p; x4 para los vídeos pequeños de pantallas)."""
    c = crop_for(w, h)
    if c:
        return 2, ULTRA[0], ULTRA[1]
    if h <= 200:
        return 4, w * 4, h * 4
    if h <= 360:
        return 4, w * 3, h * 3
    if h <= 720:
        return 2, w * 1920 // 1280 // 2 * 2, h * 1080 // 720 // 2 * 2
    return 0, w, h


def process(src, work, name):
    info = probe(src)
    if not info:
        print(name, ": no es Bink 1, se omite", flush=True)
        return None
    w, h, fps, audio, secs = info
    scale, tw, th = target(w, h)
    if not scale:
        print(name, ": ya es de alta resolución, se omite", flush=True)
        return None
    d = os.path.join(work, name)
    fin, fout, fhd = (os.path.join(d, x) for x in ("in", "out", "hd"))
    for p in (fin, fout, fhd):
        os.makedirs(p, exist_ok=True)
    t0 = time.time()
    print(f"{name}: {w}x{h} {fps} fps, {secs:.0f} s, {len(audio)} pistas de audio -> {tw}x{th}", flush=True)
    wavs = []
    for idx, tid, rate in audio:
        wav = os.path.join(d, f"pista{tid}.wav")
        if not os.path.exists(wav):
            run([FF, "-y", "-v", "error", "-i", src, "-map", f"0:{idx}", "-c:a", "pcm_s16le", wav])
        wavs.append((tid, wav))
    n_src = int(round(secs * fps))
    n_out, n_hd = len(os.listdir(fout)), len(os.listdir(fhd))
    if n_hd == 0 or n_hd < n_out or (n_out == 0 and n_hd < n_src * 0.98):
        if n_out < max(1, n_hd) or (n_out < n_src * 0.98):
            for x in os.listdir(fout):
                os.remove(os.path.join(fout, x))
            c = crop_for(w, h)
            vf = ["-vf", "crop=%d:%d:%d:%d" % c] if c else []
            run([FF, "-y", "-v", "error", "-i", src, "-map", "0:v:0", "-vsync", "0"] + vf + [os.path.join(fin, "%06d.png")])
            n = len(os.listdir(fin))
            print(f"  {n} fotogramas extraídos ({time.time() - t0:.0f} s)", flush=True)
            t1 = time.time()
            run([ESR, "-i", fin, "-o", fout, "-n", "realesr-animevideov3", "-s", str(scale), "-f", "png",
                 "-j", "2:4:4"], cwd=os.path.dirname(ESR))
            print(f"  IA: {n} fotogramas en {time.time() - t1:.0f} s ({n / max(1, time.time() - t1):.1f} fps)",
                  flush=True)
            shutil.rmtree(fin, ignore_errors=True)
        for x in os.listdir(fhd):  # se rehace entero: el último fotograma pudo quedar a medias
            os.remove(os.path.join(fhd, x))
        run([FF, "-y", "-v", "error", "-i", os.path.join(fout, "%06d.png"), "-vf",
             f"scale={tw}:{th}:flags=lanczos", os.path.join(fhd, "%06d.png")])
        shutil.rmtree(fout, ignore_errors=True)
    frames = sorted(x for x in os.listdir(fhd) if x.endswith(".png"))
    lst = os.path.join(d, "frames.lst")
    with open(lst, "w") as f:
        for x in frames:
            f.write(os.path.join(fhd, x) + "\n")
    rate = int(os.path.getsize(src) / max(1.0, secs) * 1.8 * max(1.0, tw * th / (1920 * 1080)))
    rate = max(300000, min(rate, 4000000))
    vid = os.path.join(d, "video.bik")
    t2 = time.time()
    rad(["binkc", lst, vid, f"/F{fps}", f"/D{rate}", "/V100", "/L-1", "/{0"], vid)
    print(f"  Bink: {os.path.getsize(vid) / 1e6:.0f} MB en {time.time() - t2:.0f} s", flush=True)
    cur = vid
    for i, (tid, wav) in enumerate(wavs):
        nxt = os.path.join(d, f"mix{i}.bik")
        rad(["binkmix", cur, wav, nxt, f"/T{tid}", "/L4"], nxt)
        if cur != vid:
            os.remove(cur)
        cur = nxt
    final = os.path.join(work, name + ".bik")
    shutil.move(cur, final)
    print(f"  LISTO {name}.bik ({os.path.getsize(final) / 1e6:.0f} MB, total {time.time() - t0:.0f} s)", flush=True)
    return final


def keep_awake():
    """Evita que Windows suspenda el equipo mientras se procesan los vídeos."""
    try:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)  # CONTINUOUS | SYSTEM_REQUIRED
    except Exception:
        pass


def main():
    keep_awake()
    global ULTRA
    for a in sys.argv:
        if a.startswith("--panoramica="):
            ULTRA = tuple(int(x) for x in a.split("=", 1)[1].lower().split("x"))
    movies, work = sys.argv[1], sys.argv[2]
    names = [a for a in sys.argv[3:] if not a.startswith("--")]
    install, keep = "--instalar" in sys.argv, "--conservar" in sys.argv
    os.makedirs(work, exist_ok=True)
    for name in names:
        src = os.path.join(movies, "_original", name + ".bik")
        if not os.path.exists(src):
            src = os.path.join(movies, name + ".bik")
        final = os.path.join(work, name + ".bik")
        if not os.path.exists(final):
            final = process(src, work, name)
        if final and not keep:
            shutil.rmtree(os.path.join(work, name), ignore_errors=True)
        if final and install:
            bk = os.path.join(movies, "_original")
            os.makedirs(bk, exist_ok=True)
            if not os.path.exists(os.path.join(bk, name + ".bik")):
                shutil.move(os.path.join(movies, name + ".bik"), os.path.join(bk, name + ".bik"))
            shutil.copy(final, os.path.join(movies, name + ".bik"))
            print("  instalado en el juego:", name, flush=True)


if __name__ == "__main__":
    main()
