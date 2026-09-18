@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
cl /nologo /utf-8 /std:c++20 /EHsc /MD /O2 /D_WIN32_WINNT=0x0601 /I "D:\E2EAPP_MicroMani\hal\include" /c D:\E2EAPP_MicroMani\hal\src\ForceComplianceController.cpp D:\E2EAPP_MicroMani\hal\src\ForceControlRuntime.cpp D:\E2EAPP_MicroMani\hal\src\ForceSafetyLatch.cpp D:\E2EAPP_MicroMani\hal\src\HkvlForceDriver.cpp D:\E2EAPP_MicroMani\hal\src\HkvlForceProtocol.cpp D:\E2EAPP_MicroMani\hal\src\LTDMCDriver.cpp D:\E2EAPP_MicroMani\hal\src\HalJson.cpp D:\E2EAPP_MicroMani\hal\src\HalCommandDispatcher.cpp D:\E2EAPP_MicroMani\hal\src\NativeTeleopController.cpp D:\E2EAPP_MicroMani\hal\src\Omega7Driver.cpp D:\E2EAPP_MicroMani\hal\src\JodellGripperDriver.cpp D:\E2EAPP_MicroMani\hal\src\TeleopHardwareTargetExecutor.cpp D:\E2EAPP_MicroMani\hal\tests\ForceCoreTests.cpp D:\E2EAPP_MicroMani\hal\tests\EmergencyStopTests.cpp D:\E2EAPP_MicroMani\hal\tests\ThreadStabilityTests.cpp D:\E2EAPP_MicroMani\hal\tests\WorkerResilienceTests.cpp D:\E2EAPP_MicroMani\hal\tests\ControlLeaseTests.cpp D:\E2EAPP_MicroMani\hal\src\MotionControlThread.cpp
if errorlevel 1 exit /b 1
link /nologo /OUT:ForceCoreTests.exe ForceCoreTests.obj HkvlForceProtocol.obj ForceSafetyLatch.obj ForceComplianceController.obj HkvlForceDriver.obj ForceControlRuntime.obj LTDMCDriver.obj HalJson.obj
if errorlevel 1 exit /b 1
link /nologo /OUT:EmergencyStopTests.exe EmergencyStopTests.obj HalCommandDispatcher.obj HalJson.obj HkvlForceProtocol.obj ForceSafetyLatch.obj ForceComplianceController.obj HkvlForceDriver.obj ForceControlRuntime.obj LTDMCDriver.obj NativeTeleopController.obj Omega7Driver.obj JodellGripperDriver.obj TeleopHardwareTargetExecutor.obj

if errorlevel 1 exit /b 1
link /nologo /OUT:ThreadStabilityTests.exe ThreadStabilityTests.obj HalCommandDispatcher.obj HalJson.obj HkvlForceProtocol.obj ForceSafetyLatch.obj ForceComplianceController.obj HkvlForceDriver.obj ForceControlRuntime.obj LTDMCDriver.obj NativeTeleopController.obj Omega7Driver.obj JodellGripperDriver.obj TeleopHardwareTargetExecutor.obj

if errorlevel 1 exit /b 1
link /nologo /OUT:WorkerResilienceTests.exe WorkerResilienceTests.obj HalCommandDispatcher.obj HalJson.obj HkvlForceProtocol.obj ForceSafetyLatch.obj ForceComplianceController.obj HkvlForceDriver.obj ForceControlRuntime.obj LTDMCDriver.obj NativeTeleopController.obj Omega7Driver.obj JodellGripperDriver.obj TeleopHardwareTargetExecutor.obj MotionControlThread.obj
if errorlevel 1 exit /b 1
link /nologo /OUT:ControlLeaseTests.exe ControlLeaseTests.obj HalCommandDispatcher.obj HalJson.obj HkvlForceProtocol.obj ForceSafetyLatch.obj ForceComplianceController.obj HkvlForceDriver.obj ForceControlRuntime.obj LTDMCDriver.obj NativeTeleopController.obj Omega7Driver.obj JodellGripperDriver.obj TeleopHardwareTargetExecutor.obj

