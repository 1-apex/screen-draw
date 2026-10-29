# Installs the built app for the current user (no admin needed):
#   - copies dist\ScreenDraw to %LOCALAPPDATA%\Programs\ScreenDraw
#   - adds a "Screen Draw" Start Menu shortcut (right-click it to pin to taskbar)
# Run with -Uninstall to remove it again, including the "Start with Windows" entry.
param([switch]$Uninstall)
$ErrorActionPreference = "Stop"

$source = Join-Path $PSScriptRoot "dist\ScreenDraw"
$target = Join-Path $env:LOCALAPPDATA "Programs\ScreenDraw"
$shortcut = Join-Path ([Environment]::GetFolderPath("Programs")) "Screen Draw.lnk"

# Close a running copy so its files can be replaced.
Get-Process ScreenDraw -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 300

if ($Uninstall) {
    if (Test-Path $target) { Remove-Item $target -Recurse -Force }
    if (Test-Path $shortcut) { Remove-Item $shortcut -Force }
    Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" `
        -Name "Screen Draw" -ErrorAction SilentlyContinue
    Write-Host "Screen Draw uninstalled."
    return
}

if (-not (Test-Path (Join-Path $source "ScreenDraw.exe"))) {
    throw "No build found. Run .\build.ps1 first."
}

if (Test-Path $target) { Remove-Item $target -Recurse -Force }
Copy-Item $source $target -Recurse

$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($shortcut)
$link.TargetPath = Join-Path $target "ScreenDraw.exe"
$link.WorkingDirectory = $target
$link.Description = "Draw on top of anything on your screen"
$link.Save()

Write-Host "Installed to $target"
Write-Host "Start Menu shortcut: $shortcut"
