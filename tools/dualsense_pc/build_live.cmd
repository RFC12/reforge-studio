@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
cd /d "%~dp0"
call build.cmd >nul 2>&1
cl /nologo /O2 /utf-8 test_live.cpp /Fe:test_live.exe >nul
(echo [dualsense]& echo texture_dump=0& echo texture_swap=0) > reforge_dualsense.ini
del reforge_dualsense.log 2>nul
test_live.exe
type reforge_dualsense.log
