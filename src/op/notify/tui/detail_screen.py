"""Detail view: the model's summary above the activity log it was made from.

The screen navigates the inbox itself (`n`/`p`) instead of sending the reader
back to the list for every work package, and `m` toggles the "mark as read"
selection right here. Toggling works against the queue, not the server: there is
no documented way back to *unread*, so nothing is written until the review
screen applies it.
"""

from __future__ import annotations

import webbrowser

from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, Markdown

from op.notify.analysis import GroupAnalysis


class NotifyDetailScreen(Screen[None]):
    BINDINGS = [
        Binding('m', 'toggle_mark', 'Gelesen', show=True),
        Binding('p', 'previous', 'Zurück', show=True),
        Binding('n', 'next', 'Weiter', show=True),
        Binding('o', 'open_browser', 'Browser', show=True),
        Binding('q', 'close', 'Liste', show=True),
        Binding('escape', 'close', 'Liste', show=False),
    ]

    def __init__(self, index: int) -> None:
        super().__init__()
        self.index = index

    @property
    def analysis(self) -> GroupAnalysis | None:
        if 0 <= self.index < len(self.app.analyses):
            return self.app.analyses[self.index]
        return None

    def compose(self):  # noqa: ANN201
        yield Header()
        yield Markdown(self._document(), id='notify-detail')
        yield Footer()

    def on_mount(self) -> None:
        self._update_subtitle()

    def _document(self) -> str:
        a = self.analysis
        if a is None:
            return '(kein Eintrag)'
        parts = [f'# #{a.work_package_id} — {a.title}', '']
        meta = [a.project_name, f'{a.count} Benachrichtigung(en)']
        if self._is_marked():
            meta.append('**als gelesen vorgemerkt**')
        parts.extend([' · '.join(m for m in meta if m), ''])
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

    def _is_marked(self) -> bool:
        a = self.analysis
        return a is not None and self.app.queue.contains(a.work_package_id)

    def _refresh(self) -> None:
        self.query_one('#notify-detail', Markdown).update(self._document())
        self._update_subtitle()

    def _update_subtitle(self) -> None:
        a = self.analysis
        if a is None:
            return
        position = f'{self.index + 1}/{len(self.app.analyses)}'
        marked = ' · vorgemerkt' if self._is_marked() else ''
        self.app.sub_title = f'#{a.work_package_id} — {a.title} ({position}){marked}'

    # --- actions ---------------------------------------------------------

    def action_toggle_mark(self) -> None:
        a = self.analysis
        if a is None:
            return
        if self.app.queue.contains(a.work_package_id):
            self.app.queue.remove(a.work_package_id)
        else:
            self.app.queue.add(a)
        self._refresh()

    def action_next(self) -> None:
        self._move(1)

    def action_previous(self) -> None:
        self._move(-1)

    def _move(self, step: int) -> None:
        target = self.index + step
        if not 0 <= target < len(self.app.analyses):
            return  # stop at the ends rather than wrapping around
        self.index = target
        self.app.detail_index = target
        self._refresh()

    def action_close(self) -> None:
        self.app.pop_screen()

    def action_open_browser(self) -> None:
        a = self.analysis
        if a is None or a.work_package_id is None:
            return
        base = self.app.config.connection.base_url.rstrip('/')
        webbrowser.open(f'{base}/work_packages/{a.work_package_id}')
