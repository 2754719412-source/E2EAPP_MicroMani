@echo off
chcp 65001 >nul
title AppStation 优化预览
setlocal

set "DIR=%~dp0"
set "HTML=%DIR%appstation-optimized.html"

echo ============================================
echo   AppStation 前端优化预览
echo   文件: %HTML%
echo ============================================
echo.

where python >nul 2>nul
if %errorlevel%==0 (
  echo [1/2] 使用 Python 启动本地服务 http://127.0.0.1:5500
  start "" "http://127.0.0.1:5500/appstation-optimized.html"
  echo [2/2] 按 Ctrl+C 可停止服务
  python -m http.server 5500 --bind 127.0.0.1 --directory "%DIR%"
  goto :end
)

where py >nul 2>nul
if %errorlevel%==0 (
  echo [1/2] 使用 Python 启动本地服务 http://127.0.0.1:5500
  start "" "http://127.0.0.1:5500/appstation-optimized.html"
  echo [2/2] 按 Ctrl+C 可停止服务
  py -m http.server 5500 --bind 127.0.0.1 --directory "%DIR%"
  goto :end
)

echo 未找到 Python，直接用系统浏览器打开本地文件...
start "" "%HTML%"
echo 已打开。若需本地 HTTP 方式，请安装 Python 或使用 Node 版脚本。
pause

:end
endlocal
