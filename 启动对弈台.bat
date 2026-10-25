@echo off
title SANCHI Patent Xiangqi - Local Arena (port 8771)
cd /d "%~dp0server"

set "PY=D:\Program Files\Python312\python.exe"
if not exist "%PY%" set "PY=python"

rem ---- guard: if the arena is already listening on 8771, just open the page ----
netstat -ano | findstr /C:"LISTENING" | findstr /C:":8771 " >nul 2>&1
if not errorlevel 1 goto already_running

echo ============================================================
echo   SANCHI Patent Xiangqi - Local Arena
echo   Port  : 8771
echo   Board : http://127.0.0.1:8771/
echo.
echo   The browser will open automatically (do NOT set
echo   SANCHI_NO_BROWSER=1).
echo   Close this window to stop the server.
echo ============================================================
echo.

"%PY%" app.py --local

echo.
echo Server stopped.
pause
exit /b

:already_running
echo ============================================================
echo   Arena is ALREADY running on port 8771.
echo   Opening  http://127.0.0.1:8771/  ...
echo.
echo   To RESTART it: close the other console window first,
echo   then double-click this shortcut again.
echo ============================================================
start "" "http://127.0.0.1:8771/"
ping -n 3 127.0.0.1 >nul
