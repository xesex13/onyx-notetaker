#Requires -Version 5.1
<#
    ONYX installer (Windows / PowerShell).
    Downloads the repo, unpacks it into $OnyxHome, and wires a global `onyx` launcher.
#>

$ErrorActionPreference = "Stop"

$RepoUrl  = "https://github.com/xesex13/onyx-notetaker/archive/refs/heads/main.zip"
$OnyxHome = Join-Path $env:USERPROFILE ".onyx"
$TempZip  = Join-Path ([System.IO.Path]::GetTempPath()) "onyx-notetaker.zip"
$TempExtract = Join-Path ([System.IO.Path]::GetTempPath()) "onyx-notetaker-extract"

Write-Host "Downloading ONYX from $RepoUrl ..."
Invoke-WebRequest -Uri $RepoUrl -OutFile $TempZip

if (Test-Path $TempExtract) {
    Remove-Item -Recurse -Force $TempExtract
}
New-Item -ItemType Directory -Path $TempExtract | Out-Null

Write-Host "Extracting archive ..."
Expand-Archive -Path $TempZip -DestinationPath $TempExtract -Force

$ExtractedRoot = Join-Path $TempExtract "onyx-notetaker-main"

if (Test-Path $OnyxHome) {
    Remove-Item -Recurse -Force $OnyxHome
}
New-Item -ItemType Directory -Path $OnyxHome | Out-Null

Write-Host "Installing to $OnyxHome ..."
Copy-Item -Path (Join-Path $ExtractedRoot "*") -Destination $OnyxHome -Recurse -Force

Remove-Item -Force $TempZip
Remove-Item -Recurse -Force $TempExtract

Write-Host "Installing Python dependencies ..."
python -m pip install --upgrade -e $OnyxHome

$WindowsAppsDir = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps"
$BatPath = Join-Path $WindowsAppsDir "onyx.bat"

$BatContent = "@echo off`r`npython `"$OnyxHome\src\onyx_vault\main.py`" %*`r`n"
Set-Content -Path $BatPath -Value $BatContent -Encoding ASCII

Write-Host "ONYX installed. Run 'onyx' from any new terminal to start."
