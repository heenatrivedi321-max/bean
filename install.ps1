# bean installer — Windows (PowerShell 5.1+, run from any shell)
#
#   curl -fsSL https://raw.githubusercontent.com/heenatrivedi321-max/bean/main/install.ps1 | powershell -Command -
#
# Or from a clone:  powershell -ExecutionPolicy Bypass -File .\install.ps1
#
# Checks and installs, in order:
#   1. Python 3.12 + bean's deps (rich, requests) — via uv, automatically
#   2. Ollama (the local model runtime) — via winget, automatically
#   3. Starts the Ollama desktop app, creates the `bean` command, launches bean
#
#   -DryRun   print what would be installed without touching anything
#   -NoRun    install everything but don't launch bean
param(
  [switch]$DryRun,
  [switch]$NoRun
)
$ErrorActionPreference = "Stop"

function Say($m) { Write-Host "bean -> $m" -ForegroundColor Yellow }
function Ok($m)  { Write-Host "bean -> $m" -ForegroundColor Green }

$Repo    = "https://github.com/heenatrivedi321-max/bean.git"
$UserHome = $env:USERPROFILE
$BeanDir = Join-Path $UserHome ".bean"
$BeanFile = Join-Path $BeanDir "bean.py"
$BinDir  = Join-Path $BeanDir "bin"

if ($DryRun) { Say "dry run - nothing will be installed or changed" }

# ---------------------------------------------------------------- sources

if (!(Test-Path $BeanFile)) {
  Say "bean isn't here yet - grabbing it from $Repo"
  if (-not $DryRun) {
    if (Test-Path $BeanDir) { Remove-Item -Recurse -Force $BeanDir }
    git clone --depth 1 $Repo $BeanDir
  } else {
    Write-Host "  would run: git clone --depth 1 $Repo $BeanDir"
  }
}

# --------------------------------------------------------- python + deps

$Py = $null
if (Get-Command uv -ErrorAction SilentlyContinue) {
  $Py = "uv run --quiet --python 3.12 --with rich --with requests python"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
  if ($LASTEXITCODE -eq 0) {
    if (-not $DryRun) { python -m pip install --user --quiet rich requests }
    $Py = "python"
  }
}
if (-not $Py) {
  Say "no Python or uv found - installing uv (it brings its own Python)"
  if (-not $DryRun) {
    winget install --id astral-sh.uv -e --accept-source-agreements --accept-package-agreements | Out-Null
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + $env:Path
    $Py = "uv run --quiet --python 3.12 --with rich --with requests python"
  } else {
    Write-Host "  would run: winget install --id astral-sh.uv -e"
    $Py = "uv run --quiet --python 3.12 --with rich --with requests python"
  }
}

# ------------------------------------------------------------------ ollama

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
  Say "installing Ollama - the engine that runs your local models"
  if (-not $DryRun) {
    winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements | Out-Null
  } else {
    Write-Host "  would run: winget install --id Ollama.Ollama -e"
  }
}

# -------------------------------------------- start the Ollama desktop app

# The app (and its local engine on port 11434) is launched by bean itself
# during handoff — just make sure it can open. Nothing to do here.
if (-not $DryRun) {
  Say "the Ollama desktop app will open when bean hands off"
}

# ------------------------------------------------------ the 'bean' command

if (-not $DryRun) {
  New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
  $CmdPath = Join-Path $BinDir "bean.cmd"
  $CmdBody = "@echo off`r`ncd /d `"$BeanDir`"`r`n$Py bean.py %*`r`n"
  Set-Content -Path $CmdPath -Value $CmdBody -Encoding ASCII
  Ok "installed the 'bean' command ($CmdPath)"

  $UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
  if ($UserPath -notlike "*$BinDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$UserPath;$BinDir", "User")
    Say "added $BinDir to your PATH - new terminals will have 'bean'"
  }
}

Ok "everything's in place"
if ($NoRun -or $DryRun) { exit 0 }

Say "opening bean"
Push-Location $BeanDir
& $Py $BeanFile
Pop-Location