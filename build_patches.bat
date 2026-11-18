@echo off
REM Empaqueta todos los parches de la carpeta patches\ en dist\patches\*.rfpatch
cd /d "%~dp0"
call buscar_python.bat || goto :err
for /d %%P in (patches\*) do %PY% tools\make_patch.py "%%P" -o dist\patches || goto :err
pause
exit /b 0
:err
echo Error al empaquetar los parches.
pause
exit /b 1
