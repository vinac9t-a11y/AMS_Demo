"""Markdown -> render-ready blocks.

The console has no markdown parser, deliberately — it would have to be vendored
to survive the locked-down port. So the conversion happens server-side, and
these tests pin the cases the epic actually contains. Getting this wrong is
visible on a projector: literal `**bold**` and bullets flattened into prose.
"""

from __future__ import annotations

from s7_delivery.pipeline import _to_blocks, build_state, to_payload


def test_paragraphs_split_on_blank_lines() -> None:
    blocks = _to_blocks("First paragraph.\n\nSecond paragraph.")
    assert blocks == [
        {"type": "paragraph", "text": "First paragraph."},
        {"type": "paragraph", "text": "Second paragraph."},
    ]


def test_wrapped_lines_join_into_one_paragraph() -> None:
    blocks = _to_blocks("A sentence that was\nhard wrapped by the author.")
    assert blocks == [
        {"type": "paragraph", "text": "A sentence that was hard wrapped by the author."}
    ]


def test_bullets_become_an_unordered_list() -> None:
    blocks = _to_blocks("Intro line:\n\n- first\n- second")
    assert blocks[0]["type"] == "paragraph"
    assert blocks[1] == {"type": "list", "ordered": False, "items": ["first", "second"]}


def test_numbered_items_become_an_ordered_list() -> None:
    blocks = _to_blocks("1. first\n2. second")
    assert blocks == [{"type": "list", "ordered": True, "items": ["first", "second"]}]


def test_emphasis_markers_are_stripped_not_shown() -> None:
    """`**plan sponsors**` reached the browser as literal asterisks."""
    blocks = _to_blocks("MapleSure sells to **plan sponsors** — employer `organizations`.")
    assert "**" not in blocks[0]["text"]
    assert "`" not in blocks[0]["text"]
    assert "plan sponsors" in blocks[0]["text"]


def test_blockquote_markers_are_stripped() -> None:
    blocks = _to_blocks("> Give plan sponsors a guided online way\n> to submit a claim.")
    assert blocks == [
        {"type": "paragraph", "text": "Give plan sponsors a guided online way to submit a claim."}
    ]


def test_table_rows_are_dropped() -> None:
    """The epic's metadata table is surfaced as dedicated fields already."""
    blocks = _to_blocks("| **Id** | EPIC-S7-001 |\n|---|---|\n\nReal prose.")
    assert blocks == [{"type": "paragraph", "text": "Real prose."}]


def test_indented_continuation_joins_its_bullet() -> None:
    blocks = _to_blocks("- a bullet that continues\n  onto the next line\n- second")
    assert blocks[0]["items"] == ["a bullet that continues onto the next line", "second"]


def test_switching_list_type_starts_a_new_list() -> None:
    blocks = _to_blocks("- bullet\n\n1. numbered")
    assert [b["ordered"] for b in blocks] == [False, True]


def test_empty_body_yields_no_blocks() -> None:
    assert _to_blocks("") == []


# --- against the real epic --------------------------------------------------


def test_the_real_epic_produces_no_stray_markdown() -> None:
    payload = to_payload(build_state())
    for section in payload["epic"]["sections"]:
        assert section["blocks"], f"section {section['heading']!r} rendered to nothing"
        for block in section["blocks"]:
            texts = [block["text"]] if block["type"] == "paragraph" else block["items"]
            for text in texts:
                assert "**" not in text
                assert not text.startswith(("-", ">", "|"))


def test_current_state_bullets_survive_as_a_list() -> None:
    payload = to_payload(build_state())
    section = next(s for s in payload["epic"]["sections"] if s["heading"] == "Current state")
    lists = [b for b in section["blocks"] if b["type"] == "list"]
    assert lists and len(lists[0]["items"]) >= 4
