@echo off
setlocal

title STANK Archive Pro Release Builder

echo.
echo ==========================================
echo   STANK Archive Pro Release Builder
echo ==========================================
echo.

echo Installing build tools...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller pillow

if errorlevel 1 (
    echo.
    echo ERROR: Dependency install failed.
    pause
    exit /b 1
)

echo.
echo Cleaning previous builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist release rmdir /s /q release
mkdir release

echo.
echo Building portable app...
python -m PyInstaller --clean --noconfirm --windowed --name "STANK Archive Pro" --icon "assets\app_icon.ico" --add-data "assets;assets" main.py

if errorlevel 1 (
    echo.
    echo ERROR: Build failed.
    pause
    exit /b 1
)

echo.
echo Creating sendable ZIP...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'dist\STANK Archive Pro\*' -DestinationPath 'release\STANK_Archive_Pro_v1.0.0_Portable.zip' -Force"

if errorlevel 1 (
    echo.
    echo ERROR: ZIP creation failed.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo RELEASE READY
echo ==========================================
echo.
echo Send this file to users:
echo release\STANK_Archive_Pro_v1.0.0_Portable.zip
echo.
explorer release
pause
