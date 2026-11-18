@echo off
REM ============================================================
REM  Busca un Python 3.11 o mas nuevo y lo deja en la variable PY.
REM  Uso dentro de otro .bat:   call buscar_python.bat || goto :err
REM  (en Windows "python" puede ser una version antigua, por eso
REM   se prueba primero el lanzador "py", que elige la mas nueva)
REM ============================================================
set PY=
for /f "delims=" %%v in ('py -3 -c "import sys;print(1 if sys.version_info>=(3,11) else 0)" 2^>nul') do if "%%v"=="1" set "PY=py -3"
if not defined PY for /f "delims=" %%v in ('python -c "import sys;print(1 if sys.version_info>=(3,11) else 0)" 2^>nul') do if "%%v"=="1" set "PY=python"
if not defined PY (
  echo.
  echo *** Hace falta Python 3.11 o mas nuevo.
  echo     Descargalo de https://www.python.org/downloads/
  echo     y marca "Add python.exe to PATH" al instalarlo.
  exit /b 1
)
REM UTF-8 en la consola: si no, los mensajes con acentos y simbolos fallan
set PYTHONUTF8=1
for /f "delims=" %%v in ('%PY% -c "import sys;print(sys.version.split()[0])"') do echo Usando Python %%v
exit /b 0
