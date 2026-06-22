"""Modal to create a new user, optionally cloning a template user's permissions.

Cloning copies BOTH the template's group memberships and its direct project
memberships (the latter are unusual and flagged `⚠`). Status is chosen between
`invited` (sends an invitation email) and `active`.
"""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Grid, Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Input, Label

from op.perms_queue import CreateUserClone
from op.tui.picker_widget import CompactInput, ListPickerScreen


def _template_clone_specs(app, template_uid: int):  # noqa: ANN001, ANN202
    """(group_ids, memberships) the template user has — for cloning."""
    group_ids = {
        gid for gid, members in app.group_members.items() if template_uid in members
    }
    memberships: set[tuple[int, frozenset[int]]] = set()
    for pid in app.direct_projects.get(template_uid, set()):
        for m in app.memberships.get(pid, []):
            if m.principal_type == 'user' and m.principal_id == template_uid:
                memberships.add((pid, frozenset(m.role_ids)))
    return group_ids, memberships


class PermsNewUserModal(ModalScreen[bool]):
    BINDINGS = [
        Binding('ctrl+s', 'apply', 'Anlegen', show=True),
        Binding('ctrl+t', 'toggle_status', 'Status invited/active', show=True),
        Binding('ctrl+p', 'pick_template', 'Vorlage wählen', show=True),
        Binding('escape', 'cancel', 'Abbrechen', show=True),
    ]

    DEFAULT_CSS = """
    PermsNewUserModal { align: center middle; }
    PermsNewUserModal > Vertical {
        background: $panel; border: round $accent; padding: 1 2;
        width: 72; height: auto;
    }
    PermsNewUserModal Grid {
        grid-size: 2; grid-columns: 16 1fr; grid-rows: auto; height: auto;
    }
    PermsNewUserModal Grid > Label { height: 1; padding: 0; }
    """

    def __init__(self) -> None:
        super().__init__()
        self._status = 'invited'
        self._template: int | None = None

    def compose(self):  # noqa: ANN201
        with Vertical():
            yield Label('Neuen Benutzer anlegen', id='nu-title')
            with Grid():
                yield Label('Vorname:')
                yield CompactInput(id='nu-first')
                yield Label('Nachname:')
                yield CompactInput(id='nu-last')
                yield Label('E-Mail:')
                yield CompactInput(id='nu-email', placeholder='name@dvs.ag')
                yield Label('Login:')
                yield CompactInput(id='nu-login', placeholder='leer = E-Mail')
            yield Label('', id='nu-status')
            yield Label('', id='nu-template')
            yield Footer()

    def on_mount(self) -> None:
        self._refresh_labels()
        self.query_one('#nu-first', CompactInput).focus()

    def _refresh_labels(self) -> None:
        self.query_one('#nu-status', Label).update(
            f'Status: {self._status}  (Ctrl+T zum Umschalten)'
        )
        tname = (
            self.app.config.remote.users.get(self._template, str(self._template))
            if self._template is not None else '— keine —'
        )
        self.query_one('#nu-template', Label).update(
            f'Vorlage (Ctrl+P): {tname}'
        )

    def action_toggle_status(self) -> None:
        self._status = 'active' if self._status == 'invited' else 'invited'
        self._refresh_labels()

    def action_pick_template(self) -> None:
        options = sorted(
            ((name, uid) for uid, name in self.app.config.remote.users.items()),
            key=lambda o: o[0].lower(),
        )

        def _on_pick(result: object) -> None:
            if isinstance(result, int):
                self._template = result
                self._refresh_labels()

        self.app.push_screen(ListPickerScreen(options), _on_pick)

    def action_apply(self) -> None:
        first = self.query_one('#nu-first', Input).value.strip()
        last = self.query_one('#nu-last', Input).value.strip()
        email = self.query_one('#nu-email', Input).value.strip()
        login = self.query_one('#nu-login', Input).value.strip() or email
        if not (first and last and email):
            self.notify('Vorname, Nachname und E-Mail sind erforderlich.', severity='error', timeout=4)
            return
        group_ids: set[int] = set()
        memberships: set[tuple[int, frozenset[int]]] = set()
        template_name = None
        if self._template is not None:
            group_ids, memberships = _template_clone_specs(self.app, self._template)
            template_name = self.app.config.remote.users.get(self._template, str(self._template))
        self.app.perms_queue.add(CreateUserClone(
            login=login, email=email, first_name=first, last_name=last,
            user_status=self._status, template_name=template_name,
            group_ids=group_ids, memberships=memberships,
        ))
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
