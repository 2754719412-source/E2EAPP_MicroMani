# 实验维护入口。默认预览，-Execute 才执行，路径相对当前仓库。
# backend 仅重启后端；full 还会重启 HAL 并重新初始化设备，须在现场维护窗口运行。
param(
  [ValidateSet('backend', 'full')][string]$Mode = 'backend',
  [switch]$Execute,
  [Parameter(DontShow)][ValidatePattern('^\d{8}_\d{6}$')][string]$WorkerStamp
)
$ErrorActionPreference = 'Stop'
$R = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Rt = "$R\backend\runtime"
$Py = "$R\backend\.venv\Scripts\python.exe"
$Dll = "$R\backend\native\build\appstation_fastdds_transport.dll"
$stamp = if ($WorkerStamp) { $WorkerStamp } else { Get-Date -Format 'yyyyMMdd_HHmmss' }
$log = Join-Path $Rt "logs\start_formal_$stamp.log"
function L($m) { $s = (Get-Date -Format 'HH:mm:ss.fff') + " $m"; Write-Host $s; if ($Execute) { Add-Content -LiteralPath $log $s } }

if ($Execute -and -not $WorkerStamp) {
  # 由 Windows 在当前用户会话中创建独立进程，避免调用端关闭或更新时一并终止正式服务。
  $startup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ShowWindow=[uint16]0}
  $shell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
  $command = '"{0}" -NoProfile -ExecutionPolicy Bypass -File "{1}" -Mode {2} -Execute -WorkerStamp {3}' -f $shell, $PSCommandPath, $Mode, $stamp
  $created = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine=$command; ProcessStartupInformation=$startup}
  if ($created.ReturnValue -ne 0) { throw "Cannot start independent formal worker: WMI error $($created.ReturnValue)" }
  $worker = Get-Process -Id $created.ProcessId -ErrorAction Stop
  [void]$worker.Handle
  $worker.WaitForExit()
  if (Test-Path -LiteralPath $log) { Get-Content -LiteralPath $log | Out-Host }
  if ($worker.ExitCode -ne 0) { throw "Formal startup failed (exit $($worker.ExitCode)); see $log" }
  return
}

trap {
  if ($WorkerStamp -and (Test-Path -LiteralPath (Split-Path $log))) { L "FAILED: $_" }
  break
}

foreach ($p in @($R, $Py, $Dll, "$R\hal\build\HalServer.exe", "$R\hal\build\JodellGripperWorker.exe", "$Rt\config.json")) {
  if (-not (Test-Path -LiteralPath $p)) { throw "missing: $p" }
}
if ($Execute) { New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null }
L "mode=$Mode execute=$Execute repo=$R runtime=$Rt head=$((git -C $R log -1 --format='%h %s') 2>$null)"
Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue  # uv Python 3.13 parents leak it into the 3.12 venv
# Use the defaults even if an old shell still carries the former overrides.
Remove-Item Env:APPSTATION_RUNTIME_DIR -ErrorAction SilentlyContinue
Remove-Item Env:APPSTATION_FASTDDS_BINDING_DLL -ErrorAction SilentlyContinue

if ($Mode -eq 'full') {
  # start-hal.ps1 reads force-sensor settings from $Rt\config.json, the same file the backend uses.
  L "start-hal.ps1 -Restart -Port 8091"
  if ($Execute) {
    $env:ProgramData = 'C:\ProgramData'
    $starter = Start-Process powershell -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + "$R\scripts\start-hal.ps1" + '"'), '-Restart', '-Port', '8091' `
      -WindowStyle Hidden -RedirectStandardOutput "$Rt\logs\start-hal_$stamp.out.log" -RedirectStandardError "$Rt\logs\start-hal_$stamp.err.log" -PassThru
    $starter.WaitForExit()
    if ($starter.ExitCode -ne 0) { throw "HAL restart failed; see $Rt\logs\start-hal_$stamp.*.log" }
    L "HAL restart completed"
  }
}

$old = @(Get-NetTCPConnection -LocalPort 18082 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
# 仅关闭由本仓库虚拟环境启动且占用目标端口的 AppStation 后端。
$owners = @()
foreach ($listener in $old) {
  $process = Get-CimInstance Win32_Process -Filter "ProcessId=$listener"
  if (-not $process -or $process.CommandLine -notmatch 'backend\.app:create_app') { throw "Unrecognized listener on port 18082: $listener" }
  $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.ParentProcessId)"
  if ($process.ExecutablePath -eq $Py) { $owners += $listener }
  elseif ($parent -and $parent.ExecutablePath -eq $Py) { $owners += $listener, $parent.ProcessId }
  else { throw "Port 18082 is owned by a different installation: $listener" }
}
L ("stop backend pids: " + ($owners -join ','))
if ($Execute) {
  foreach ($p in $owners) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue }
  $env:APPSTATION_HAL_MODE = 'real'
  $env:APPSTATION_HAL_BASE_URL = 'http://127.0.0.1:8091'
  $env:APPSTATION_HAL_TRANSPORT = 'dds'
  $env:APPSTATION_DDS_DOMAIN_ID = '42'
  $bp = Start-Process $Py -ArgumentList '-B', '-m', 'uvicorn', 'backend.app:create_app', '--factory', '--host', '0.0.0.0', '--port', '18082' `
    -WorkingDirectory $R -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput "$Rt\logs\backend-formal_$stamp.out.log" -RedirectStandardError "$Rt\logs\backend-formal_$stamp.err.log"
  L "backend started pid=$($bp.Id)"
  $t0 = Get-Date; $up = $false
  while (((Get-Date) - $t0).TotalSeconds -lt 40) {
    try { if ((Invoke-WebRequest http://127.0.0.1:18082/docs -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) { $up = $true; break } } catch {}
    Start-Sleep -Milliseconds 500
  }
  L ("backend /docs up=$up after {0:N1} s" -f ((Get-Date) - $t0).TotalSeconds)
  if (-not $up) { throw "backend not up; see $Rt\logs\backend-formal_$stamp.err.log" }
}
L 'done'
