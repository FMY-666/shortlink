@echo off
setlocal
title ShortLink 一键启动

rem ==================== 可调参数 ====================
rem 想让同一局域网的其他设备也能用：把 HOST 改成 0.0.0.0
rem 并把 .env 里的 BASE_URL 改成 http://你的局域网IP:8000
set "HOST=0.0.0.0"
set "PORT=8000"
set "REDIS_DIR=D:\ProgramFiles\Redis"
set "REDIS_PORT=6379"

cd /d %~dp0

set "OPEN_URL=http://%HOST%:%PORT%/"
if "%HOST%"=="0.0.0.0" set "OPEN_URL=http://127.0.0.1:%PORT%/"

echo ==================================================
echo    ShortLink 一键启动
echo    项目目录 : %~dp0
echo ==================================================
echo.

rem ---------- 前置：虚拟环境 ----------
echo [前置] 检查虚拟环境 ...
if not exist ".venv\Scripts\python.exe" goto no_venv
echo        [OK] .venv 就位
echo.
goto step1

:no_venv
echo        [失败] 找不到 .venv\Scripts\python.exe
echo        先在项目根目录执行两件事：
echo          python -m venv .venv
echo          .venv\Scripts\pip.exe install -r requirements.txt
echo.
pause
exit /b 1

rem ---------- 1/3 MySQL ----------
:step1
echo [1/3] 检查 MySQL ...
netstat -ano | findstr /C:":3306 " | findstr /C:"LISTENING" >nul 2>&1
if not errorlevel 1 goto mysql_ok
echo        3306 没在监听，尝试启动服务 MySQL80 ...
net start MySQL80
netstat -ano | findstr /C:":3306 " | findstr /C:"LISTENING" >nul 2>&1
if not errorlevel 1 goto mysql_ok
echo        [失败] MySQL 起不来。两种办法：
echo          1^) 右键本脚本 - 以管理员身份运行
echo          2^) 手工到「服务」里启动 MySQL80
echo.
pause
exit /b 1

:mysql_ok
echo        [OK] MySQL 在运行 ^(3306^)
echo.

rem ---------- 2/3 Redis ----------
echo [2/3] 检查 Redis ...
"%REDIS_DIR%\redis-cli.exe" -p %REDIS_PORT% ping >nul 2>&1
if not errorlevel 1 goto redis_ok
echo        6379 没在跑，正在拉起 ...
start "Redis %REDIS_PORT%" /min /D "%REDIS_DIR%" redis-server.exe redis.conf
set "N=0"
:redis_wait
timeout /t 1 /nobreak >nul
"%REDIS_DIR%\redis-cli.exe" -p %REDIS_PORT% ping >nul 2>&1
if not errorlevel 1 goto redis_ok
set /a N+=1
if %N% lss 10 goto redis_wait
echo        [失败] 10 秒内连不上 6379。
echo        双击 %REDIS_DIR%\start.bat 前台启动一次，看具体报错。
echo.
pause
exit /b 1

:redis_ok
echo        [OK] Redis 在运行 ^(6379^)
echo.

rem ---------- 3/3 短链服务 ----------
echo [3/3] 检查短链服务 ...
netstat -ano | findstr /C:":%PORT% " | findstr /C:"LISTENING" >nul 2>&1
if errorlevel 1 goto svc_start
echo        端口 %PORT% 已被占用，服务可能已经在跑 —— 直接开浏览器。
start "" "%OPEN_URL%"
echo.
pause
exit /b 0

:svc_start
echo        4 秒后自动打开浏览器: %OPEN_URL%
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 4; Start-Process '%OPEN_URL%'"
echo.
echo ==================================================
echo    服务正在本窗口运行，下面就是它的日志
echo    停止：按 Ctrl+C，或直接关掉本窗口
echo    顺手也要停 Redis：双击 stop-all.bat
echo ==================================================
echo.

.venv\Scripts\python.exe -m uvicorn app.main:app --host %HOST% --port %PORT% --reload

echo.
echo 服务已退出。
pause
