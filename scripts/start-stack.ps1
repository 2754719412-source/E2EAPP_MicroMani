# 阅读导航 08｜启动、部署与工具
# 职责：按顺序启动 HAL、后端和前端，并管理同项目旧进程及日志。
# 先看：Stop-ProcessTree → Stop-BackendProcessTrees。
# 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；逐文件目录：docs/SOURCE_INDEX.md。

param(
  [int]$BackendPort = 18082,
  [int]$FrontendPort = 5174,
  [int]$HalPort = 8091,
  [switch]$RestartHal
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$logDir = Join-Path $repo "backend\runtime\logs"
$frontendOutLog = Join-Path $logDir "frontend-launch.out.log"
$frontendErrLog = Join-Path $logDir "frontend-launch.err.log"

function Stop-ProcessTree {
  param([int]$RootPid)

  $allProcesses = Get-CimInstance Win32_Process
  $children = $allProcesses | Where-Object { $_.ParentProcessId -eq $RootPid }
  foreach ($child in $children) {
    Stop-ProcessTree -RootPid $child.ProcessId
  }
  Stop-Process -Id $RootPid -Force -ErrorAction SilentlyContinue
}

function Stop-BackendProcessTrees {
  $allProcesses = Get-CimInstance Win32_Process
  $escapedRepo = [regex]::Escape($repo)
  $backendProcesses = @($allProcesses | Where-Object {
      $process = $_
      $commandLine = $process.CommandLine
      if (-not $commandLine) {
        return $false
      }
      if ($commandLine -notmatch "backend\.app:create_app" -or $commandLine -notmatch "--port\s+$BackendPort") {
        return $false
      }
      if ($commandLine -match $escapedRepo) {
        return $true
      }
      $parent = $allProcesses | Where-Object { $_.ProcessId -eq $process.ParentProcessId } | Select-Object -First 1
      return (
        $parent -and
        $parent.CommandLine -and
        $parent.CommandLine -match $escapedRepo -and
        $parent.CommandLine -match "backend\.app:create_app" -and
        $parent.CommandLine -match "--port\s+$BackendPort"
      )
    })

  $rootPids = @($backendProcesses | ForEach-Object {
      $process = $_
      $rootPid = $process.ProcessId
      $parent = $allProcesses | Where-Object { $_.ProcessId -eq $process.ParentProcessId } | Select-Object -First 1
      if (
        $parent -and
        $parent.CommandLine -and
        $parent.CommandLine -match $escapedRepo -and
        $parent.CommandLine -match "backend\.app:create_app" -and
        $parent.CommandLine -match "--port\s+$BackendPort"
      ) {
        $rootPid = $parent.ProcessId
      }
      $rootPid
    } | Sort-Object -Unique)

  foreach ($rootPid in $rootPids) {
    Stop-ProcessTree -RootPid $rootPid
  }
}

Stop-BackendProcessTrees

$backendPid = Get-NetTCPConnection -LocalPort $BackendPort -State Listen -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -First 1
if ($backendPid) {
  $backendRootPid = $backendPid
  $allProcesses = Get-CimInstance Win32_Process
  $backendProcess = $allProcesses | Where-Object { $_.ProcessId -eq $backendPid } | Select-Object -First 1
  $backendParent = $allProcesses | Where-Object { $_.ProcessId -eq $backendProcess.ParentProcessId } | Select-Object -First 1
  if ($backendParent -and $backendParent.CommandLine -match "backend\.app:create_app" -and $backendParent.CommandLine -match "--port\s+$BackendPort") {
    $backendRootPid = $backendParent.ProcessId
  }
  Stop-ProcessTree -RootPid $backendRootPid
}

$frontendPid = Get-NetTCPConnection -LocalPort $FrontendPort -State Listen -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -First 1
if ($frontendPid) {
  Stop-Process -Id $frontendPid -Force -ErrorAction SilentlyContinue
}

$activeHalPort = $HalPort
# 控制卡计数在 HAL 进程重启后不变，但参考点和工作原点按 HAL 实例确认；
# 本仓库的 HAL 仍在运行时直接复用，避免每次打开程序都要重新建参考。
$halExePath = Join-Path $repo "hal\build\HalServer.exe"
$runningHal = Get-NetTCPConnection -LocalPort $HalPort -State Listen -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -First 1 |
  ForEach-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue }
$reuseHal = (-not $RestartHal) -and $runningHal -and ($runningHal.Path -eq $halExePath)
try {
  if ($reuseHal) {
    Write-Host "Reusing running HAL pid=$($runningHal.Id) on port $HalPort (references stay valid)"
    & (Join-Path $PSScriptRoot "start-hal.ps1") -Port $activeHalPort | Out-Host
  } else {
    & (Join-Path $PSScriptRoot "start-hal.ps1") -Restart -Port $activeHalPort | Out-Host
  }
} catch {
  $halStartError = $_.Exception.Message
  # 仅监听端口失败时换端口，初始化超时或崩溃应保留首次诊断。
  if ($HalPort -ne 8091 -or $halStartError -notmatch "Failed to bind HalServer on 127\.0\.0\.1:8091") {
    throw
  }
  Write-Warning "HAL start on port 8091 failed; retrying on 8092. $halStartError"
  $activeHalPort = 8092
  & (Join-Path $PSScriptRoot "start-hal.ps1") -Restart -Port $activeHalPort | Out-Host
}

Start-Sleep -Seconds 1

New-Item -ItemType Directory -Path $logDir -Force | Out-Null
Remove-Item -LiteralPath $frontendOutLog, $frontendErrLog -Force -ErrorAction SilentlyContinue

$env:APPSTATION_HAL_MODE = "real"
$env:APPSTATION_HAL_BASE_URL = "http://127.0.0.1:$activeHalPort"
$env:APPSTATION_HAL_TRANSPORT = "dds"
if (-not $env:APPSTATION_DDS_DOMAIN_ID) { $env:APPSTATION_DDS_DOMAIN_ID = "42" }
$jodellBinding = Join-Path $repo "frontend\.env.local"
if (-not $env:APPSTATION_JODELL_EXTERNAL_PORT -and (Test-Path -LiteralPath $jodellBinding) -and
    (Get-Process -Name 'clawControlTool*' -ErrorAction SilentlyContinue)) {
  # 厂商工具独占已绑定串口，启动时仅在另一侧恢复 HAL 采样。
  $boundPort = Select-String -LiteralPath $jodellBinding -Pattern '^\s*APPSTATION_JODELL_CAPTURE_PORT\s*=\s*(COM\d+)\s*$' |
    Select-Object -Last 1
  if ($boundPort) { $env:APPSTATION_JODELL_EXTERNAL_PORT = $boundPort.Matches[0].Groups[1].Value }
}
$backend = Start-Process `
  -FilePath (Join-Path $repo "backend\.venv\Scripts\python.exe") `
  -ArgumentList @("-m", "uvicorn", "backend.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "$BackendPort") `
  -WorkingDirectory $repo `
  -WindowStyle Hidden `
  -PassThru

$frontendCommand = "`$env:VITE_MOCK_MODE='false'; `$env:VITE_API_BASE=''; `$env:VITE_WS_URL=''; `$env:VITE_BACKEND_PORT='$BackendPort'; npm run build; if (`$LASTEXITCODE -ne 0) { exit `$LASTEXITCODE }; node scripts/serve-dist.mjs --host 0.0.0.0 --port $FrontendPort"
$frontend = Start-Process `
  -FilePath "powershell.exe" `
  -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $frontendCommand) `
  -WorkingDirectory (Join-Path $repo "frontend") `
  -WindowStyle Hidden `
  -RedirectStandardOutput $frontendOutLog `
  -RedirectStandardError $frontendErrLog `
  -PassThru

Start-Sleep -Seconds 3

[pscustomobject]@{
  backendPid = $backend.Id
  frontendLauncherPid = $frontend.Id
  backend = "http://127.0.0.1:$BackendPort"
  frontend = "http://127.0.0.1:$FrontendPort"
  hal = "http://127.0.0.1:$activeHalPort"
  frontendOutLog = $frontendOutLog
  frontendErrLog = $frontendErrLog
}
