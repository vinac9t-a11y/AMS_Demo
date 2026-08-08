"""Record the upstream artifacts via the claude_cli provider.

Usage:
    LLM_MODE=record LLM_PROVIDER=claude_cli .venv/bin/python demo/record_run.py

Record mode always calls live and refreshes the committed recordings, so a
weak result is re-rolled by simply running again. Verify afterwards with:
    LLM_MODE=replay .venv/bin/python demo/record_run.py
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from s7_delivery import generate  # noqa: E402
from s7_delivery.pipeline import load_epic  # noqa: E402


def main() -> int:
    document = load_epic()
    epic = document.epic
    print(f"epic: {epic.id} — {epic.title}")

    a = generate.assessment(epic)
    print(f"\nassessment: {len(a.tasks)} tasks, provenance={a.provenance.value}")
    for t in a.tasks:
        flag = " [EXTERNAL]" if t.blocked_by_external else ""
        print(f"  {t.id} [{t.stream.value}/{t.coverage.value}] {t.estimate_days}d {t.summary}{flag}")
    print(f"  coverage breakdown (effort-weighted): "
          f"{ {c.value: round(v * 100) for c, v in a.coverage_breakdown().items()} }")
    print(f"  integration: {a.integration_note}")

    designs = generate.design(epic, a)
    print(f"\ndesign: {[f'{d.id} ({d.kind})' for d in designs]}")
    for d in designs:
        print(f"  {d.id}: {len(d.source.splitlines())} mermaid lines — {d.title}")

    stories = generate.stories(epic, a)
    print(f"\nstories: {len(stories)}")
    agentic_found = False
    for s in stories:
        lane = [t.id for t in s.tasks if t.runs_in_downstream_lane]
        agentic_found = agentic_found or bool(lane)
        print(f"  {s.id}: {s.title}")
        print(f"    ACs={len(s.acceptance)} unsatisfied={list(s.unsatisfied())} "
              f"tasks={len(s.tasks)} agentic={lane} assumptions={len(s.assumptions)}")
    if not agentic_found:
        print("\nFATAL: no agentic task for the downstream lane — re-record stories",
              file=sys.stderr)
        return 1
    print("\nOK — upstream artifacts complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
