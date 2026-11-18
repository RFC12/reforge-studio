"""Transcribe las dos pistas de voz en español (c/d -> 13 y e/f -> 15) de cada vídeo con varios idiomas, a partir
de los originales del respaldo, para decidir cuál es la latina en cada uno."""
import os, subprocess, sys
import numpy as np
from faster_whisper import WhisperModel
FF = r"C:\ReForgeBuild\awlat\build\awlat\ffmpeg.exe"
model = WhisperModel("medium", device="cpu", compute_type="int8")
b = r"H:\Call of Duty Advanced Warfare\spanish\_reforge_respaldo\_raiz"
out = open(sys.argv[1], "w", encoding="utf-8")
names = sorted(n for n in os.listdir(b) if n.endswith(".bik") and not n.startswith(("zombies", "audio_log")))
for n in names:
    for t in (13, 15):
        r = subprocess.run([FF, "-v", "error", "-i", os.path.join(b, n), "-map", "0:a:%d" % t, "-t", "75", "-ac", "1",
                            "-ar", "16000", "-f", "f32le", "-"], capture_output=True)
        x = np.frombuffer(r.stdout, np.float32)
        if len(x) == 0:
            continue
        segs, info = model.transcribe(x, language="es", beam_size=3, vad_filter=True)
        text = " ".join(s.text.strip() for s in segs)
        out.write("%s | pista %d | %s\n" % (n, t, text))
        out.flush()
out.write("FIN\n")
