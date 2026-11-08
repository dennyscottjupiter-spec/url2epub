# Builds dist\url2epub.exe (Windows desktop app) from url2epub-desktop.spec.
# Usage: powershell -NoProfile -File build_exe.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python3 -m PyInstaller url2epub-desktop.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Get-Item dist\url2epub.exe | Select-Object FullName, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } }
