from __future__ import annotations

from op.html_to_markdown import html_to_markdown


class TestHtmlToMarkdown:
    def test_paragraph(self) -> None:
        md = html_to_markdown('<p>Hello world</p>')
        assert 'Hello world' in md

    def test_heading(self) -> None:
        md = html_to_markdown('<h1>Title</h1>')
        assert md.lstrip().startswith('#') or 'Title' in md

    def test_table_renders_as_markdown_table(self) -> None:
        html = (
            '<table>'
            '<tr><th>Stufe</th><th>Art</th></tr>'
            '<tr><td>1</td><td>DVS-Rechnung</td></tr>'
            '</table>'
        )
        md = html_to_markdown(html)
        assert 'Stufe' in md
        assert 'Art' in md
        assert 'DVS-Rechnung' in md
        # GitHub-Markdown-Tables contain pipes
        assert '|' in md

    def test_empty_html_returns_empty_string(self) -> None:
        assert html_to_markdown('').strip() == ''

    def test_no_linebreaks_for_wrapping(self) -> None:
        """Long paragraphs must not be wrapped (body_width=0) so the markdown stays intact."""
        long_text = 'word ' * 100
        md = html_to_markdown(f'<p>{long_text}</p>')
        # Single-line paragraph, no mid-sentence line breaks
        # html2text may still insert \n at paragraph boundaries, but not mid-word
        lines = [line for line in md.splitlines() if line.strip()]
        assert all(len(line) > 100 for line in lines)
