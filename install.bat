@echo off
reg add HKCU\Console /v VirtualTerminalLevel /t REG_DWORD /d 1 /f >nul 2>&1
setlocal EnableDelayedExpansion
cls

echo.
echo [91m  ============================================================[0m
echo [93m       AMD - Apple Music Downloader - INSTALLER[0m
echo [91m  ============================================================[0m
echo.

cd /d "%~dp0"

echo [96m  [1/4] Checking Python installation...[0m
python --version >nul 2>&1
if errorlevel 1 (
    echo [91m  ERROR: Python is not installed or not in PATH![0m
    echo [93m  Please install Python from https://python.org[0m
    echo.
    pause
    exit /b 1
)
echo [92m  Python found![0m
echo.

echo [96m  [2/4] Installing required packages...[0m
pip install -r requirements.txt
if errorlevel 1 (
    echo [91m  ERROR: Failed to install packages![0m
    echo.
    pause
    exit /b 1
)
echo [92m  Packages installed successfully![0m
echo.

echo [96m  [3/4] Optional: AI Lyrics Generation[0m
echo.
echo [97m  Whisper AI can automatically generate lyrics for songs[0m
echo [97m  that don't have them by transcribing the audio.[0m
echo.
set /p "installWhisper=[93m  Install Whisper AI? (~1.5GB download) (Y/N): [0m"
if /i "%installWhisper%"=="Y" (
    echo.
    echo [96m  Installing openai-whisper...[0m
    pip install openai-whisper
    if errorlevel 1 (
        echo [91m  Warning: Failed to install Whisper. You can install it later.[0m
    ) else (
        echo [92m  Whisper installed successfully![0m
    )
) else (
    echo [93m  Skipped. You can install later with: pip install openai-whisper[0m
)
echo.

echo [96m  [4/4] Setup complete![0m
echo.
echo [92m  ============================================================[0m
echo [92m    Installation Complete![0m
echo [92m  ============================================================[0m
echo.

set /p "shortcut=[93m  Create desktop shortcut? (Y/N): [0m"
if /i "%shortcut%"=="Y" (
    echo.
    echo [96m  Creating desktop shortcut...[0m
    set "SCRIPT_DIR=%~dp0"
    set "SCRIPT_DIR=!SCRIPT_DIR:~0,-1!"
    
    if exist "!SCRIPT_DIR!\dist\AppleMusicDownloader.exe" (
        echo [96m  Found EXE build, using that...[0m
        set "TARGET=!SCRIPT_DIR!\dist\AppleMusicDownloader.exe"
        set "ICON=!SCRIPT_DIR!\dist\AppleMusicDownloader.exe,0"
    ) else (
        set "TARGET=!SCRIPT_DIR!\run_headless.bat"
        set "ICON=imageres.dll,190"
    )
    
    powershell -NoProfile -ExecutionPolicy Bypass -Command "& { $WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\Apple Music Downloader.lnk'); $Shortcut.TargetPath = '!TARGET!'; $Shortcut.WorkingDirectory = '!SCRIPT_DIR!'; $Shortcut.IconLocation = '!ICON!'; $Shortcut.Save() }"
    if exist "%USERPROFILE%\Desktop\Apple Music Downloader.lnk" (
        echo [92m  Desktop shortcut created![0m
    ) else (
        echo [91m  Failed to create shortcut.[0m
    )
)

echo.
echo [93m  Press any key to exit...[0m
pause >nul