@echo off
setlocal
cd /d "%~dp0.."
if not defined PORT set PORT=8700
if not defined S7_ARTIFACTS set S7_ARTIFACTS=ai
if not defined LLM_MODE set LLM_MODE=replay
if not defined LLM_PROVIDER set LLM_PROVIDER=claude_cli
if exist ".venv\Scripts\uvicorn.exe" (
  ".venv\Scripts\uvicorn.exe" apps.console.server:app --host 127.0.0.1 --port %PORT%
) else (
  uvicorn apps.console.server:app --host 127.0.0.1 --port %PORT%
)
endlocal
