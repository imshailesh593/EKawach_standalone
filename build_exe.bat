@echo off
REM Builds dist\EkavachFiller.exe (needs Python + Microsoft Edge on the PC)
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --onefile --windowed --name EkavachFiller ekavach_filler.py
echo.
echo Done. Copy dist\EkavachFiller.exe (and optionally patients.csv) anywhere you like.
pause
