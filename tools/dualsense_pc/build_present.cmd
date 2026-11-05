@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
cd /d "%~dp0"
call build.cmd >nul 2>&1
cl /nologo /O2 /utf-8 test_present.cpp /Fe:test_present.exe >nul
(echo [dualsense]& echo texture_dump=0& echo fps_limit=60& echo performance_log=1) > reforge_dualsense.ini
del reforge_dualsense.log 2>nul
test_present.exe
type reforge_dualsense.log
