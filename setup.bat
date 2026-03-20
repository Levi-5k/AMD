@echo off
echo ========================================
echo   Apple Music Downloader - Setup Script
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH!
    echo Opening Python download page...
    start https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [OK] Python found!
echo.

REM Check if Docker is running, if not try to start it
docker info >nul 2>&1
if errorlevel 1 (
    echo [INFO] Docker is not running. Attempting to start Docker Desktop...
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    echo [INFO] Waiting for Docker to start (this may take up to 60 seconds)...
    
    REM Wait for Docker to be ready
    set /a count=0
    :waitloop
    timeout /t 5 >nul
    docker info >nul 2>&1
    if not errorlevel 1 goto dockerready
    set /a count+=1
    echo        Still waiting... (%count%/12)
    if %count% lss 12 goto waitloop
    
    echo [ERROR] Docker did not start in time. Please start Docker Desktop manually.
    pause
    exit /b 1
)

:dockerready
echo [OK] Docker is running!
echo.

REM Install Python requirements
echo Installing Python requirements...
echo ----------------------------------------
pip install -r requirements.txt
echo.

echo [OK] Python requirements installed!
echo.
echo ========================================
echo   Opening download pages for required tools...
echo ========================================
echo.

REM Open download pages for required tools
echo [1/4] Opening apple-music-downloader GitHub page...
start https://github.com/zhaarey/apple-music-downloader

timeout /t 2 >nul

echo [2/4] Opening MP4Box (GPAC) download page...
start https://gpac.io/downloads/gpac-nightly-builds/

timeout /t 2 >nul

echo [3/4] Opening Docker Desktop download page...
echo      NOTE: Docker is required to run wrapper on Windows!
start https://www.docker.com/products/docker-desktop/

timeout /t 2 >nul

echo [4/4] Opening mp4decrypt (Bento4) download page...
echo      NOTE: You only need mp4decrypt.exe from this download!
start https://www.bento4.com/downloads/

echo.
echo ========================================
echo   Setup Complete!
echo ========================================
echo.
echo Next steps:
echo   1. apple-music-downloader: Clone the repo or use Docker
echo   2. GPAC: Install MP4Box from the installer
echo   3. Docker: Install Docker Desktop, then run wrapper with:
echo      docker build --tag wrapper https://github.com/WorldObservationLog/wrapper.git
echo      docker run -it -v ./rootfs/data:/app/rootfs/data -e args='-L user:pass -H 0.0.0.0' wrapper
echo      docker run -v ./rootfs/data:/app/rootfs/data -p 10020:10020 -p 20020:20020 -p 30020:30020 -e args="-H 0.0.0.0" wrapper
echo   4. Bento4: Extract ZIP and copy mp4decrypt.exe from the bin folder
echo   5. Get your media-user-token from Apple Music cookies
echo   6. Run the app with: run.bat (or python start.py)
echo.
echo NOTE: The app will auto-install any missing Python packages when first run!
echo.
echo Press any key to exit...
pause >nul
