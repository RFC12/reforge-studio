@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
cd /d "%~dp0"
cl /nologo /O2 /EHsc /utf-8 test_ds.cpp /Fe:test_ds.exe d3d11.lib >nul && (echo [dualsense]& echo texture_dump=1) > reforge_dualsense.ini && test_ds.exe & type reforge_dualsense.log & dir /b reforge_textures\dump
