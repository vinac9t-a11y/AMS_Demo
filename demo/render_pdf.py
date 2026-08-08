#!/usr/bin/env python3
"""Render a repo Markdown or HTML doc to a styled, self-contained PDF.

Authoring tooling, not runtime. This is the one place in the repo that reaches
for a local browser, and it is deliberately outside the portability rule: the
generated PDF is committed, so a locked-down environment never runs this script.
Hard rule 4 constrains what the demo *needs*, not what the authors use to make
the deliverables.

No new dependency is added to requirements.txt. The Markdown subset handled here
is exactly what the repo's docs use; it is not a general converter.

    python3 demo/render_pdf.py docs/SPRINT-PLAN.md   docs/S7-Sprint-Plan.pdf
    python3 demo/render_pdf.py docs/delivery-pack.html docs/S7-Delivery-Pack.pdf

A `.html` source is passed through with its own styling rather than converted —
that is the escape hatch for a document that needs more than the Markdown subset
can express. Either way, local `<img src="...">` files are inlined as data URIs
so the page renders from a temp directory and the PDF carries its own images.
"""

from __future__ import annotations

import base64
import html
import mimetypes
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)

CSS = """
@page { size: A4; margin: 16mm 15mm 18mm 15mm; }
* { box-sizing: border-box; }
body {
  font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
  font-size: 10.2pt; line-height: 1.5; color: #1b2430; margin: 0;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
h1 { font-size: 21pt; margin: 0 0 2mm; color: #12283f; letter-spacing: -0.2px; }
h2 {
  font-size: 13pt; margin: 9mm 0 3mm; color: #12283f;
  border-bottom: 2px solid #d7dee6; padding-bottom: 1.6mm;
  break-after: avoid;
}
h3 { font-size: 11pt; margin: 6mm 0 2mm; color: #2c4a68; break-after: avoid; }
p { margin: 0 0 3mm; }
a { color: #1d4e80; }
hr { border: 0; border-top: 1px solid #dde3ea; margin: 7mm 0; }
strong { color: #0f2136; }
code {
  font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 8.8pt;
  background: #eef2f6; padding: 0.5mm 1.2mm; border-radius: 2px; color: #1b3a5c;
}
pre {
  background: #f5f8fa; border: 1px solid #dfe6ed; border-left: 3px solid #4a7fb5;
  padding: 3mm 4mm; border-radius: 3px; overflow-x: auto;
  font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 8.4pt;
  line-height: 1.42; break-inside: avoid; margin: 0 0 4mm;
}
pre code { background: none; padding: 0; font-size: inherit; color: #24405c; }
blockquote {
  margin: 0 0 4mm; padding: 2.6mm 4mm; background: #eef4fa;
  border-left: 3px solid #4a7fb5; border-radius: 0 3px 3px 0;
  font-size: 10.6pt; color: #14304d;
}
blockquote p { margin: 0; }
table {
  width: 100%; border-collapse: collapse; margin: 0 0 4mm;
  font-size: 8.9pt; break-inside: avoid;
}
th {
  background: #12283f; color: #fff; text-align: left;
  padding: 2mm 2.6mm; font-weight: 600; border: 1px solid #12283f;
}
td { padding: 1.9mm 2.6mm; border: 1px solid #dde3ea; vertical-align: top; }
tbody tr:nth-child(even) td { background: #f6f9fb; }
ul, ol { margin: 0 0 3.5mm; padding-left: 6mm; }
li { margin-bottom: 1.2mm; }
.subtitle { color: #5a6b7d; font-size: 9.6pt; margin: 0 0 5mm; }
"""

INLINE = (
    (re.compile(r"`([^`]+)`"), lambda m: f"<code>{html.escape(m.group(1))}</code>"),
    (re.compile(r"\*\*([^*]+)\*\*"), lambda m: f"<strong>{m.group(1)}</strong>"),
    (re.compile(r"(?<![*\w])\*([^*]+)\*(?!\*)"), lambda m: f"<em>{m.group(1)}</em>"),
)


def inline(text: str) -> str:
    """Escape a run of text, then re-apply the inline Markdown we support."""
    out = html.escape(text)
    for pattern, repl in INLINE:
        out = pattern.sub(repl, out)
    return out


def _row_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def convert(md: str) -> str:
    lines = md.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            i += 1
            block: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            out.append(f"<pre><code>{html.escape(chr(10).join(block))}</code></pre>")
            continue

        # Table: a header row followed by a |---|---| separator.
        if (
            stripped.startswith("|")
            and i + 1 < len(lines)
            and re.fullmatch(r"\|[\s:|-]+\|", lines[i + 1].strip() or "|")
        ):
            head = _row_cells(stripped)
            i += 2
            body: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                body.append(_row_cells(lines[i].strip()))
                i += 1
            th = "".join(f"<th>{inline(c)}</th>" for c in head)
            rows = "".join(
                "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body
            )
            out.append(f"<table><thead><tr>{th}</tr></thead><tbody>{rows}</tbody></table>")
            continue

        if re.fullmatch(r"-{3,}", stripped):
            out.append("<hr>")
            i += 1
            continue

        heading = re.match(r"(#{1,4})\s+(.*)", stripped)
        if heading:
            level = len(heading.group(1))
            out.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
            i += 1
            continue

        if stripped.startswith(">"):
            quote: list[str] = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append(f"<blockquote><p>{inline(' '.join(quote))}</p></blockquote>")
            continue

        bullet = re.match(r"[-*]\s+(.*)", stripped)
        number = re.match(r"\d+\.\s+(.*)", stripped)
        if bullet or number:
            ordered = number is not None
            items: list[str] = []
            pattern = r"\d+\.\s+(.*)" if ordered else r"[-*]\s+(.*)"
            while i < len(lines):
                match = re.match(pattern, lines[i].strip())
                if match:
                    items.append(match.group(1))
                    i += 1
                elif lines[i].startswith(("  ", "\t")) and lines[i].strip() and items:
                    items[-1] += " " + lines[i].strip()  # continuation line
                    i += 1
                else:
                    break
            tag = "ol" if ordered else "ul"
            body_items = "".join(f"<li>{inline(t)}</li>" for t in items)
            out.append(f"<{tag}>{body_items}</{tag}>")
            continue

        if not stripped:
            i += 1
            continue

        para: list[str] = []
        while i < len(lines) and lines[i].strip() and not re.match(
            r"^\s*(#{1,4}\s|[-*]\s|\d+\.\s|>|\||```|-{3,}$)", lines[i]
        ):
            para.append(lines[i].strip())
            i += 1
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")

    return "\n".join(out)


_IMG_SRC = re.compile(r'(<img\b[^>]*?\bsrc=")([^"]+)(")', re.IGNORECASE)


def inline_images(page: str, base_dir: Path) -> str:
    """Rewrite local `<img src>` paths to data URIs.

    The page is rendered from a temp directory, so a relative path would 404 and
    print as a broken-image box. Inlining also means the PDF is self-contained
    and does not silently depend on files that may be cleaned up later.
    Already-inlined and remote sources are left alone.
    """

    def repl(match: re.Match[str]) -> str:
        head, src, tail = match.groups()
        if src.startswith(("data:", "http://", "https://")):
            return match.group(0)
        path = Path(src) if Path(src).is_absolute() else base_dir / src
        if not path.is_file():
            print(f"  warning: image not found, left as-is: {src}", file=sys.stderr)
            return match.group(0)
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"{head}data:{mime};base64,{encoded}{tail}"

    return _IMG_SRC.sub(repl, page)


def find_chrome() -> str:
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    for name in ("google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    raise SystemExit(
        "No Chrome/Chromium found. Install one, or convert "
        "docs/SPRINT-PLAN.md to PDF by hand."
    )


def main() -> int:
    if len(sys.argv) != 3:
        return print(__doc__) or 2
    source, target = Path(sys.argv[1]), Path(sys.argv[2])
    if not source.is_file():
        raise SystemExit(f"No such file: {source}")

    raw = source.read_text()
    if source.suffix.lower() in {".html", ".htm"}:
        # Passed through with its own styling — the escape hatch for a document
        # the Markdown subset cannot express.
        page = raw
    else:
        title = source.stem.replace("-", " ").replace("_", " ").title()
        page = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head>"
            f"<body>{convert(raw)}</body></html>"
        )
    page = inline_images(page, source.parent)

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        html_path = Path(tmp) / "page.html"
        html_path.write_text(page)
        subprocess.run(
            [
                find_chrome(),
                "--headless",
                "--disable-gpu",
                "--no-pdf-header-footer",
                f"--print-to-pdf={target.resolve()}",
                "--virtual-time-budget=4000",
                html_path.resolve().as_uri(),
            ],
            check=True,
            capture_output=True,
        )

    size = target.stat().st_size
    print(f"{target}  ({size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
