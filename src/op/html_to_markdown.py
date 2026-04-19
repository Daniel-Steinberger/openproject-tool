"""Convert an HTML snippet (e.g. an OpenProject comment body) to Markdown.

We use `html2text` because it preserves structure — in particular, HTML tables
are converted to GitHub-flavored Markdown tables, which Textual's Markdown widget
renders correctly. Without this, WYSIWYG-edited comments lose their tables.
"""

from __future__ import annotations

import html2text


def html_to_markdown(html: str) -> str:
    if not html:
        return ''
    converter = html2text.HTML2Text()
    converter.body_width = 0   # don't wrap long paragraphs
    converter.ignore_links = False
    converter.ignore_images = False
    converter.ignore_emphasis = False
    converter.protect_links = True
    return converter.handle(html)
