#!/usr/bin/env python3
"""Epic → stories, with a real model — the Sprint 3 spike for one beat.

Small standalone demo of the story-breakdown stage: reads `crs/EPIC-S7-001.md`,
asks the configured model to break it into user stories, validates the result
into `s7_delivery.models.UserStory` objects, and renders a provenance-badged
HTML page.

    demo/epic_to_stories_demo.py            # replay (offline, committed recording)
    LLM_MODE=record demo/epic_to_stories_demo.py   # refresh the recording (needs a key)

Output: `s7_delivery/out/epic-to-stories.html` (gitignored, regenerated per run)
plus a terminal summary.

Two things this deliberately is NOT:

- It is not the pipeline. `s7_delivery.pipeline` enforces that story breakdown
  stays locked until the human review gate approves the design, and this script
  does not route around that for the console — it is a bench demo of the
  breakdown beat alone, and both the page and the terminal output say the gate
  is taken as approved. When Sprint 3 wires `build_state` to real calls, the
  prompt below moves there and this script keeps working as its bench harness.
- It is not staged output. The call goes through `common.llm.complete()` like
  every other model call in the repo: `record` makes one live call and commits
  the recording under `s7_delivery/cache/llm/`, and the default `replay` mode
  reproduces it offline with provenance `REPLAYED_AI` — genuine AI output,
  recorded earlier, per hard rule 5.
"""

from __future__ import annotations

import html
import os
import sys
import webbrowser
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from common.llm import LLMError, complete, parse_json_response  # noqa: E402
from common.prompt import PromptLayers  # noqa: E402
from s7_delivery.models import (  # noqa: E402
    AcceptanceCriterion,
    Provenance,
    Stream,
    UserStory,
)
from s7_delivery.pipeline import load_epic  # noqa: E402

OUT_PATH = REPO_ROOT / "s7_delivery" / "out" / "epic-to-stories.html"

# One recording per epic. The prompt text is hashed into the cache key by
# common.llm, so editing the layers below invalidates the recording loudly
# (missing-recording error) instead of silently replaying a stale answer.
CACHE_KEY = "s7_story_breakdown:EPIC-S7-001"

RULES = (
    "You are an AI delivery assistant for MapleSure Insurance, a fictional "
    "insurer in a tabletop exercise. All data is synthetic. Answer with "
    "structured JSON only when asked for JSON, and never invent facts the "
    "input does not support."
)

ROLE = (
    "Your role in this stage is the delivery lead's story breakdown: turn an "
    "epic that has already passed design review into a small set of "
    "independently deliverable user stories a maintenance team can execute. "
    "Stories must jointly cover the epic's committed scope — no story for "
    "work the epic defers, and no scope silently dropped. Where the epic "
    "lists open questions, do NOT answer them yourself: carry the dependency "
    "as an explicit assumption on the story it affects."
)

TASK = """Break this epic into user stories. Return JSON exactly matching:
{
  "stories": [
    {
      "id": "S7-001-<n>, numbered from 1 in delivery order",
      "title": "<short imperative title>",
      "narrative": "As a <actor>, I want <capability>, so that <outcome>",
      "acceptance": [
        {"id": "AC-<n>", "text": "Given <context>, when <action>, then <observable result>"}
      ],
      "streams": ["subset of: frontend, api, database, document_intake, system_of_record, test"],
      "estimate_points": <integer story points, 1/2/3/5/8/13>,
      "assumptions": ["<only what rests on the epic's own open questions; empty list if none>"]
    }
  ]
}

Between three and six stories. Every acceptance criterion must be testable as
written — an observable behaviour, not an intention."""


def _provenance() -> Provenance:
    mode = os.environ.get("LLM_MODE", "replay").lower()
    return Provenance.LIVE_AI if mode in {"live", "record"} else Provenance.REPLAYED_AI


def break_down_epic() -> tuple[list[UserStory], dict]:
    """One model call: the epic body in, validated stories out."""
    document = load_epic()
    layers = PromptLayers(
        rules=RULES,
        role=ROLE,
        ref=f"The epic, verbatim:\n\n{document.epic.body}",
        task=TASK,
    )
    usage: dict = {}
    response = complete(layers, json_mode=True, cache_key=CACHE_KEY, usage_out=usage)
    data = parse_json_response(response, required_keys={"stories"})

    raw_stories = data["stories"]
    if not isinstance(raw_stories, list) or not 3 <= len(raw_stories) <= 6:
        raise LLMError(f"expected 3-6 stories, got {raw_stories!r:.80}")

    provenance = _provenance()
    stories: list[UserStory] = []
    seen: set[str] = set()
    for raw in raw_stories:
        story_id = str(raw["id"])
        if story_id in seen:
            raise LLMError(f"duplicate story id {story_id}")
        seen.add(story_id)
        acceptance = tuple(
            AcceptanceCriterion(id=str(c["id"]), text=str(c["text"])) for c in raw["acceptance"]
        )
        if not acceptance:
            raise LLMError(f"story {story_id} has no acceptance criteria")
        try:
            streams = tuple(Stream(s) for s in raw["streams"])
        except ValueError as exc:
            raise LLMError(f"story {story_id} names an unknown stream: {exc}") from exc
        if not streams:
            raise LLMError(f"story {story_id} has no streams")
        points = raw["estimate_points"]
        if not isinstance(points, int) or points < 1:
            raise LLMError(
                f"story {story_id} estimate_points must be a positive int, got {points!r}"
            )
        stories.append(
            UserStory(
                id=story_id,
                title=str(raw["title"]),
                narrative=str(raw["narrative"]),
                acceptance=acceptance,
                streams=streams,
                estimate_points=points,
                provenance=provenance,
                epic_id=document.epic.id,
                assumptions=tuple(str(a) for a in raw.get("assumptions", [])),
            )
        )
    return stories, usage


STREAM_LABELS = {
    "frontend": "Frontend",
    "api": "API / Services",
    "database": "Database",
    "document_intake": "Document intake",
    "system_of_record": "System of record",
    "test": "Test",
}

BADGE_LABELS = {
    Provenance.LIVE_AI: ("LIVE AI", "#4fae7c"),
    Provenance.REPLAYED_AI: ("REPLAYED AI", "#4fae7c"),
    Provenance.STAGED: ("STAGED", "#d9a13c"),
    Provenance.HUMAN: ("HUMAN", "#9aa7b8"),
}


def esc(text: object) -> str:
    return html.escape(str(text))


def render_html(stories: list[UserStory], usage: dict) -> str:
    document = load_epic()
    badge, badge_color = BADGE_LABELS[stories[0].provenance]
    total = sum(s.estimate_points for s in stories)
    tokens = ""
    if usage.get("input_tokens"):
        tokens = f"{usage['input_tokens']:,} tokens in · {usage.get('output_tokens', 0):,} out"

    cards = []
    for story in stories:
        chips = "".join(
            f'<span class="chip">{esc(STREAM_LABELS.get(s.value, s.value))}</span>'
            for s in story.streams
        )
        criteria = "".join(
            f"<li><b>{esc(c.id)}</b> — {esc(c.text)}</li>" for c in story.acceptance
        )
        assumptions = ""
        if story.assumptions:
            items = "".join(f"<li>{esc(a)}</li>" for a in story.assumptions)
            assumptions = (
                '<div class="assume"><b>Assumptions carried, not answered</b>'
                f"<ul>{items}</ul></div>"
            )
        cards.append(f"""
    <article class="card">
      <header><span class="sid">{esc(story.id)}</span>
        <span class="badge" style="background:{badge_color}22;color:{badge_color}">{badge}</span>
        <span class="pts">{story.estimate_points} pts</span></header>
      <h2>{esc(story.title)}</h2>
      <p class="narrative">{esc(story.narrative)}</p>
      <div class="chips">{chips}</div>
      <ul class="criteria">{criteria}</ul>
      {assumptions}
    </article>""")

    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Epic → Stories — {esc(document.epic.id)}</title>
<style>
  :root {{ --bg:#0e1116; --card:#171c24; --ink:#eef2f7; --soft:#9aa7b8;
           --line:#2a3341; --accent:#e04f4f; }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:var(--bg); color:var(--ink); padding:40px clamp(16px,5vw,64px);
          font-family:"Avenir Next","Segoe UI",system-ui,sans-serif; }}
  .head {{ max-width:960px; margin:0 auto 28px; }}
  .kicker {{ font-size:12px; letter-spacing:.16em; text-transform:uppercase;
             color:var(--accent); font-weight:600; }}
  h1 {{ font-size:clamp(22px,3vw,34px); margin:6px 0 10px; }}
  .meta {{ color:var(--soft); font-size:14px; line-height:1.6; }}
  .grid {{ max-width:960px; margin:0 auto; display:grid; gap:16px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
           padding:18px 20px; }}
  .card header {{ display:flex; align-items:center; gap:10px; margin-bottom:8px; }}
  .sid {{ font-family:ui-monospace,Menlo,monospace; color:var(--accent); font-size:13px; }}
  .badge {{ font-size:10.5px; font-weight:700; letter-spacing:.05em; padding:2px 8px;
            border-radius:999px; }}
  .pts {{ margin-left:auto; color:var(--soft); font-size:13px; }}
  h2 {{ font-size:18px; margin-bottom:4px; }}
  .narrative {{ color:var(--soft); font-size:14px; margin-bottom:10px; }}
  .chips {{ display:flex; gap:6px; flex-wrap:wrap; margin-bottom:10px; }}
  .chip {{ font-size:11px; padding:2px 9px; border-radius:999px; background:#1d232e;
           border:1px solid var(--line); color:var(--soft); }}
  .criteria {{ list-style:none; }}
  .criteria li {{ font-size:13.5px; line-height:1.5; padding:6px 0;
                  border-top:1px solid var(--line); }}
  .criteria b {{ color:var(--ink); font-family:ui-monospace,Menlo,monospace; font-size:12px; }}
  .assume {{ margin-top:10px; border-left:3px solid #d9a13c; background:#1d232e;
             border-radius:0 8px 8px 0; padding:8px 12px; font-size:12.5px; }}
  .assume b {{ color:#d9a13c; }}
  .assume ul {{ margin:4px 0 0 16px; color:var(--soft); }}
  .foot {{ max-width:960px; margin:24px auto 0; color:var(--soft); font-size:12.5px;
           line-height:1.6; border-top:1px solid var(--line); padding-top:14px; }}
</style>
</head>
<body>
  <div class="head">
    <div class="kicker">S7 · story breakdown · bench demo of one beat</div>
    <h1>{esc(document.epic.id)} — {esc(document.epic.title)}</h1>
    <p class="meta">{len(stories)} stories · {total} points · generated
    {generated}{" · " + tokens if tokens else ""}<br>
    Human review gate: <b>taken as approved</b> for this bench run — in the console this stage stays
    locked until a named reviewer approves the design.</p>
  </div>
  <div class="grid">{"".join(cards)}
  </div>
  <p class="foot">Model output via <code>common/llm.py</code> ({esc(badge.title())}). Story
  points are draft sizing; the intended grounding for estimates is historical delivery data.
  Assumption boxes carry the epic's own open questions — the model is instructed never to answer
  them on the business's behalf.</p>
</body>
</html>
"""


def main() -> None:
    try:
        stories, usage = break_down_epic()
    except LLMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(render_html(stories, usage), encoding="utf-8")

    badge, _ = BADGE_LABELS[stories[0].provenance]
    print(f"EPIC-S7-001 → {len(stories)} stories ({badge})")
    for story in stories:
        streams = ", ".join(s.value for s in story.streams)
        flag = f"  [{len(story.assumptions)} assumption(s)]" if story.assumptions else ""
        print(f"  {story.id}  {story.estimate_points:>2} pts  {story.title}  ({streams}){flag}")
    print(f"\nwrote {OUT_PATH.relative_to(REPO_ROOT)}")
    if "--open" in sys.argv:
        webbrowser.open(OUT_PATH.as_uri())


if __name__ == "__main__":
    main()
