"""Record the downstream lane for the first AGENTIC frontend task.

Usage:
    LLM_MODE=record LLM_PROVIDER=claude_cli .venv/bin/python demo/record_downstream.py

The upstream calls replay from Task 2's recordings; only the three downstream
agent calls (developer, tester, reviewer) go live. Verify afterwards with:
    LLM_MODE=replay LLM_PROVIDER=claude_cli .venv/bin/python demo/record_downstream.py
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from s7_delivery import generate  # noqa: E402
from s7_delivery.downstream import run_lane  # noqa: E402
from s7_delivery.models import Stream  # noqa: E402
from s7_delivery.pipeline import load_epic  # noqa: E402


def main() -> int:
    # Pin the upstream to the committed recordings regardless of the outer
    # mode: record mode refreshes every call it touches, and re-rolling the
    # assessment/stories here would silently invalidate Task 2's artifacts
    # (and change which task this script picks). Only the downstream agent
    # calls run in the outer mode.
    outer_mode = os.environ.get("LLM_MODE", "replay")
    os.environ["LLM_MODE"] = "replay"
    epic = load_epic().epic
    a = generate.assessment(epic)
    stories = generate.stories(epic, a)
    os.environ["LLM_MODE"] = outer_mode

    picks = [
        (s, t)
        for s in stories
        for t in s.tasks
        if t.runs_in_downstream_lane and t.stream is Stream.FRONTEND
    ]
    if not picks:
        picks = [(s, t) for s in stories for t in s.tasks if t.runs_in_downstream_lane]
    if not picks:
        print("FATAL: no agentic task in the recorded stories", file=sys.stderr)
        return 1

    story, task = picks[0]
    print(f"lane task: {task.id} [{task.stream.value}] {task.summary}")
    print(f"satisfies: {list(task.satisfies)}\n")

    root = REPO_ROOT / "artifacts" / epic.id / "downstream"
    result = run_lane(story, task, root=root)

    print(f"ok={result.ok}")
    print(f"app: {result.app_dir}")
    print(f"verdict: {result.review.get('verdict')}")
    for c in result.review.get("criteria", []):
        print(f"  {c.get('id')}: {'met' if c.get('met') else 'NOT MET'} — {c.get('note', '')}")
    print("\npytest output:")
    print(result.test_output)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
