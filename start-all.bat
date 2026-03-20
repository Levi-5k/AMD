@echo off
REM Apple Music Downloader - Full Startup Script
REM Starts both the wrapper service and the web app

setlocal enabledelayedexpansion

set "AMD_DIR=%~dp0"
set "WRAPPER_DATA=%AMD_DIR%wrapper-data"

echo ============================================================
echo  Apple Music Downloader - Full Startup
echo ============================================================
echo.

REM Check if Docker is running
docker info >nul 2>&1
if errorlevel 1 (
    echo [INFO] Docker is not running. Starting Docker Desktop...
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    
    echo [INFO] Waiting for Docker to start...
    call :wait_for_docker
    if errorlevel 1 (
        echo [ERROR] Docker failed to start within 60 seconds.
        echo Please start Docker Desktop manually and try again.
        pause
        exit /b 1
    )
    echo [OK] Docker is now running
    REM Give Docker a moment to fully initialize
    timeout /t 3 >nul
) else (
    echo [OK] Docker is already running
)

REM Check if wrapper-data exists (means user has logged in before)
if not exist "%WRAPPER_DATA%" (
    echo [WARNING] Wrapper data not found. You may need to run first-time setup.
    echo Run start-wrapper.bat and choose option 2 to Login first.
    echo.
)

REM Check if wrapper is running
docker ps --filter "name=amd-wrapper" --format "{{.Names}}" | findstr /i "amd-wrapper" >nul
if errorlevel 1 (
    echo Starting wrapper service...
    docker run -d --name amd-wrapper --restart unless-stopped ^
        -v "%WRAPPER_DATA%:/app/rootfs/data" ^
        -p 10020:10020 -p 20020:20020 -p 30020:30020 ^
        -e args="-H 0.0.0.0" ^
        ghcr.io/worldobservationlog/wrapper 2>nul
    
    if errorlevel 1 (
        echo Removing old wrapper container...
        docker rm -f amd-wrapper 2>nul
        docker run -d --name amd-wrapper --restart unless-stopped ^
            -v "%WRAPPER_DATA%:/app/rootfs/data" ^
            -p 10020:10020 -p 20020:20020 -p 30020:30020 ^
            -e args="-H 0.0.0.0" ^
            ghcr.io/worldobservationlog/wrapper
    )
    echo [OK] Wrapper started
    timeout /t 3 >nul
) else (
    echo [OK] Wrapper is already running
)

echo.
echo Starting web app...
echo.

REM Activate virtual environment and start Flask
if exist "%AMD_DIR%.venv\Scripts\activate.bat" (
    call "%AMD_DIR%.venv\Scripts\activate.bat"
) else if exist "%AMD_DIR%venv\Scripts\activate.bat" (
    call "%AMD_DIR%venv\Scripts\activate.bat"
)

echo ============================================================
echo  Web App: http://127.0.0.1:5000
echo  Wrapper: Running on ports 10020, 20020, 30020
echo ============================================================
echo.
echo Press Ctrl+C to stop the web app
echo.

python "%AMD_DIR%app.py"
if errorlevel 1 (
    echo.
    echo [ERROR] Python script exited with an error.
)

pause
goto :eof

REM Subroutine to wait for Docker to start
:wait_for_docker
set /a DOCKER_WAIT=0
:wait_docker_loop
timeout /t 2 >nul
set /a DOCKER_WAIT+=2
docker info >nul 2>&1
if not errorlevel 1 (
    exit /b 0
)
if !DOCKER_WAIT! geq 60 (
    exit /b 1
)
echo [INFO] Still waiting for Docker... (!DOCKER_WAIT! seconds^)
goto wait_docker_loop