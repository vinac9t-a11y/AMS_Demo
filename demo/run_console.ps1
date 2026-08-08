# Launch the S7 delivery console on Windows PowerShell.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$Port = if ($env:PORT) { $env:PORT } else { "8700" }
$env:S7_ARTIFACTS = if ($env:S7_ARTIFACTS) { $env:S7_ARTIFACTS } else { "ai" }
$env:LLM_MODE = if ($env:LLM_MODE) { $env:LLM_MODE } else { "replay" }
$env:LLM_PROVIDER = if ($env:LLM_PROVIDER) { $env:LLM_PROVIDER } else { "claude_cli" }

$uvicorn = Join-Path $PWD ".venv\Scripts\uvicorn.exe"
if (Test-Path $uvicorn) {
    & $uvicorn "apps.console.server:app" --host 127.0.0.1 --port $Port
    exit $LASTEXITCODE
}

if (Get-Command uvicorn -ErrorAction SilentlyContinue) {
    & uvicorn "apps.console.server:app" --host 127.0.0.1 --port $Port
    exit $LASTEXITCODE
}

Write-Error "uvicorn not found. Create the venv first: python -m venv .venv; .venv\Scripts\python -m pip install -r requirements.txt"
