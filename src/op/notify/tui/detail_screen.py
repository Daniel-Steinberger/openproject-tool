"""Detail view: the model's summary above the activity log it was made from."""

from __future__ import annotations

import webbrowser

from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, Markdown

from op.notify.analysis import GroupAnalysis


class NotifyDetailScreen(Screen[None]):
    BINDINGS = [
        Binding('q', 'close', 'Zurück', show=True),
        Binding('escape', 'close', 'Zurück', show=False),
        Binding('o', 'open_browser', 'Browser', show=True),
    ]

    def __init__(self, analysis: GroupAnalysis) -> None:
        super().__init__()
        self.analysis = analysis

    def compose(self):  # noqa: ANN201
        yield Header()
        yield Markdown(self._document(), id='notify-detail')
        yield Footer()

    def on_mount(self) -> None:
        self.app.sub_title = f'#{self.analysis.work_package_id} — {self.analysis.title}'

    def _document(self) -> str:
        a = self.analysis
        parts = [f'# #{a.work_package_id} — {a.title}', '']
        if a.project_name:
            parts.append(f'*{a.project_name}* · {a.count} Benachrichtigung(en)')
            parts.append('')
        if a.error:
            parts.extend([f'> **Analyse fehlgeschlagen:** {a.error}', ''])
        if a.summary:
            parts.extend([a.summary, ''])
        if a.open_points:
            parts.append('## Offene Punkte')
            parts.extend(f'- {point}' for point in a.open_points)
            parts.append('')
        if a.rationale:
            parts.extend([f'*Einstufung `{a.classification}`: {a.rationale}*', ''])
        # The raw block is what the model saw — it makes the summary checkable.
        parts.extend(['## Aktivitäten', '', a.block or '(kein Aktivitätsblock)'])
        return '\n'.join(parts)

    def action_close(self) -> None:
        self.app.pop_screen()

    def action_open_browser(self) -> None:
        if self.analysis.work_package_id is None:
            return
        base = self.app.config.connection.base_url.rstrip('/')
        webbrowser.open(f'{base}/work_packages/{self.analysis.work_package_id}')
