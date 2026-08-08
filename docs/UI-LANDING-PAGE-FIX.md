# S7 Console landing-page fix

## What was fixed

1. The stage rail has **7** stages, but the desktop CSS was configured for **5** grid columns. That created an unintended second row and made the landing page look mis-rendered. The rail now uses 7 columns on desktop and 7 horizontally scrollable columns on tablet/mobile.
2. Static asset references are rooted (`/styles.css`, `/app.js`, `/vendor/mermaid.min.js`) so they resolve consistently when FastAPI serves the console.
3. The browser now detects `file://` launches and displays a clear instruction instead of silently failing API calls.
4. Added `GET /api/health` for a simple server-vs-UI diagnostic.
5. Added Windows launchers (`demo/run_console.ps1`, `demo/run_console.bat`) and a smoke test.

## Correct test flow

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.\demo\run_console.ps1
```

Then open `http://127.0.0.1:8700/`. Do **not** double-click `apps/console/static/index.html`.

## Validation performed

- Python compile check: passed
- Full pytest suite: **219 passed**
- HTTP smoke check: `/`, `/styles.css`, `/app.js`, Mermaid vendor, `/api/health`, and `/api/run` all returned HTTP 200
