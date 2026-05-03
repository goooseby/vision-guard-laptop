$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if ($env:VISION_GUARD_PYTHON) {
    & $env:VISION_GUARD_PYTHON -m vision_guard
    exit $LASTEXITCODE
}

$Conda = Get-Command conda -ErrorAction SilentlyContinue
if ($Conda) {
    conda run -n vision-guard python -m vision_guard
    exit $LASTEXITCODE
}

python -m vision_guard
