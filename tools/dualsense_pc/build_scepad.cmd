@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
cd /d "%~dp0"
cl /nologo /LD /O2 /EHsc /std:c++17 /utf-8 /DUNICODE /D_UNICODE scepad_proxy.cpp /Fe:libScePad.dll /link /DEF:libScePad.def hid.lib setupapi.lib && echo COMPILADO
