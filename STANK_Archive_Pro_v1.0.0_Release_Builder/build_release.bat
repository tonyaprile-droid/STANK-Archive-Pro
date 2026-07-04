@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo STANK Archive Pro v1.0.0 Release Builder
echo ========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python was not found.
    echo Install Python from https://www.python.org/downloads/windows/
    echo Make sure "Add python.exe to PATH" is checked.
    pause
    exit /b 1
)

echo Installing/updating build dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist release rmdir /s /q release
mkdir release

echo.
echo Building executable...
pyinstaller --noconfirm --onedir --windowed --name "StankArchivePro" --icon "assets\app_icon.ico" --add-data "assets;assets" main.py

if not exist "dist\StankArchivePro\StankArchivePro.exe" (
    echo.
    echo ERROR: Build failed. The executable was not created.
    pause
    exit /b 1
)

echo.
echo Creating portable release folder...
xcopy "dist\StankArchivePro" "release\STANK Archive Pro" /E /I /Y >nul

copy README_RELEASE.txt "release\STANK Archive Pro\README.txt" >nul

powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'release\STANK Archive Pro' -DestinationPath 'release\STANK_Archive_Pro_v1.0.0_Portable.zip' -Force"

echo.
echo ========================================
echo RELEASE CREATED
echo ========================================
echo Send this file to users:
echo release\STANK_Archive_Pro_v1.0.0_Portable.zip
echo.
pause
