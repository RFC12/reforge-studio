@echo off
rem Compila el instalador externo del doblaje latino de COD: Advanced Warfare.
rem Necesita Python con: pyinstaller, lz4, imageio-ffmpeg (para copiar ffmpeg.exe dentro).
setlocal
cd /d "%~dp0\.."
python -m pip install -q pyinstaller lz4 imageio-ffmpeg || goto :err
for /f "delims=" %%F in ('python -c "import imageio_ffmpeg as f; print(f.get_ffmpeg_exe())"') do set FFMPEG=%%F
if not exist build\awlat mkdir build\awlat
copy /y "%FFMPEG%" build\awlat\ffmpeg.exe >nul || goto :err
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name ReForge-Doblaje-Latino-AW --icon assets\icon.ico --paths . --paths tools ^
  --hidden-import reforge.xiso --hidden-import reforge.xcontent --hidden-import lz4.block ^
  --add-binary "build\awlat\ffmpeg.exe;." --add-data "assets\icon.ico;assets" ^
  --distpath dist --workpath build\work-awlat tools\aw_latino_gui.py || goto :err
echo.
echo    dist\ReForge-Doblaje-Latino-AW.exe
exit /b 0
:err
echo *** Error al compilar ***
exit /b 1
