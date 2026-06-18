<#
.SYNOPSIS
    Redemarre Wispr MR proprement.
    1) Arrete toutes les instances en cours (l'ancien code charge en memoire).
    2) Reinstalle le demarrage automatique Windows (profil 'fast').
    3) Relance l'app immediatement avec le code a jour.

    A lancer apres une mise a jour du code pour appliquer les changements.
.EXAMPLE
    .\restart.ps1
    .\restart.ps1 -Profile balanced   # surcharge le profil de lancement
#>
param([ValidateSet("fast", "balanced", "quality")][string]$Profile = "fast")

$ErrorActionPreference = "Stop"
$projectDir = $PSScriptRoot
$appScript  = Join-Path $projectDir "app.py"
$startupDir = [Environment]::GetFolderPath("Startup")
$vbsPath    = Join-Path $startupDir "WisprMR.vbs"

Write-Host ""
Write-Host "=== Wispr MR - redemarrage ==="
Write-Host ""

# ── 1) Arret des instances en cours ──────────────────────────────────────────
Write-Host "[1/3] Arret des instances Wispr en cours..."
$wispr = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*app.py*" -and $_.CommandLine -like "*$projectDir*" }

$killed = 0
foreach ($p in $wispr) {
    try {
        Stop-Process -Id $p.ProcessId -Force
        $killed++
    } catch {
        Write-Warning "      Impossible d'arreter le PID $($p.ProcessId): $_"
    }
}
if ($killed -gt 0) {
    Write-Host "      $killed instance(s) arretee(s)."
    # Laisser le mutex 'instance unique' et l'audio se liberer avant de relancer.
    Start-Sleep -Milliseconds 800
} else {
    Write-Host "      Aucune instance en cours."
}

# ── 2) Reinstallation du demarrage automatique ───────────────────────────────
Write-Host "[2/3] (Re)installation du demarrage automatique..."
& (Join-Path $projectDir "autostart_install.ps1")

# ── 3) Lancement immediat avec le code a jour ────────────────────────────────
Write-Host "[3/3] Lancement de Wispr MR (profil '$Profile')..."
if (Test-Path $vbsPath) {
    # Reutilise le VBScript du Startup (lance pythonw sans fenetre, profil 'fast').
    if ($Profile -eq "fast") {
        Start-Process "wscript.exe" -ArgumentList "`"$vbsPath`""
    } else {
        # Profil different demande : lancer directement avec la surcharge CLI.
        $pythonw = Join-Path $projectDir ".venv\Scripts\pythonw.exe"
        Start-Process $pythonw -ArgumentList "`"$appScript`"", "--profile", $Profile -WorkingDirectory $projectDir
    }
} else {
    $pythonw = Join-Path $projectDir ".venv\Scripts\pythonw.exe"
    Start-Process $pythonw -ArgumentList "`"$appScript`"", "--profile", $Profile -WorkingDirectory $projectDir
}

Write-Host ""
Write-Host "[OK] Wispr MR redemarre. La pastille doit reapparaitre en bas de l'ecran."
Write-Host "     Maintenez Ctrl+Espace pour dicter."
Write-Host ""
