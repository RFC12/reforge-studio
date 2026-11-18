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

for /f "delims=" %%v in ('python -c "import reforge;print(reforge.__version__)"') do set VER=%%v
if "%VER%"=="" goto :err
echo === ReForge Studio v%VER% ===

echo.
echo [1/6] Dependencias
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller || goto :err

echo.
echo [2/6] Pruebas
python tests\test_xiso.py || goto :err
python tests\test_patches.py || goto :err
python tests\test_pipeline.py || goto :err
python tests\test_launch.py || goto :err
python tests\test_game_profiles.py || goto :err
python tests\test_runtime_repair.py || goto :err
python tests\test_installer.py || goto :err
python tests\test_play_repair_ui.py || goto :err
python tests\test_launcher.py || goto :err
python tests\test_profile.py || goto :err
python tests\test_optimizer.py || goto :err
python tests\test_watcher_sound.py || goto :err
python tests\test_toast_anim.py || goto :err
python tests\test_quality.py || goto :err
python tests\test_xcontent.py || goto :err
python tests\test_truncated.py || goto :err
python tests\test_title_update.py || goto :err
python tests\test_cheats.py || goto :err
python tests\test_deepscan.py || goto :err
python tests\test_engine.py || goto :err
python tests\test_pc_enhance.py || goto :err
python tests\test_crash_guard.py || goto :err
python tests\test_perfdiag.py || goto :err
python tests\test_autoconfig.py || goto :err
python tests\test_guide_menu.py || goto :err
python tests\test_sweep.py || goto :err
python tests\test_gameicon.py || goto :err
python tests\test_mods.py || goto :err
python tests\test_seh.py || goto :err
python tests\test_split.py || goto :err
python tests\test_texswap.py || goto :err
python tests\test_extra_content.py || goto :err
python tests\test_shadercache.py || goto :err
python tests\test_update.py || goto :err

echo.
echo [3/6] Parches (se incluyen dentro del programa)
if exist dist\patches rmdir /s /q dist\patches
for /d %%P in (patches\*) do (
  python tools\make_patch.py "%%P" -o dist\patches || goto :err
)

echo.
echo [4/6] Aplicacion (carpeta)
if exist build\app rmdir /s /q build\app
python -m PyInstaller --noconfirm --clean --onedir --windowed ^
  --name ReForgeStudio --icon assets\icon.ico ^
  --add-data "assets;assets" --add-data "dist\patches;bundled_patches" --add-data "reforge\sdk_patches;reforge\sdk_patches" ^
  --collect-submodules send2trash --hidden-import PySide6.QtMultimedia ^
  --distpath build\app --workpath build\work main.py || goto :err
python tools\make_payload.py build\app\ReForgeStudio build\installer || goto :err

echo.
echo [5/6] Instalador
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name ReForgeStudio-Setup-%VER% --icon assets\icon.ico --paths . ^
  --hidden-import reforge.toolchain ^
  --add-data "build\installer\payload.zip;." --add-data "build\installer\payload.json;." ^
  --add-data "assets\icon.ico;." ^
  --distpath dist --workpath build\work-setup installer\setup.py || goto :err

echo.
echo [6/6] Listo
echo ============================================================
echo    dist\ReForgeStudio-Setup-%VER%.exe
echo    dist\patches\
echo ============================================================
pause
exit /b 0

:err
echo.
echo *** Error durante la compilacion ***
pause
exit /b 1
