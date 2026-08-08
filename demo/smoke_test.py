"""Small build/smoke test for the S7 console.

Usage while the server is running:
    python demo/smoke_test.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8700").rstrip("/")
PATHS = ["/", "/styles.css", "/app.js", "/vendor/mermaid.min.js", "/api/health", "/api/run"]

for path in PATHS:
    with urllib.request.urlopen(BASE + path, timeout=5) as response:
        body = response.read()
        print(f"OK  {response.status:3}  {path:28} {response.headers.get('content-type','')} {len(body)} bytes")

with urllib.request.urlopen(BASE + "/api/health", timeout=5) as response:
    health = json.loads(response.read())
assert health["status"] == "ok"
print("Console smoke test passed.")
