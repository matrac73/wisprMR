<#
.SYNOPSIS
    Installe Wispr MR de A a Z sur une machine Windows neuve : Python 3.11,
    dependances Python, Ollama + modeles LLM, modele(s) Whisper, demarrage
    automatique. Idempotent : peut etre relance sans risque pour reparer une
    installation partielle.
.EXAMPLE
    .\setup.ps1                       # installation standard (profil 'fast')
    .\setup.ps1 -Profile balanced      # pre-télécharge le modele Whisper 'small'
    .\setup.ps1 -AllModels             # pre-télécharge les 3 modeles Whisper (base/small/turbo)
    .\setup.ps1 -SkipOllama            # n'installe pas Ollama / ne tire pas les modeles LLM
    .\setup.ps1 -NoAutostart           # n'enregistre pas le demarrage automatique Windows
    .\setup.ps1 -Launch                # lance l'app immediatement une fois l'installation terminee
#>
param(
    [ValidateSet("fast", "balanced", "quality")][string]$Profile = "fast",
    [switch]$AllModels,
    [switch]$SkipOllama,
    [switch]$NoAutostart,
    [switch]$Launch
)

$ErrorActionPreference = "Stop"
$projectDir = $PSScriptRoot
$configPath = Join-Path $projectDir "config.yaml"

function Write-Step($msg) { Write-Host ""; Write-Host "=== $msg ===" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Info($msg) { Write-Host "[INFO] $msg" }
function Write-Err($msg)  { Write-Host "[ERREUR] $msg" -ForegroundColor Red }

function Refresh-Path {
    # Recharge le PATH depuis le registre : necessaire dans ce process apres un
    # `winget install` (le PATH du process courant ne voit pas les nouvelles entrees).
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user    = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Install-Python311Direct {
    $version = "3.11.9"
    $installerUrl = "https://www.python.org/ftp/python/$version/python-$version-amd64.exe"
    $installerPath = Join-Path $env:TEMP "python-$version-amd64.exe"

    Write-Info "Telechargement direct de Python $version..."
    Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing

    Write-Info "Installation silencieuse de Python $version pour l'utilisateur courant..."
    $args = @(
        "/quiet",
        "InstallAllUsers=0",
        "PrependPath=0",
        "Include_launcher=0",
        "Include_pip=1",
        "Include_test=0",
        "Shortcuts=0"
    )
    $proc = Start-Process -FilePath $installerPath -ArgumentList $args -Wait -PassThru
    Remove-Item $installerPath -ErrorAction SilentlyContinue

    if ($proc.ExitCode -ne 0) {
        Write-Info "Echec de l'installation directe de Python 3.11 (code $($proc.ExitCode))."
        return $false
    }
    return $true
}

function Has-Conda {
    return [bool](Get-Command conda -ErrorAction SilentlyContinue)
}

function Find-Ollama {
    $cmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $candidates = @(
        (Join-Path $env:LocalAppData "Programs\Ollama\ollama.exe"),
        (Join-Path $env:ProgramFiles "Ollama\ollama.exe")
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    return $null
}

function Get-ConfigProfile {
    if (-not (Test-Path $configPath)) { return $null }
    $line = Get-Content -Path $configPath | Where-Object { $_ -match '^\s*profile\s*:' } | Select-Object -First 1
    if (-not $line) { return $null }
    $value = ($line -replace '^\s*profile\s*:\s*', '').Trim().Trim('"').Trim("'")
    if ($value -in @("fast", "balanced", "quality")) { return $value }
    return $null
}

Write-Host ""
Write-Host "############################################################" -ForegroundColor Magenta
Write-Host "#   Installation de Wispr MR - dictee vocale locale         #" -ForegroundColor Magenta
Write-Host "############################################################" -ForegroundColor Magenta

# ── 0) Pre-requis : winget ────────────────────────────────────────────────────
Write-Step "[0/7] Verification de winget"
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Err "winget est introuvable. Installe 'App Installer' depuis le Microsoft Store puis relance ce script."
    exit 1
}
Write-Ok "winget disponible."

# ── 1) Python 3.11 ─────────────────────────────────────────────────────────────
Write-Step "[1/7] Python 3.11 (dedie a Wispr MR, n'affecte pas ton Python par defaut)"

function Find-Python311 {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try {
            $exe = & py -3.11 -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe) {
                $exe = $exe.Trim()
                if (Test-Path $exe) { return $exe }
            }
        } catch {}
    }
    $candidates = @(
        (Join-Path $env:LocalAppData "Programs\Python\Python311\python.exe"),
        "C:\Python311\python.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    return $null
}

$py311 = Find-Python311
if (-not $py311) {
    Write-Info "Python 3.11 non trouve — installation via winget (silencieux)..."
    winget install --id Python.Python.3.11 -e --source winget --scope user `
        --accept-package-agreements --accept-source-agreements --silent --disable-interactivity
    if ($LASTEXITCODE -ne 0) {
        Write-Info "winget a echoue (code $LASTEXITCODE) — tentative avec l'installeur officiel python.org."
        Install-Python311Direct | Out-Null
    }
    Refresh-Path
    $py311 = Find-Python311
}
if (-not $py311) {
    if (Has-Conda) {
        Write-Info "Python 3.11 systeme introuvable — Conda sera utilise pour creer .venv en Python 3.11."
    } else {
        Write-Err "Python 3.11 introuvable et Conda indisponible. Installe Python 3.11 manuellement puis relance."
        exit 1
    }
} else {
    Write-Ok "Python 3.11 : $py311"
}

# ── 2) Environnement virtuel + dependances ────────────────────────────────────
Write-Step "[2/7] Environnement virtuel (.venv) et dependances Python"

$venvDir      = Join-Path $projectDir ".venv"
$venvPython   = Join-Path $venvDir "Scripts\python.exe"
$isFirstSetup = -not (Test-Path $venvPython)
$profileExplicit = $PSBoundParameters.ContainsKey("Profile")

if (-not (Test-Path $venvPython)) {
    if ($py311) {
        Write-Info "Creation de .venv..."
        & $py311 -m venv $venvDir
    } else {
        Write-Info "Creation de .venv avec Conda (Python 3.11)..."
        & conda create -y -p $venvDir python=3.11 pip
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Echec de la creation du venv."
        exit 1
    }
}
Write-Ok "Venv pret : $venvDir"

Write-Info "Installation des dependances (requirements.txt) — quelques minutes la premiere fois..."
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install -r (Join-Path $projectDir "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Err "Echec de 'pip install -r requirements.txt'. Voir le log ci-dessus."
    exit 1
}
Write-Ok "Dependances Python installees."

if (-not $profileExplicit) {
    $configuredProfile = Get-ConfigProfile
    if ($configuredProfile) {
        $Profile = $configuredProfile
        Write-Info "Profil conserve depuis config.yaml : $Profile"
    }
}

# ── 3) Ollama + modeles LLM ────────────────────────────────────────────────────
if (-not $SkipOllama) {
    Write-Step "[3/7] Ollama (polish LLM local)"

    $ollamaExe = Find-Ollama
    if (-not $ollamaExe) {
        Write-Info "Ollama non trouve — installation via winget (silencieux)..."
        winget install --id Ollama.Ollama -e --source winget `
            --accept-package-agreements --accept-source-agreements --silent
        Refresh-Path
        $ollamaExe = Find-Ollama
        if ($LASTEXITCODE -ne 0 -and -not $ollamaExe) {
            Write-Err "Echec de l'installation d'Ollama via winget (code $LASTEXITCODE)."
            exit 1
        }
    }

    if (-not $ollamaExe) {
        Write-Err "Ollama introuvable meme apres installation. Ouvre une nouvelle session/terminal et relance ce script."
        exit 1
    }
    Write-Ok "Ollama disponible : $ollamaExe"

    # S'assurer que le serveur Ollama repond (l'app Ollama le lance normalement
    # automatiquement apres install / au login ; on force sinon).
    $ollamaUp = $false
    for ($i = 0; $i -lt 5; $i++) {
        try {
            Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 2 | Out-Null
            $ollamaUp = $true
            break
        } catch {
            if ($i -eq 0) {
                Start-Process $ollamaExe -ArgumentList "serve" -WindowStyle Hidden -ErrorAction SilentlyContinue
            }
            Start-Sleep -Seconds 2
        }
    }
    if ($ollamaUp) {
        Write-Ok "Serveur Ollama joignable (http://localhost:11434)."
    } else {
        Write-Info "Serveur Ollama pas encore joignable — les modeles seront quand meme tires, Wispr MR retentera au demarrage."
    }

    # Modeles utilises par Wispr MR : lus depuis config.yaml (source de verite),
    # avec repli sur les valeurs par defaut si le parsing echoue.
    # (here-string a quotes simples : contenu 100% litteral, les valeurs
    # dynamiques passent en argv pour eviter tout souci d'interpolation PS.)
    $pyGetModels = @'
import sys
sys.path.insert(0, sys.argv[1])
try:
    from config_loader import load_config
    cfg = load_config(path=sys.argv[2])
    names = {cfg.llm.model, cfg.llm.fallback_model}
    print("\n".join(n for n in names if n))
except Exception:
    print("qwen2.5:3b-instruct-q4_K_M")
    print("qwen2.5:1.5b-instruct-q4_K_M")
'@
    $pyGetModelsPath = Join-Path $env:TEMP "wispr_mr_get_models.py"
    Set-Content -Path $pyGetModelsPath -Value $pyGetModels -Encoding UTF8
    $models = & $venvPython $pyGetModelsPath $projectDir $configPath
    Remove-Item $pyGetModelsPath -ErrorAction SilentlyContinue
    if (-not $models) {
        $models = @("qwen2.5:3b-instruct-q4_K_M", "qwen2.5:1.5b-instruct-q4_K_M")
    }
    foreach ($model in $models) {
        $model = $model.Trim()
        if (-not $model) { continue }
        Write-Info "ollama pull $model ..."
        $pullOut = Join-Path $env:TEMP ("wispr_mr_ollama_pull_" + ($model -replace "[^A-Za-z0-9_.-]", "_") + ".out")
        $pullErr = Join-Path $env:TEMP ("wispr_mr_ollama_pull_" + ($model -replace "[^A-Za-z0-9_.-]", "_") + ".err")
        $pullProc = Start-Process -FilePath $ollamaExe -ArgumentList @("pull", $model) `
            -Wait -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput $pullOut -RedirectStandardError $pullErr
        if ($pullProc.ExitCode -ne 0) {
            Write-Info "Echec du pull pour '$model' (reseau ? Ollama pas encore pret ?) — tu pourras relancer 'ollama pull $model' plus tard."
            if (Test-Path $pullErr) {
                Get-Content -Tail 10 -Path $pullErr | ForEach-Object { Write-Info $_ }
            }
        } else {
            Write-Ok "Modele Ollama pret : $model"
        }
        Remove-Item $pullOut, $pullErr -ErrorAction SilentlyContinue
    }
    Write-Ok "Modeles LLM prets."
} else {
    Write-Step "[3/7] Ollama (ignore : -SkipOllama)"
}

# ── 4) Modele(s) Whisper ───────────────────────────────────────────────────────
Write-Step "[4/7] Telechargement du/des modele(s) Whisper (Hugging Face, ~1x)"

$profileArg = $Profile
$allModelsArg = "0"
if ($AllModels) { $allModelsArg = "1" }

$dlScript = @'
import sys
sys.path.insert(0, sys.argv[1])
from config_loader import PROFILES
from stt.transcriber import _resolve_model_name
from faster_whisper import WhisperModel

all_models = sys.argv[2] == "1"
profile = sys.argv[3]

if all_models:
    names = sorted({p["stt"]["model"] for p in PROFILES.values()})
else:
    names = [PROFILES[profile]["stt"]["model"]]

for name in names:
    real = _resolve_model_name(name)
    print("[whisper] telechargement de '" + real + "'...", flush=True)
    WhisperModel(real, device="cpu", compute_type="int8", cpu_threads=1, num_workers=1)
    print("[whisper] '" + real + "' pret.", flush=True)
'@
$dlScriptPath = Join-Path $env:TEMP "wispr_mr_dl_whisper.py"
Set-Content -Path $dlScriptPath -Value $dlScript -Encoding UTF8

$whisperOut = Join-Path $env:TEMP "wispr_mr_whisper_download.out"
$whisperErr = Join-Path $env:TEMP "wispr_mr_whisper_download.err"
$whisperProc = Start-Process -FilePath $venvPython -ArgumentList @($dlScriptPath, $projectDir, $allModelsArg, $profileArg) `
    -Wait -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $whisperOut -RedirectStandardError $whisperErr
if (Test-Path $whisperOut) {
    Get-Content -Path $whisperOut | ForEach-Object { Write-Info $_ }
}
if ($whisperProc.ExitCode -ne 0) {
    Write-Info "Echec du telechargement du modele Whisper (reseau ?) — il sera re-tente au premier lancement de l'app."
    if (Test-Path $whisperErr) {
        Get-Content -Tail 10 -Path $whisperErr | ForEach-Object { Write-Info $_ }
    }
} else {
    Write-Ok "Modele(s) Whisper prets."
}
Remove-Item $dlScriptPath, $whisperOut, $whisperErr -ErrorAction SilentlyContinue

# ── 5) Config : profil de depart ──────────────────────────────────────────────
Write-Step "[5/7] Profil de config.yaml"
if ($isFirstSetup -or $profileExplicit) {
    $pySetProfile = @'
import sys
sys.path.insert(0, sys.argv[1])
from config_loader import update_config_file
update_config_file({"profile": sys.argv[3]}, path=sys.argv[2])
'@
    $pySetProfilePath = Join-Path $env:TEMP "wispr_mr_set_profile.py"
    Set-Content -Path $pySetProfilePath -Value $pySetProfile -Encoding UTF8
    & $venvPython $pySetProfilePath $projectDir $configPath $Profile
    Remove-Item $pySetProfilePath -ErrorAction SilentlyContinue
    Write-Ok "Profil actif : $Profile"
} else {
    Write-Info "config.yaml existant conserve tel quel (relance sans -Profile explicite)."
}

# ── 6) Demarrage automatique Windows ──────────────────────────────────────────
if (-not $NoAutostart) {
    Write-Step "[6/7] Enregistrement du demarrage automatique Windows"
    & (Join-Path $projectDir "autostart_install.ps1") -Profile $Profile
} else {
    Write-Step "[6/7] Demarrage automatique (ignore : -NoAutostart)"
}

# ── 7) Recapitulatif ───────────────────────────────────────────────────────────
Write-Step "[7/7] Installation terminee"
Write-Host ""
Write-Ok  "Wispr MR est installe."
Write-Info "Profil actif    : $Profile"
Write-Info "Venv             : $venvDir"
Write-Info "Hotkey           : maintenir Ctrl+Espace pour dicter"
Write-Info "Demarrage auto   : $(if ($NoAutostart) { 'non enregistre' } else { 'active a la prochaine connexion Windows' })"
Write-Host ""
Write-Info "Pour lancer maintenant sans redemarrer Windows : .\restart.ps1"
Write-Info "Pour changer de profil plus tard               : .\restart.ps1 -Profile balanced"
Write-Info "Pour desinstaller le demarrage automatique      : .\autostart_install.ps1 -Remove"
Write-Host ""

if ($Launch) {
    Write-Info "Lancement de Wispr MR..."
    & (Join-Path $projectDir "restart.ps1") -Profile $Profile
}
