@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
cl /nologo /utf-8 /std:c++20 /EHsc /MD /O2 /UAPPSTATION_ENABLE_VENDOR_SDKS /UAPPSTATION_ENABLE_DDS /D_WIN32_WINNT=0x0601 /I "D:\E2EAPP_MicroMani\hal\include" /c "D:\E2EAPP_MicroMani\hal\tests\HalHealthTests.cpp" "D:\E2EAPP_MicroMani\hal\src\HalJson.cpp" "D:\E2EAPP_MicroMani\hal\src\LTDMCDriver.cpp"
if errorlevel 1 exit /b 1
link /nologo /OUT:HalHealthTests.exe HalHealthTests.obj HalJson.obj LTDMCDriver.obj
exit /b %errorlevel%
