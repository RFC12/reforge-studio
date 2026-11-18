@echo off
REM Genera dist\ReForgeStudio.exe (un solo archivo, sin consola)
cd /d "%~dp0"
call buscar_python.bat || goto :err
%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt pyinstaller || goto :err
for /d %%P in (patches\*) do %PY% tools\make_patch.py "%%P" -o dist\patches || goto :err
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed ^
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
