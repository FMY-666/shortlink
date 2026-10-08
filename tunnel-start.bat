@echo off
setlocal
cd /d "%~dp0"

set "CLOUDFLARED=D:\ProgramFiles\cloudflared\cloudflared.exe"

echo ============================================================
echo   Cloudflare 免费隧道  -  让外网也能访问你的短链服务
echo ============================================================
echo.
if not exist "%CLOUDFLARED%" goto no_cf
if not exist ".venv\Scripts\python.exe" goto no_venv
if not exist "tools\tunnel.py" goto no_py
goto run

:no_cf
echo [错误] 找不到 cloudflared.exe :
echo         %CLOUDFLARED%
echo.
echo 下载 cloudflared-windows-amd64.exe 放到该目录并改名 cloudflared.exe 即可，
echo 或者改本文件里的 CLOUDFLARED 变量，指向它的实际路径。
echo.
pause
exit /b 1

:no_venv
echo [错误] 找不到 .venv\Scripts\python.exe
echo 请先按 README 建好虚拟环境并装好依赖。
echo.
pause
exit /b 1

:no_py
echo [错误] 找不到 tools\tunnel.py
echo 请在项目根目录下运行本脚本。
echo.
pause
exit /b 1

:run
echo 正在向 Cloudflare 申请隧道地址，大约 10 秒...
echo 拿到地址后会自动写进 .env 的 BASE_URL。
echo.
echo 注意：这个窗口不能关，关了隧道就断。
echo 想停就按 Ctrl+C，或者直接关掉窗口。
echo.
echo ------------------------------------------------------------
".venv\Scripts\python.exe" "tools\tunnel.py"
echo ------------------------------------------------------------
echo.
echo 隧道已退出。
echo 注意：.env 里的 BASE_URL 还留着那个 trycloudflare 地址。
echo 要让短链改回局域网地址，把它改回 http://192.168.0.100:8000 再重启服务。
echo.
pause
exit /b 0
