@echo off
REM ============================================================
REM  ReForge Studio - compilacion completa de la version
REM  Resultado:
REM    dist\ReForgeStudio-Setup-<version>.exe   instalador completo
REM        (programa + parches incluidos + descarga del SDK rexglue)
REM    dist\patches\*.rfpatch                   parches sueltos
REM
REM  Opcional: copia rexglue-sdk-*-win-amd64.zip junto al instalador
REM  para instalar el SDK sin conexion.
REM ============================================================
setlocal
cd /d "%~dp0"

call buscar_python.bat || goto :err

for /f "delims=" %%v in ('%PY% -c "import reforge;print(reforge.__version__)"') do set VER=%%v
if "%VER%"=="" goto :err
echo === ReForge Studio v%VER% ===

echo.
echo [1/6] Dependencias
%PY% -m pip install --upgrade pip >nul
%PY% -m pip install -r requirements.txt pyinstaller || goto :err

echo.
echo [2/6] Pruebas
for %%T in (tests\test_*.py) do (
  echo    %%~nxT
  %PY% "%%T" || goto :err
)

echo.
echo [3/6] Parches (se incluyen dentro del programa)
if exist dist\patches rmdir /s /q dist\patches
for /d %%P in (patches\*) do (
  %PY% tools\make_patch.py "%%P" -o dist\patches || goto :err
)

echo.
echo [4/6] Aplicacion (carpeta)
if exist build\app rmdir /s /q build\app
%PY% -m PyInstaller --noconfirm --clean --onedir --windowed ^
  --name ReForgeStudio --icon assets\icon.ico ^
  --add-data "assets;assets" --add-data "dist\patches;bundled_patches" --add-data "reforge\sdk_patches;reforge\sdk_patches" ^
  --collect-submodules send2trash --hidden-import PySide6.QtMultimedia ^
  --distpath build\app --workpath build\work main.py || goto :err
%PY% tools\make_payload.py build\app\ReForgeStudio build\installer || goto :err

echo.
echo [5/6] Instalador
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name ReForgeStudio-Setup-%VER% --icon assets\icon.ico --paths . ^
  --hidden-import reforge.toolchain --hidden-import reforge.sdkcompat --hidden-import reforge.autorecompile ^
  --hidden-import reforge.gamedb --hidden-import reforge.nativepatch --hidden-import reforge.migrate --hidden-import reforge.portimport --hidden-import reforge.communityports --hidden-import reforge.communityports_ui --hidden-import reforge.portachievements --hidden-import reforge.titleprofiles --hidden-import reforge.milestones --hidden-import reforge.launcher_views --hidden-import reforge.deferred_trace ^
  --add-data "build\installer\payload.zip;." --add-data "build\installer\payload.json;." ^
  --add-data "assets\icon.ico;." ^
  --distpath dist --workpath build\work-setup installer\setup.py || goto :err

echo.
echo [6/6] Listo
echo ============================================================
echo    dist\ReForgeStudio-Setup-%VER%.exe
echo    dist\patches\
echo.
echo    Para que el actualizador automatico lo vea, publica una
echo    Release en GitHub con la etiqueta v%VER% y sube ese .exe
echo    tal cual (el nombre del archivo es el que busca ReForge).
echo ============================================================
pause
exit /b 0

:err
echo.
echo *** Error durante la compilacion ***
pause
exit /b 1
