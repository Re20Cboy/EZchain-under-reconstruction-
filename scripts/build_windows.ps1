$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

python scripts/release_gate.py --skip-slow
python scripts/package_app.py --target windows --clean

Write-Host "Windows artifact ready under dist/"
