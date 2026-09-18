@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
cl /nologo /utf-8 /std:c++20 /EHsc /MD /O2 /UAPPSTATION_ENABLE_VENDOR_SDKS /UAPPSTATION_ENABLE_DDS /D_WIN32_WINNT=0x0601 /I "D:\E2EAPP_MicroMani\output\remote-audit-20260917-213346-72a7e2e\source\hal\include" /c "D:\E2EAPP_MicroMani\output\remote-audit-20260917-213346-72a7e2e\source\hal\tests\ForceCoreTests.cpp" "D:\E2EAPP_MicroMani\output\remote-audit-20260917-213346-72a7e2e\source\hal\src\HkvlForceProtocol.cpp" "D:\E2EAPP_MicroMani\output\remote-audit-20260917-213346-72a7e2e\source\hal\src\ForceSafetyLatch.cpp" "D:\E2EAPP_MicroMani\output\remote-audit-20260917-213346-72a7e2e\source\hal\src\ForceComplianceController.cpp" "D:\E2EAPP_MicroMani\output\remote-audit-20260917-213346-72a7e2e\source\hal\src\HkvlForceDriver.cpp" "D:\E2EAPP_MicroMani\output\remote-audit-20260917-213346-72a7e2e\source\hal\src\ForceControlRuntime.cpp" "D:\E2EAPP_MicroMani\output\remote-audit-20260917-213346-72a7e2e\source\hal\src\LTDMCDriver.cpp" "D:\E2EAPP_MicroMani\output\remote-audit-20260917-213346-72a7e2e\source\hal\src\HalJson.cpp"
if errorlevel 1 exit /b 1
link /nologo /OUT:ForceCoreTests.exe ForceCoreTests.obj HkvlForceProtocol.obj ForceSafetyLatch.obj ForceComplianceController.obj HkvlForceDriver.obj ForceControlRuntime.obj LTDMCDriver.obj HalJson.obj
exit /b %errorlevel%

