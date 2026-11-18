import subprocess, sys, re
import numpy as np
from faster_whisper import WhisperModel
FF = r"C:\ReForgeBuild\awlat\build\awlat\ffmpeg.exe"
model = WhisperModel("medium", device="cpu", compute_type="int8")
f = sys.argv[1]
ESP = re.compile(r"\b(vosotros|vosotras|os|vuestr\w*|\w+[aáeé]is|\w+[aáeéií]steis|vale|ordenador|coche|tío|joder)\b", re.I)
for t in [int(x) for x in sys.argv[2].split(",")]:
    r = subprocess.run([FF, "-v", "error", "-i", f, "-map", "0:a:%d" % t, "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                       capture_output=True)
    x = np.frombuffer(r.stdout, np.float32)
    segs, info = model.transcribe(x, language="es", beam_size=5)
    text = " ".join(s.text.strip() for s in segs)
    marks = sorted(set(m.group(0).lower() for m in ESP.finditer(text)))
    print("=== pista %d · marcas de España: %s" % (t, marks or "ninguna"))
    print(text.encode("ascii", "replace").decode())
    sys.stdout.flush()
