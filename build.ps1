# Build Mouthpiece.exe (onedir) with PyInstaller.
#   .\build.ps1            -> dist\Mouthpiece\Mouthpiece.exe  (+ dist\Mouthpiece.zip)
# Requires: .venv with requirements.txt + requirements-build.txt installed.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = ".\.venv\Scripts\python.exe"

# tray icon from the same drawing the app uses
& $py -c "from mouthpiece.tray import make_icon; im = make_icon('#FF1A1A', size=256); im.save('mouthpiece.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)]); print('icon ok')"

& $py -m PyInstaller --noconfirm --clean --windowed --name Mouthpiece --icon mouthpiece.ico `
    --add-data "mouthpiece\stage\fonts;mouthpiece\stage\fonts" `
    --collect-all livekit `
    --collect-all sounddevice `
    --hidden-import mouthpiece.stage.baymax --hidden-import mouthpiece.stage.wheatley --hidden-import mouthpiece.stage.kitt `
    --hidden-import keyboard `
    run.pyw

Copy-Item config.example.json dist\Mouthpiece\config.example.json -Force
Copy-Item README.md dist\Mouthpiece\README.md -Force
if (Test-Path dist\Mouthpiece.zip) { Remove-Item dist\Mouthpiece.zip }
Compress-Archive -Path dist\Mouthpiece\* -DestinationPath dist\Mouthpiece.zip
Write-Host "built dist\Mouthpiece\Mouthpiece.exe and dist\Mouthpiece.zip"
