"""Convert an HTML snippet (e.g. an OpenProject comment body) to Markdown.

We use `html2text` because it preserves structure — in particular, HTML tables
are converted to GitHub-flavored Markdown tables, which Textual's Markdown widget
renders correctly. Without this, WYSIWYG-edited comments lose their tables.

GFM tables cannot contain real line-breaks inside a cell: any `\\n` inside a row
turns the remainder into a new pseudo-row, with subsequent text sliding into
column 1. OpenProject's WYSIWYG editor happily emits `<td><p>a</p><p>b</p></td>`
or `<td>a<br>b</td>` though, so we pre-flatten those patterns inside table cells
before handing the HTML to `html2text`.
"""

from __future__ import annotations

import re

import html2text

_CELL_RE = re.compile(
    r'(<(t[dh])\b[^>]*>)(.*?)(</\2>)',
    flags=re.DOTALL | re.IGNORECASE,
)


def html_to_markdown(html: str) -> str:
    if not html:
        return ''
    html = _flatten_table_cells(html)
    converter = html2text.HTML2Text()
    converter.body_width = 0   # don't wrap long paragraphs
    converter.ignore_links = False
    converter.ignore_images = False
    converter.ignore_emphasis = False
    converter.protect_links = True
    return converter.handle(html)


def _flatten_table_cells(html: str) -> str:
    """Collapse block-level elements inside <td>/<th> to single-line content.

    Markdown tables require each row on one line. `<p>…</p>`, `<div>…</div>`,
    `<br>` etc. inside a cell would otherwise produce internal `\\n`s.
    """

    def _flatten(match: re.Match) -> str:
        opening, _tag, content, closing = (
            match.group(1),
            match.group(2),
            match.group(3),
            match.group(4),
        )
        # Strip opening <p>/<div> tags (and their closings → replace with space)
        content = re.sub(r'<(p|div)\b[^>]*>', '', content, flags=re.IGNORECASE)
        content = re.sub(r'</(p|div)>', ' ', content, flags=re.IGNORECASE)
        # <br> → space
        content = re.sub(r'<br\s*/?>', ' ', content, flags=re.IGNORECASE)
        # Collapse newlines and runs of whitespace
        content = re.sub(r'\s+', ' ', content).strip()
        return opening + content + closing

    return _CELL_RE.sub(_flatten, html)
