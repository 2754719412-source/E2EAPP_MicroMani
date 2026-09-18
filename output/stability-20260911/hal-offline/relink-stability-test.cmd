@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
cl /nologo /utf-8 /std:c++20 /EHsc /MD /O2 /D_WIN32_WINNT=0x0601 /I "D:\E2EAPP_MicroMani\hal\include" /c D:\E2EAPP_MicroMani\hal\tests\ThreadStabilityTests.cpp
if errorlevel 1 exit /b 1
link /nologo /OUT:ThreadStabilityTests.exe ThreadStabilityTests.obj HalCommandDispatcher.obj HalJson.obj HkvlForceProtocol.obj ForceSafetyLatch.obj ForceComplianceController.obj HkvlForceDriver.obj ForceControlRuntime.obj LTDMCDriver.obj NativeTeleopController.obj Omega7Driver.obj JodellGripperDriver.obj TeleopHardwareTargetExecutor.obj
