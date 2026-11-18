import os, subprocess, sys, tempfile
from faster_whisper import WhisperModel
FF = r"C:\ReForgeBuild\awlat\build\awlat\ffmpeg.exe"
src = sys.argv[1]
tmp = tempfile.mkdtemp()
model = WhisperModel(sys.argv[2] if len(sys.argv) > 2 else "small", device="cpu", compute_type="int8")
for t in range(9):
    wav = os.path.join(tmp, "t%d.wav" % t)
    subprocess.run([FF, "-y", "-v", "error", "-i", src, "-map", "0:a:%d" % t, "-ac", "1", "-ar", "16000", wav], check=True)
    segs, info = model.transcribe(wav, beam_size=1)
    text = " ".join(s.text.strip() for s in segs)
    print("pista %d [%s %.2f]: %s" % (t, info.language, info.language_probability, text[:400]), flush=True)
