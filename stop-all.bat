@echo off
setlocal
title ShortLink 一键停止

set "PORT=8000"
set "REDIS_DIR=D:\ProgramFiles\Redis"
set "REDIS_PORT=6379"

cd /d %~dp0

echo ==================================================
echo    ShortLink 一键停止
echo ==================================================
echo.

rem ---------- 1/2 短链服务 ----------
echo [1/2] 停止短链服务 ...
netstat -ano | findstr /C:":%PORT% " | findstr /C:"LISTENING" >nul 2>&1
if errorlevel 1 goto svc_none

echo        正在结束 uvicorn 进程 ^(连同它的子进程^) ...
powershell -NoProfile -Command "$ids = Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*uvicorn*' } | Select-Object -Expand ProcessId; foreach ($i in $ids) { taskkill /PID $i /T /F | Out-Null }"

set "N=0"
:svc_wait
timeout /t 1 /nobreak >nul
netstat -ano | findstr /C:":%PORT% " | findstr /C:"LISTENING" >nul 2>&1
if errorlevel 1 goto svc_ok
set /a N+=1
if %N% lss 8 goto svc_wait
echo        [警告] %PORT% 还在监听。可能是别的东西占着它。
echo        可在任务管理器里按端口 %PORT% 找到那个进程。
goto svc_end

:svc_none
echo        没有发现监听 %PORT% 的服务，跳过。
goto svc_end

:svc_ok
echo        [OK] 短链服务已停止

:svc_end
echo.

rem ---------- 2/2 Redis ----------
echo [2/2] 停止 Redis ...
"%REDIS_DIR%\redis-cli.exe" -p %REDIS_PORT% ping >nul 2>&1
if not errorlevel 1 goto redis_stop
echo        6379 上没有 Redis 在跑，跳过。
goto redis_end

:redis_stop
"%REDIS_DIR%\redis-cli.exe" -p %REDIS_PORT% shutdown save >nul 2>&1
set "N=0"
:redis_wait
timeout /t 1 /nobreak >nul
"%REDIS_DIR%\redis-cli.exe" -p %REDIS_PORT% ping >nul 2>&1
if errorlevel 1 goto redis_ok
set /a N+=1
if %N% lss 8 goto redis_wait
echo        [警告] 8 秒内没停下来，可能是另一个 Redis 占了 6379。
goto redis_end

:redis_ok
echo        [OK] Redis 已停止，数据已落盘

:redis_end
echo.
echo ==================================================
echo    已全部停止。下次启动双击 start-all.bat
echo ==================================================
timeout /t 3 /nobreak >nul
exit /b 0
