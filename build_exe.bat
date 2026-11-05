@echo off
REM Genera dist\ReForgeStudio.exe (un solo archivo, sin consola)
cd /d "%~dp0"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller || goto :err
for /d %%P in (patches\*) do python tools\make_patch.py "%%P" -o dist\patches
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name ReForgeStudio --icon assets\icon.ico ^
  --add-data "assets;assets" --add-data "dist\patches;bundled_patches" --collect-submodules send2trash main.py || goto :err
echo.
echo Listo: dist\ReForgeStudio.exe
pause
exit /b 0
:err
echo Error durante la compilacion.
pause
exit /b 1
