@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
cd /d "%~dp0"
cl /nologo /O2 /EHsc /std:c++17 /utf-8 /DDS_STANDALONE /DUNICODE /D_UNICODE dualsense.cpp /Fe:probar_gatillos.exe hid.lib setupapi.lib d3d11.lib user32.lib >nul && echo ok
