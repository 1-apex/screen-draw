# Builds the standalone Windows app into dist\ScreenDraw\ScreenDraw.exe
# Exit codes are checked explicitly: with ErrorActionPreference=Stop, Windows
# PowerShell 5.1 aborts on any stderr text from native tools, even warnings.
Set-Location $PSScriptRoot

python -m pip install --quiet -r requirements.txt -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

python tools\make_icon.py assets\icon.ico
if ($LASTEXITCODE -ne 0) { throw "icon generation failed" }

# --onedir starts instantly; --onefile would unpack itself on every launch.
python -m PyInstaller --noconfirm --clean --windowed --onedir `
    --name ScreenDraw --icon assets\icon.ico screen_draw.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# PySide6 bundles Qt parts this app never touches (QML/Quick, PDF, software
# OpenGL, TLS, translations). Dropping them roughly halves the install size.
$qt = "dist\ScreenDraw\_internal\PySide6"
$unused = @(
    "$qt\opengl32sw.dll", "$qt\Qt6Quick.dll", "$qt\Qt6Qml*.dll", "$qt\Qt6Pdf.dll",
    "$qt\Qt6VirtualKeyboard*.dll", "$qt\translations",
    "$qt\plugins\platforminputcontexts", "$qt\plugins\imageformats\qpdf.dll",
    "$qt\plugins\tls", "$qt\plugins\networkinformation",
    "dist\ScreenDraw\_internal\libssl-3-x64.dll", "dist\ScreenDraw\_internal\libcrypto-3-x64.dll"
)
Remove-Item $unused -Recurse -Force -ErrorAction SilentlyContinue
$mb = (Get-ChildItem dist\ScreenDraw -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("Trimmed build: {0:N0} MB" -f $mb)

Write-Host "Built dist\ScreenDraw\ScreenDraw.exe - run .\install.ps1 to install it."
