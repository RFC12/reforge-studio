"""ReForge · Doblaje Latino para Call of Duty: Advanced Warfare (PC).

Instalador externo del parche: toma las voces en español latino de TU copia de Xbox 360 (carpeta
spanishna, ISO o Games on Demand) y las aplica a TU juego de PC. No incluye audio del juego: lo convierte
en tu equipo a partir de tus archivos.
"""
import os
import queue
import string
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import aw_doblaje_latino as core  # noqa: E402

APP = "Doblaje Latino · Call of Duty: Advanced Warfare"
EXE_PC = "s1_sp64_ship.exe"
BG, PANEL, FG, MUTED, ACCENT, OK, BAD = "#14161b", "#1d2027", "#e8eaf0", "#9aa1ad", "#3fa7ff", "#3fcf7f", "#ff6b6b"


def resource(name):
    return os.path.join(getattr(sys, "_MEIPASS", "") or os.path.dirname(HERE), "assets", name)


# --------------------------------------------------------------------------------------- detección
def _drives():
    if os.name != "nt":
        return ["/"]
    return [d + ":\\" for d in string.ascii_uppercase if os.path.exists(d + ":\\")]


def _subdirs(p):
    try:
        return [e.path for e in os.scandir(p) if e.is_dir(follow_symlinks=False)]
    except OSError:
        return []


def is_pc_game(p):
    return bool(p) and os.path.isfile(os.path.join(p, EXE_PC)) and os.path.isdir(os.path.join(p, core.LANG_DIR))


def find_pc_game():
    cands = []
    for d in _drives():
        cands += [os.path.join(d, "Program Files (x86)", "Steam", "steamapps", "common", "Call of Duty Advanced Warfare"),
                  os.path.join(d, "SteamLibrary", "steamapps", "common", "Call of Duty Advanced Warfare"),
                  os.path.join(d, "Steam", "steamapps", "common", "Call of Duty Advanced Warfare")]
        for s1 in _subdirs(d):
            cands.append(s1)
            low = os.path.basename(s1).lower()
            if any(k in low for k in ("game", "juego", "steam", "warfare", "call of duty", "cod")):
                cands += _subdirs(s1)
    for c in cands:
        if is_pc_game(c):
            return c
    return ""


def _is_sna(p):
    try:
        return any(n.lower().startswith("sna_soundfile") for n in os.listdir(p))
    except OSError:
        return False


def find_360_source():
    roots = [os.path.join(os.path.expanduser("~"), "ReForgeProjects")] + _drives()
    for r in roots:
        for s1 in _subdirs(r):
            for c in (os.path.join(s1, "assets", "spanishna"), os.path.join(s1, "spanishna")):
                if _is_sna(c):
                    return c
            if os.path.basename(s1).upper() == "41560914":
                return s1
            for s2 in _subdirs(s1):
                if os.path.basename(s2).upper() == "41560914" or _is_sna(os.path.join(s2, "spanishna")):
                    return s2 if os.path.basename(s2).upper() == "41560914" else os.path.join(s2, "spanishna")
    return ""


def prepare_source(path, work, log, progress):
    """Devuelve la carpeta con los archivos sna_* (la extrae de una ISO o de un GOD si hace falta)."""
    if os.path.isdir(path):
        for c in (path, os.path.join(path, "spanishna"), os.path.join(path, "assets", "spanishna")):
            if _is_sna(c):
                return c
    img = None
    if os.path.isfile(path) and path.lower().endswith(".iso"):
        from reforge.xiso import XisoImage
        img = XisoImage(path)
        log("Leyendo la ISO de Xbox 360…")
    else:
        from reforge.xcontent import XContentPackage
        img = XContentPackage(path)
        log("Leyendo el paquete Games on Demand de Xbox 360…")
    try:
        files = [e for e in img.files() if e.path.lower().startswith("spanishna/")]
        if not files:
            raise RuntimeError("Esa copia de Xbox 360 no trae la carpeta «spanishna» (doblaje latino). "
                               "Hace falta la versión de Latinoamérica / Norteamérica del juego.")
        dest = os.path.join(work, "spanishna")
        os.makedirs(dest, exist_ok=True)
        total = sum(e.size for e in files)
        done = 0
        for e in files:
            out = os.path.join(dest, os.path.basename(e.path))
            if not (os.path.exists(out) and os.path.getsize(out) == e.size):
                with open(out + ".tmp", "wb") as f:
                    f.write(img.read_file(e))
                os.replace(out + ".tmp", out)
            done += e.size
            progress(done, total)
        log("Archivos latinos extraídos (%d)." % len(files))
        return dest
    finally:
        img.close()


# ---------------------------------------------------------------------------------------- ventana
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP)
        self.configure(bg=BG)
        self.geometry("760x600")
        self.minsize(680, 520)
        try:
            self.iconbitmap(resource("icon.ico"))
        except Exception:
            pass
        self.q = queue.Queue()
        self.busy = False
        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure(".", background=BG, foreground=FG, fieldbackground=PANEL, bordercolor="#2a2e37")
        st.configure("TLabel", background=BG, foreground=FG, font=("Segoe UI", 10))
        st.configure("Muted.TLabel", foreground=MUTED, font=("Segoe UI", 9))
        st.configure("Title.TLabel", font=("Segoe UI Semibold", 17))
        st.configure("TEntry", fieldbackground=PANEL, foreground=FG, insertcolor=FG)
        st.configure("TButton", background=PANEL, foreground=FG, padding=(12, 6), font=("Segoe UI", 10))
        st.map("TButton", background=[("active", "#2a2f39"), ("disabled", "#181a1f")],
               foreground=[("disabled", "#5b616c")])
        st.configure("Accent.TButton", background=ACCENT, foreground="#071321", font=("Segoe UI Semibold", 11))
        st.map("Accent.TButton", background=[("active", "#62b8ff"), ("disabled", "#24425e")])
        st.configure("TProgressbar", troughcolor=PANEL, background=ACCENT, bordercolor=PANEL, thickness=10)

        pad = dict(padx=18)
        ttk.Label(self, text="Doblaje latino para Advanced Warfare", style="Title.TLabel").pack(anchor="w", pady=(16, 0), **pad)
        ttk.Label(self, text="Pone las voces latinas de tu copia de Xbox 360 en tu juego de PC: campaña, escenas "
                             "y cinemáticas. Todo se puede deshacer.", style="Muted.TLabel",
                  wraplength=700).pack(anchor="w", pady=(2, 12), **pad)

        self.pc = tk.StringVar()
        self.src = tk.StringVar()
        self._row("Juego de PC (carpeta con s1_sp64_ship.exe)", self.pc,
                  [("Carpeta…", self.pick_pc)])
        self._row("Copia de Xbox 360: carpeta «spanishna», ISO o carpeta GOD (41560914)", self.src,
                  [("Carpeta…", self.pick_src_dir), ("ISO / archivo…", self.pick_src_file)])

        self.state = ttk.Label(self, text="", style="Muted.TLabel")
        self.state.pack(anchor="w", pady=(6, 6), **pad)
        self.bar = ttk.Progressbar(self, mode="determinate", maximum=1000)
        self.bar.pack(fill="x", **pad)
        box = tk.Frame(self, bg=PANEL)
        box.pack(fill="both", expand=True, pady=10, **pad)
        self.text = tk.Text(box, bg=PANEL, fg="#cfd3dc", relief="flat", font=("Consolas", 9), wrap="word",
                            insertbackground=FG, highlightthickness=0, padx=10, pady=8)
        sb = ttk.Scrollbar(box, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set, state="disabled")
        sb.pack(side="right", fill="y")
        self.text.pack(fill="both", expand=True)

        btns = tk.Frame(self, bg=BG)
        btns.pack(fill="x", pady=(0, 16), **pad)
        self.b_install = ttk.Button(btns, text="Instalar doblaje latino", style="Accent.TButton", command=self.install)
        self.b_install.pack(side="left")
        self.b_restore = ttk.Button(btns, text="Volver al doblaje de España", command=self.restore)
        self.b_restore.pack(side="left", padx=8)
        ttk.Button(btns, text="Salir", command=self.destroy).pack(side="right")

        self.pc.trace_add("write", lambda *_: self.refresh())
        self.after(80, self.poll)
        self.log("Buscando el juego y tu copia de Xbox 360…")
        threading.Thread(target=self._autodetect, daemon=True).start()

    def _row(self, label, var, buttons):
        ttk.Label(self, text=label).pack(anchor="w", padx=18, pady=(4, 2))
        f = tk.Frame(self, bg=BG)
        f.pack(fill="x", padx=18)
        ttk.Entry(f, textvariable=var).pack(side="left", fill="x", expand=True, ipady=3)
        for t, cmd in buttons:
            ttk.Button(f, text=t, command=cmd).pack(side="left", padx=(6, 0))

    # -- utilidades de la interfaz
    def log(self, msg):
        self.q.put(("log", msg))

    def progress(self, done, total):
        self.q.put(("bar", done / total if total else 0))

    def poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.text.configure(state="normal")
                    self.text.insert("end", val + "\n")
                    self.text.see("end")
                    self.text.configure(state="disabled")
                elif kind == "bar":
                    self.bar["value"] = int(val * 1000)
                elif kind == "pc" and not self.pc.get():
                    self.pc.set(val)
                elif kind == "src" and not self.src.get():
                    self.src.set(val)
                elif kind == "done":
                    self.busy = False
                    self.refresh()
                    ok, msg = val
                    (messagebox.showinfo if ok else messagebox.showerror)(APP, msg)
        except queue.Empty:
            pass
        self.after(80, self.poll)

    def refresh(self):
        pc = self.pc.get().strip()
        installed = is_pc_game(pc) and os.path.exists(os.path.join(pc, core.LANG_DIR, core.STATE_FILE))
        if not pc:
            txt = "Elige la carpeta del juego de PC."
        elif not is_pc_game(pc):
            txt = "Esa carpeta no parece el juego de PC (falta %s o la carpeta spanish)." % EXE_PC
        elif installed:
            txt = "✔ El doblaje latino está instalado en este juego."
        else:
            txt = "El juego tiene el doblaje original de España."
        self.state.configure(text=txt, foreground=OK if installed else MUTED)
        for b in (self.b_install, self.b_restore):
            b.configure(state="disabled" if self.busy else "normal")

    def _autodetect(self):
        pc = find_pc_game()
        self.q.put(("pc", pc))
        self.log("Juego de PC: " + (pc or "no encontrado (elígelo con «Carpeta…»)"))
        src = find_360_source()
        self.q.put(("src", src))
        self.log("Copia de Xbox 360: " + (src or "no encontrada (elige la carpeta spanishna, la ISO o el GOD)"))

    def pick_pc(self):
        p = filedialog.askdirectory(title="Carpeta del juego de PC")
        if p:
            self.pc.set(os.path.normpath(p))

    def pick_src_dir(self):
        p = filedialog.askdirectory(title="Carpeta spanishna, carpeta del juego de 360 o carpeta GOD")
        if p:
            self.src.set(os.path.normpath(p))

    def pick_src_file(self):
        p = filedialog.askopenfilename(title="ISO o archivo GOD de Xbox 360",
                                       filetypes=[("Imagen o paquete de Xbox 360", "*.iso *"), ("Todos", "*.*")])
        if p:
            self.src.set(os.path.normpath(p))

    # -- acciones
    def _run(self, fn):
        if self.busy:
            return
        self.busy = True
        self.refresh()
        self.bar["value"] = 0
        core.LOG_HOOK = self.log

        def work():
            try:
                msg = fn()
                self.q.put(("done", (True, msg)))
            except SystemExit as e:
                self.log("✖ " + str(e))
                self.q.put(("done", (False, str(e))))
            except Exception as e:  # noqa: BLE001
                self.log("✖ Error: %s" % e)
                self.q.put(("done", (False, "Error: %s" % e)))

        threading.Thread(target=work, daemon=True).start()

    def install(self):
        pc = self.pc.get().strip()
        src = self.src.get().strip()
        if not is_pc_game(pc):
            messagebox.showwarning(APP, "Elige la carpeta del juego de PC (la que tiene %s)." % EXE_PC)
            return
        if not src or not os.path.exists(src):
            messagebox.showwarning(APP, "Elige tu copia de Xbox 360 (carpeta spanishna, ISO o carpeta GOD).")
            return

        def job():
            t0 = time.time()
            work = os.path.join(pc, "ReForge_Doblaje_Latino", "_fuente_360")
            sna = prepare_source(src, work, self.log, self.progress)
            self.log("Fuente latina: " + sna)
            core.install(sna, pc, progress=self.progress)
            self.progress(1, 1)
            return ("¡Listo! Doblaje latino instalado en %.0f s.\n\nEn el juego usa el idioma «Español». "
                    "Puedes deshacerlo cuando quieras con «Volver al doblaje de España»." % (time.time() - t0))

        self._run(job)

    def restore(self):
        pc = self.pc.get().strip()
        if not is_pc_game(pc):
            messagebox.showwarning(APP, "Elige la carpeta del juego de PC.")
            return
        if not messagebox.askyesno(APP, "¿Volver al doblaje original de España?"):
            return

        def job():
            core.restore(pc)
            self.progress(1, 1)
            return "Doblaje de España restaurado."

        self._run(job)


def main():
    if len(sys.argv) > 1:  # modo consola: mismos argumentos que aw_doblaje_latino.py
        if sys.stdout is None:  # exe sin consola: el registro va a un archivo junto al exe
            path = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "ReForge-Doblaje-Latino-AW.log")
            fh = open(path, "a", encoding="utf-8")
            core.LOG_HOOK = lambda m: (fh.write(m + "\n"), fh.flush())
        return core.main()
    App().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
