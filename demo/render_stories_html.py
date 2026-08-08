#!/usr/bin/env python3
"""Emit the delivery-story section of the pack as HTML, from the repo itself.

Authoring tooling. Reads `s7_delivery.staged` directly rather than an HTTP API,
so the section reproduces from a fresh clone with no server and no API key —
and so the stories in the PDF cannot drift from the stories the console renders.

    python3 demo/render_stories_html.py > /tmp/stories.html

The output is spliced into docs/delivery-pack.html between the marker comments
STORIES:BEGIN and STORIES:END. Regenerate whenever the staged stories change.
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

# Run from anywhere: demo/ is not a package root, so put the repo on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from s7_delivery.staged import stories  # noqa: E402

# Stream slugs carry underscores in the model; these are the presentation names.
STREAM_LABELS = {
    "frontend": "Frontend",
    "api": "API / Services",
    "database": "Database",
    "system_of_record": "System of record",
    "document_intake": "Document intake",
    "mainframe": "Mainframe",
    "test": "Test",
}


def esc(text: str) -> str:
    return html.escape(str(text))


def main() -> None:
    items = stories()
    total = sum(s.estimate_points for s in items)

    print('  <p class="lede">The three stories the gate unlocks, exactly as the console '
          "renders them. Each carries its own provenance badge, stream routing and "
          "acceptance criteria.</p>")
    print(f'  <p class="small">{len(items)} stories &middot; {total} points total &middot; '
          "broken out of EPIC-S7-001 after human review.</p>")

    for story in items:
        streams = "".join(
            f'<span class="chip">{esc(STREAM_LABELS.get(s.value, s.value))}</span>'
            for s in story.streams
        )
        criteria = "".join(
            f"<li><b>{esc(c.id)}</b> — {esc(c.text)}</li>" for c in story.acceptance
        )
        assumptions = "".join(f"<li>{esc(a)}</li>" for a in story.assumptions)

        print('  <article class="story">')
        print('    <div class="story-h">')
        print(f'      <span class="story-id">{esc(story.id)}</span>')
        print(f'      <span class="pill staged">{esc(story.provenance.value)}</span>')
        print("    </div>")
        print(f"    <h3 class=\"story-t\">{esc(story.title)}</h3>")
        print(f'    <p class="story-n">{esc(story.narrative)}</p>')
        print(f'    <div class="chips">{streams}'
              f'<span class="chip pts">{story.estimate_points} points</span></div>')
        print('    <div class="story-ac"><b>Acceptance criteria</b>'
              f"<ul>{criteria}</ul></div>")
        if assumptions:
            print('    <div class="story-as"><b>Assumptions to validate with an SME</b>'
                  f"<ul>{assumptions}</ul></div>")
        print("  </article>")


if __name__ == "__main__":
    main()
