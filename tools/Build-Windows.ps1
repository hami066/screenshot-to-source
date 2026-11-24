param([string]$Python = "python")

$ErrorActionPreference = "Stop"
if (Test-Path -LiteralPath $Python -PathType Leaf) {
    $Python = (Resolve-Path -LiteralPath $Python).Path
}
$project = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $project
try {
    $buildRoot = Join-Path "dist" ([DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss-fff"))
    New-Item -ItemType Directory -Path $buildRoot | Out-Null
    $appIcon = Join-Path (Resolve-Path -LiteralPath $buildRoot).Path "ScreenshotToSource.ico"
    $lensAsset = Join-Path $project "assets/frosted-lens.png"
    & $Python -c 'import sys; from desktop_theme import icon; icon("crop", "#2158a8", 256).save(sys.argv[1], sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])' $appIcon
    if ($LASTEXITCODE -ne 0) { throw "App icon generation failed." }
    & $Python -m PyInstaller --onedir --windowed --noupx --icon $appIcon --name ScreenshotToSource --add-data "${lensAsset}:assets" --collect-all tkinterdnd2 --collect-all pypdfium2_raw --collect-data pypdfium2 --distpath "$buildRoot/portable" --workpath "$buildRoot/build" --specpath $buildRoot app.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }
    & $Python tools/make_release.py "$buildRoot/portable/ScreenshotToSource" $buildRoot
    if ($LASTEXITCODE -ne 0) { throw "Release creation failed." }
} finally {
    Pop-Location
}
