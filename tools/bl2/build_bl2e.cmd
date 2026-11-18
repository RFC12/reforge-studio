@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars32.bat" >nul
cd /d "%~dp0"
cl /nologo /LD /O2 /EHsc /std:c++17 /utf-8 /W3 /DUNICODE /D_UNICODE dualsense_bl2e.cpp /Fe:xinput1_3.dll /link /DEF:xi_bl2.def hid.lib setupapi.lib d3d11.lib user32.lib ole32.lib windowscodecs.lib && echo COMPILADO
