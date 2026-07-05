@echo off
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name StankArchivePro --icon assets\app_icon.ico --add-data "assets;assets" main.py
pause
