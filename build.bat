@echo off
setlocal EnableDelayedExpansion
cls

echo.
echo [91m  ============================================================[0m
echo [93m       AMD - Building Standalone EXE[0m
echo [91m  ============================================================[0m
echo.

cd /d "%~dp0"

pip install pyinstaller >nul 2>&1

echo [96m  Building (no console window)...[0m
echo.

pyinstaller --onefile --noconsole --name "AppleMusicDownloader" --add-data "templates;templates" --add-data "static;static" --add-data "config.yaml;." --hidden-import=flask --hidden-import=flask_socketio --hidden-import=engineio.async_drivers.threading --hidden-import=requests --hidden-import=yaml --hidden-import=mutagen --hidden-import=PIL --hidden-import=bs4 --hidden-import=tqdm --hidden-import=colorama --hidden-import=pycryptodomex --hidden-import=m3u8 app.py

echo.
if exist dist\AppleMusicDownloader.exe (
    echo [92m  Build successful! EXE: dist\AppleMusicDownloader.exe[0m
) else (
    echo [91m  Build failed! Check errors above.[0m
)

echo.
echo [93m  Press any key to exit...[0m
pause >nul