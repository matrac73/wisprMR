param(
    [string]$Output = "WisprMR-Install.zip"
)

$ErrorActionPreference = "Stop"
$projectDir = $PSScriptRoot
$stagingRoot = Join-Path $env:TEMP ("wispr_mr_package_" + [guid]::NewGuid().ToString("N"))
$stagingDir = Join-Path $stagingRoot "WisprMR"

New-Item -ItemType Directory -Path $stagingDir | Out-Null

$include = @(
    "A_LIRE_MAC.txt",
    "install.bat",
    "UNINSTALL.bat",
    "INSTALL.command",
    "UNINSTALL.command",
    "INSTALL.py",
    "UNINSTALL.py",
    "README.md",
    "app.py",
    "config.yaml",
    "config_loader.py",
    "dictionary.yaml",
    "requirements.txt",
    "setup.ps1",
    "autostart_install.ps1",
    "restart.ps1",
    "install_macos.sh",
    "build_macos.sh",
    "mobile_server.py",
    "audio",
    "context",
    "hotkey",
    "inject",
    "llm",
    "stt",
    "ui",
    "vocab",
    "tools"
)

foreach ($item in $include) {
    $src = Join-Path $projectDir $item
    if (-not (Test-Path $src)) {
        Write-Warning "Ignore introuvable: $item"
        continue
    }
    $dst = Join-Path $stagingDir $item
    if ((Get-Item $src).PSIsContainer) {
        Copy-Item -Path $src -Destination $dst -Recurse
    } else {
        Copy-Item -Path $src -Destination $dst
    }
}

$outputPath = Join-Path $projectDir $Output
if (Test-Path $outputPath) {
    Remove-Item $outputPath -Force
}

$zipScript = @'
import sys
import zipfile
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        rel = path.relative_to(root.parent).as_posix()
        info = zipfile.ZipInfo(rel)
        info.compress_type = zipfile.ZIP_DEFLATED
        mode = 0o755 if path.suffix in {".command", ".sh"} else 0o644
        info.external_attr = (mode & 0xFFFF) << 16
        with path.open("rb") as fh:
            zf.writestr(info, fh.read())
'@
$zipScriptPath = Join-Path $env:TEMP "wispr_mr_zip_share.py"
Set-Content -Path $zipScriptPath -Value $zipScript -Encoding UTF8
python $zipScriptPath $stagingDir $outputPath
Remove-Item $zipScriptPath -ErrorAction SilentlyContinue
Remove-Item $stagingRoot -Recurse -Force

Write-Host "[OK] Package pret : $outputPath"
Write-Host "Windows : double-cliquer install.bat"
Write-Host "macOS   : double-cliquer INSTALL.command"
