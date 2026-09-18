@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
cl /nologo /utf-8 /std:c++20 /EHsc /MD /O2 /DAPPSTATION_ENABLE_VENDOR_SDKS=1 /D_WIN32_WINNT=0x0601 /I "D:\E2EAPP_MicroMani\hal\include" /c D:\E2EAPP_MicroMani\hal\src\ForceControlRuntime.cpp D:\E2EAPP_MicroMani\hal\src\HkvlForceDriver.cpp D:\E2EAPP_MicroMani\hal\src\LTDMCDriver.cpp D:\E2EAPP_MicroMani\hal\src\NativeTeleopController.cpp D:\E2EAPP_MicroMani\hal\src\Omega7Driver.cpp D:\E2EAPP_MicroMani\hal\src\JodellGripperDriver.cpp D:\E2EAPP_MicroMani\hal\src\HalCommandDispatcher.cpp D:\E2EAPP_MicroMani\hal\src\HalServer.cpp D:\E2EAPP_MicroMani\hal\src\TeleopHardwareTargetExecutor.cpp D:\E2EAPP_MicroMani\hal\src\HalHttpServer.cpp D:\E2EAPP_MicroMani\hal\src\MotionControlThread.cpp

