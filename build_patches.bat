@echo off
REM Empaqueta todos los parches de la carpeta patches\ en dist\patches\*.rfpatch
cd /d "%~dp0"
for /d %%P in (patches\*) do python tools\make_patch.py "%%P" -o dist\patches
pause
