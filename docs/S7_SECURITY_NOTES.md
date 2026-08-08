# S7 Control Centre — Security Notes

Demo-grade software, honestly scoped: single presenter, bound to 127.0.0.1,
no authentication (the role selector is a demonstration device, not an
identity system). What it does enforce, it enforces server-side:

- **Role-based action checks** in `factory/roles.py`, applied by every
  engine action. Frontend button state is a hint; the 403 is the rule.
- **Gate validation server-side** (`factory/gates.py`); no endpoint skips a
  gate, and the demo scenarios drive the same actions.
- **Path safety**: every path segment is validated against
  `^[A-Za-z0-9][A-Za-z0-9._-]*$` and resolved under the run directory;
  a browser-supplied run id cannot escape `artifacts/runs/`.
- **No command execution** from any browser input; the engine writes JSON
  and markdown, nothing else.
- **Append-only decision history**: provenance, activity, approvals and
  amendments are JSONL ledgers with no rewrite path in the store API.
- **Immutable signed versions**: the locked plan and release decisions are
  versioned; correction creates new versions, never edits.
- **No credentials anywhere**: simulation mode makes no network calls; live
  mode is refused by the API. If it is ever enabled, keys stay in `.env`
  per hard rule 3.
- **Customer-safe surface**: no raw source, prompts, or logs; the technical
  evidence view is a sanitised summary (file names, refs, counts).

Known non-goals for the demo: authentication/authorization of real users,
TLS, multi-tenancy, audit-grade clock integrity (ledger order stands in for
trusted time).
