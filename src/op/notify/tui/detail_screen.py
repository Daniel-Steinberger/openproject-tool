"""Detail view of one work package.

Three things beyond the summary:

* **Roles are shown as badges, colour-coded.** Whether the reader is the
  responsible or the assignee decides how much of this is theirs, and that fact
  should not have to be dug out of the activity log.
* **An action line** — what this work package asks of the reader — is fetched
  from the model on demand, in the background. The rest of the page renders
  immediately; the line fills itself in when the answer arrives, once per work
  package for the lifetime of the program.
* **`n`/`p` navigate** and **`m` toggles** the "mark as read" selection, so the
  whole inbox can be worked through without returning to the list.
"""

from __future__ import annotations

import webbrowser

from rich.text import Text
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, Markdown, Static

from op.notify.analysis import GroupAnalysis
from op.notify.llm import LlmError
from op.notify.prompts import build_action_messages

_MINE = 'bold magenta'
_OTHER = 'dim'
_MENTION = 'bold yellow'
_PENDING = 'dim italic'


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
        yield Static(self._roles(), id='notify-roles')
        yield Static(self._action_line(), id='notify-action')
        yield Markdown(self._document(), id='notify-detail')
        yield Footer()

    def on_mount(self) -> None:
        self._update_subtitle()
        self._request_action_line()

    # --- rendering -------------------------------------------------------

    def _roles(self) -> Text:
        """Who is on this work package — the reader's own roles stand out."""
        a = self.analysis
        if a is None:
            return Text('')
        own = self.app.own_user_id
        line = Text()
        if a.is_mentioned:
            line.append('@ du wurdest erwähnt', style=_MENTION)
            line.append('   ')
        line.append('Verantwortlich: ', style='dim')
        line.append(*_person(a.responsible_id, a.responsible_name, own))
        line.append('   Zugewiesen: ', style='dim')
        line.append(*_person(a.assignee_id, a.assignee_name, own))
        if a.status_name:
            line.append('   Status: ', style='dim')
            line.append(a.status_name)
        return line

    def _action_line(self) -> Text:
        a = self.analysis
        if a is None:
            return Text('')
        cached = self.app.action_lines.get(a.work_package_id or -1)
        if cached:
            return Text(cached, style='bold')
        if self.app.llm is None:
            return Text('(ohne Modell gestartet — keine Handlungsempfehlung)', style=_PENDING)
        return Text('… wird ermittelt', style=_PENDING)

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
        self.query_one('#notify-roles', Static).update(self._roles())
        self.query_one('#notify-action', Static).update(self._action_line())
        self.query_one('#notify-detail', Markdown).update(self._document())
        self._update_subtitle()

    def _update_subtitle(self) -> None:
        a = self.analysis
        if a is None:
            return
        position = f'{self.index + 1}/{len(self.app.analyses)}'
        marked = ' · vorgemerkt' if self._is_marked() else ''
        self.app.sub_title = f'#{a.work_package_id} — {a.title} ({position}){marked}'

    # --- action line -----------------------------------------------------

    def _request_action_line(self) -> None:
        a = self.analysis
        if a is None or self.app.llm is None or a.work_package_id is None:
            return
        if a.work_package_id in self.app.action_lines:
            return
        self.run_worker(self._fetch_action_line(a), exclusive=False, group='action-line')

    async def _fetch_action_line(self, analysis: GroupAnalysis) -> None:
        work_package_id = analysis.work_package_id
        system, user = build_action_messages(
            block=analysis.block,
            user_name=self.app.user_name or 'the user',
            classification=analysis.classification,
            extra_instructions=self.app.config.notifications.extra_instructions,
        )
        try:
            answer = (await self.app.llm.complete_text(system=system, user=user)).strip()
        except LlmError as exc:
            answer = f'(Handlungsempfehlung nicht verfügbar: {exc})'
        self.app.action_lines[work_package_id or -1] = answer
        # The reader may have moved on in the meantime — only paint if still here.
        if self.is_attached and self.analysis is analysis:
            self.query_one('#notify-action', Static).update(self._action_line())

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
        self._request_action_line()

    def action_close(self) -> None:
        self.app.pop_screen()

    def action_open_browser(self) -> None:
        a = self.analysis
        if a is None or a.work_package_id is None:
            return
        base = self.app.config.connection.base_url.rstrip('/')
        webbrowser.open(f'{base}/work_packages/{a.work_package_id}')


def _person(person_id: int | None, name: str | None, own_id: int | None) -> tuple[str, str]:
    """(text, style) for one role — the reader's own name is the one that matters."""
    if person_id is None:
        return '—', _OTHER
    if own_id is not None and person_id == own_id:
        return f'du ({name})' if name else 'du', _MINE
    return name or f'#{person_id}', _OTHER
