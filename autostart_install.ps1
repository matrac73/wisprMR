<#
.SYNOPSIS
    Installe ou retire Wispr MR du démarrage Windows.
    Méthode : VBScript dans le dossier Startup utilisateur.
    Plus simple et plus fiable que le Planificateur de tâches pour les apps UI.
.EXAMPLE
    .\autostart_install.ps1          # installe
    .\autostart_install.ps1 -Remove  # retire
#>
param([switch]$Remove)

$projectDir  = $PSScriptRoot
$venvPythonw = Join-Path $projectDir ".venv\Scripts\pythonw.exe"
$sitePkgs    = Join-Path $projectDir ".venv\Lib\site-packages"
$appScript   = Join-Path $projectDir "app.py"
$startupDir  = [Environment]::GetFolderPath("Startup")
$vbsPath     = Join-Path $startupDir "WisprMR.vbs"

# Sur ce poste, le pythonw.exe de la venv (créée depuis Anaconda) re-spawne
# l'interpréteur de base en sous-processus → 2 process pour 1 app. On lance donc
# directement le pythonw de BASE (lu dans pyvenv.cfg) avec PYTHONPATH pointant
# vers le site-packages de la venv → un seul process propre.
$basePythonw = $venvPythonw   # repli par défaut
$cfg = Join-Path $projectDir ".venv\pyvenv.cfg"
if (Test-Path $cfg) {
    $homeLine = (Get-Content $cfg | Where-Object { $_ -match '^\s*home\s*=' } | Select-Object -First 1)
    if ($homeLine) {
        $homeDir = ($homeLine -replace '^\s*home\s*=\s*', '').Trim()
        $candidate = Join-Path $homeDir "pythonw.exe"
        if (Test-Path $candidate) { $basePythonw = $candidate }
    }
}

# ── Suppression ──────────────────────────────────────────────────────────────
if ($Remove) {
    if (Test-Path $vbsPath) {
        Remove-Item $vbsPath -Force
        Write-Host "[OK] Wispr MR retire du demarrage ($vbsPath supprime)."
    } else {
        Write-Host "[INFO] Aucun fichier de demarrage trouve."
    }
    # Supprimer aussi l'ancienne tâche Task Scheduler si elle existe encore
    Unregister-ScheduledTask -TaskName "WisprMR" -Confirm:$false -ErrorAction SilentlyContinue
    exit 0
}

# ── Validation ───────────────────────────────────────────────────────────────
if (-not (Test-Path $sitePkgs)) {
    Write-Error @"
site-packages de la venv introuvable : $sitePkgs
Cree le venv d'abord :
    python -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt
"@
    exit 1
}

# ── Création du VBScript ─────────────────────────────────────────────────────
# WScript.Shell.Run avec windowStyle=0 (invisible) et bWaitOnReturn=False
# → lance pythonw sans fenêtre console, sans bloquer le login Windows.
# PYTHONPATH = site-packages de la venv → un seul process (pas de stub venv).
$vbsContent = @"
Dim WShell
Set WShell = CreateObject("WScript.Shell")
WShell.CurrentDirectory = "$projectDir"
WShell.Environment("PROCESS")("PYTHONPATH") = "$sitePkgs"
WShell.Run """$basePythonw"" ""$appScript"" --profile fast", 0, False
"@

Set-Content -Path $vbsPath -Value $vbsContent -Encoding ASCII

# ── Confirmation ─────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[OK] Wispr MR demarrera automatiquement a chaque connexion Windows."
Write-Host ""
Write-Host "     Fichier     : $vbsPath"
Write-Host "     Executable  : $basePythonw"
Write-Host "     PYTHONPATH  : $sitePkgs"
Write-Host "     Profil      : fast"
Write-Host ""
Write-Host "     Tester maintenant (sans redemarrer) :"
Write-Host "         wscript.exe '$vbsPath'"
Write-Host ""
Write-Host "     Retirer :"
Write-Host "         .\autostart_install.ps1 -Remove"
