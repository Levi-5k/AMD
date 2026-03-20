@echo off
setlocal EnableDelayedExpansion
cls

echo.
echo [91m  ============================================================[0m
echo [93m       AMD - Apple Music Downloader[0m
echo [91m  ============================================================[0m
echo.
echo [97m  Starting server...[0m
echo.

cd /d "%~dp0"

if exist start.py (
    python start.py
) else (
    python app.py
)

echo.
echo [93m  Press any key to exit...[0m
pause >nul