param([int]$Port = 8501)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$venvPython = Join-Path $projectRoot ".venv/Scripts/python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Run .\scripts\bootstrap.ps1 first."
}
$env:LANGSMITH_TRACING = "false"
$env:LANGCHAIN_TRACING_V2 = "false"
& $venvPython -m streamlit run app.py --server.address 127.0.0.1 --server.port $Port --browser.gatherUsageStats false
exit $LASTEXITCODE
