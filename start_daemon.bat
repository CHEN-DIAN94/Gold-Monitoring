@echo off
title 黄金监控守护进程
echo ========================================
echo 黄金监控守护进程已启动
echo 程序崩溃后将自动重启
echo ========================================
echo.

:loop
echo [%date% %time%] 启动黄金监控...
py "%~dp0黄金监控.py"

echo.
echo [%date% %time%] 程序已退出，5秒后自动重启...
timeout /t 5 /nobreak >nul
echo.
goto loop
