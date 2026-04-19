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

    def test_table_cell_with_multiple_paragraphs_stays_single_row(self) -> None:
        """Regression: OpenProject WYSIWYG tables wrap cells in multiple <p> tags.
        html2text alone turns that into \\n\\n inside the cell, which breaks the
        pipe-syntax — subsequent <p> lines then appear as a new pseudo-row with
        the extra text in column 1."""
        html = (
            '<table>'
            '<tr><th>Stufe</th><th>Art</th><th>Bedingung</th></tr>'
            '<tr>'
            '<td><p>1</p></td>'
            '<td><p>DVS-Rechnungsnr. + Betrag</p></td>'
            '<td>'
            '<p>rechnung_nr im VWZ</p>'
            '<p>betrag_offen == auszug_betrag</p>'
            '</td>'
            '</tr>'
            '</table>'
        )
        md = html_to_markdown(html)
        lines = [line for line in md.splitlines() if line.strip()]
        # The header row + the separator + the data row = at most 3 lines for the table.
        # We must NOT have extra lines that would be parsed as new rows.
        table_lines = [line for line in lines if '|' in line]
        # One header line, one separator (---), one data line
        assert len(table_lines) == 3, f'expected 3 table lines, got {len(table_lines)}: {table_lines}'
        # Both content strings end up in the same (third) row
        data_row = table_lines[2]
        assert 'rechnung_nr im VWZ' in data_row
        assert 'betrag_offen' in data_row

    def test_real_openproject_table_stays_intact(self) -> None:
        """Real table from OpenProject WYSIWYG — 3 columns, rich multi-paragraph cells."""
        html = """
<table>
  <tr><th>Stufe</th><th>Art</th><th>Bedingung</th></tr>
  <tr>
    <td><p>1</p></td>
    <td><p>DVS-Rechnungsnr. + Betrag</p></td>
    <td>
      <p>rechnung_nr im VWZ (auch aufgespalten nach "-");</p>
      <p>betrag_offen == auszug_betrag ODER betrag_offen + mahnbetrag_offen == auszug_betrag</p>
    </td>
  </tr>
  <tr>
    <td><p>3</p></td>
    <td><p>APS-Aktenforderung</p></td>
    <td>
      <p>IBAN in APS_AUSZAHLUNGSKONTEN + FIRMA_FORDERUNGSKONTEN;</p>
      <p>Aktennr. (erste 10 Zeichen VWZ) = rechnung.aktenzeichen_ba;</p>
      <p>Betrag wird auf mehrere Rechnungen verteilt</p>
    </td>
  </tr>
</table>
"""
        md = html_to_markdown(html)
        table_lines = [line for line in md.splitlines() if '|' in line]
        # Header + separator + 2 data rows = 4 lines
        assert len(table_lines) == 4, (
            f'expected 4 table lines, got {len(table_lines)}:\n' + '\n'.join(table_lines)
        )
        # First data row contains both paragraph snippets
        assert 'rechnung_nr' in table_lines[2]
        assert 'betrag_offen ==' in table_lines[2]
        # Second data row likewise
        assert 'IBAN in APS' in table_lines[3]
        assert 'Aktennr.' in table_lines[3]
        assert 'Betrag wird auf' in table_lines[3]

    def test_table_cell_with_br_is_flattened(self) -> None:
        html = (
            '<table>'
            '<tr><th>a</th><th>b</th></tr>'
            '<tr><td>1</td><td>line1<br>line2</td></tr>'
            '</table>'
        )
        md = html_to_markdown(html)
        table_lines = [line for line in md.splitlines() if '|' in line]
        assert len(table_lines) == 3
        assert 'line1' in table_lines[2]
        assert 'line2' in table_lines[2]
