# Builds dist\EkavachFiller.exe and installer\output\EkavachFiller_Setup_<ver>.exe
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
Get-Process EkavachFiller -ErrorAction SilentlyContinue | Stop-Process -Force
cmd /c "python -m pip install --quiet -r requirements.txt cryptography pyinstaller >nul 2>&1"
cmd /c "python -m PyInstaller --noconfirm --onefile --windowed --name EkavachFiller --hidden-import cryptography.hazmat.primitives.asymmetric.ed25519 ekavach_filler.py > build.log 2>&1"
if (-not (Test-Path dist\EkavachFiller.exe)) { throw "PyInstaller failed - see build.log" }
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found. Install: winget install JRSoftware.InnoSetup" }
$ver = (python -c "import licensing;print(licensing.APP_VERSION)").Trim()
Write-Host "Building version $ver"
& $iscc "/DAppVer=$ver" installer\installer.iss
Get-ChildItem installer\output | Select-Object Name,Length,LastWriteTime
