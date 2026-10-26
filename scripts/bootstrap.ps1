param([string]$PythonPath = "")
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$setupTemp = Join-Path $projectRoot "tmp/setup"
New-Item -ItemType Directory -Path $setupTemp -Force | Out-Null
$previousTemp = $env:TEMP
$previousTmp = $env:TMP
try {
    $env:TEMP = $setupTemp
    $env:TMP = $setupTemp
    $venvPython = Join-Path $projectRoot ".venv/Scripts/python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) {
        if ($PythonPath) {
            & $PythonPath -m venv .venv
        } elseif (Get-Command py -ErrorAction SilentlyContinue) {
            & py -3 -m venv .venv
        } else {
            & python -m venv .venv
        }
        if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed. Supply -PythonPath with a working Python 3.11+ executable." }
    }
    & $venvPython -c "import sys; assert sys.version_info >= (3,11), 'Python 3.11 or newer is required'"
    if ($LASTEXITCODE -ne 0) { throw "This virtual environment needs Python 3.11+." }
    & $venvPython -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) { throw "Unable to prepare pip in the project environment." }
    $requirements = if (Test-Path -LiteralPath "requirements-lock.txt") { "requirements-lock.txt" } else { "requirements.txt" }
    & $venvPython -m pip install -r $requirements
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed. Check network access and the pip error above." }
    & $venvPython -m pip install --no-deps -e .
    if ($LASTEXITCODE -ne 0) { throw "Project installation failed." }
    if (-not (Test-Path -LiteralPath ".env")) {
        Copy-Item -LiteralPath ".env.example" -Destination ".env"
    }
    Write-Host "Setup complete. Start the app with: .\scripts\start.ps1"
} finally {
    $env:TEMP = $previousTemp
    $env:TMP = $previousTmp
}
