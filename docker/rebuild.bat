@echo off
REM Armada Docker Rebuild Script for Windows
REM Run this script from the docker\ directory or the project root

echo.
echo ========================================
echo   Armada Docker Rebuild
echo ========================================
echo.

REM Get script directory
set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."

REM If running from project root, use current directory
if exist "docker\Dockerfile" (
    set "PROJECT_ROOT=%CD%"
)

cd /d "%PROJECT_ROOT%"

REM Rebuild the image (no cache to ensure fresh build)
echo Rebuilding Docker image...
docker build --no-cache -t armada:latest -f docker/Dockerfile .

echo.
echo ========================================
echo   Rebuild complete!
echo.
echo   To start: cd docker ^&^& docker compose up -d
echo   Access at: http://localhost:5000
echo ========================================
echo.

pause
