"""Group detail for `op perms` — members, footprint deviations, management.

Shows the group's projects and its members. A member is flagged `▲` when its
footprint (other groups + direct project memberships) deviates from the group
majority, and `⚠` when it has direct (non-group) memberships at all.

Keys: `a` add member, `h` heal the highlighted deviating member (additive),
`n` create a new user, `g` review/apply.
"""

from __future__ import annotations

from rich.text import Text
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label

from op.perms import build_footprints, footprint_deviation, majority_footprint
from op.perms_queue import AddGroupMembers, CloneInto
from op.tui.picker_widget import ListPickerScreen


class PermsGroupDetailScreen(Screen[None]):
    BINDINGS = [
        Binding('a', 'add_member', 'Mitglied hinzufügen', show=True),
        Binding('h', 'heal', 'Abweichler heilen', show=True),
        Binding('n', 'new_user', 'Neuer Benutzer', show=True),
        Binding('g', 'review', 'Review/Apply', show=True),
        Binding('q', 'back', 'Zurück', show=True),
        Binding('escape', 'back', 'Zurück', show=False),
    ]

    def __init__(self, group_id: int) -> None:
        super().__init__()
        self.group_id = group_id
        self._member_rows: list[int] = []

    def compose(self):  # noqa: ANN201
        yield Header()
        yield Label('', id='perms-group-projects')
        yield DataTable(id='perms-group-members', cursor_type='row', zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        gname = self.app.config.remote.groups.get(self.group_id, str(self.group_id))
        self.app.sub_title = f'Gruppe · {gname}'
        proj_names = [
            self.app.projects.get(pid, str(pid))
            for pid in self.app.group_projects(self.group_id)
        ]
        self.query_one('#perms-group-projects', Label).update(
            Text(f'Projekte ({len(proj_names)}): ' + (', '.join(sorted(proj_names)) or '—'))
        )
        table = self.query_one('#perms-group-members', DataTable)
        table.add_column('', width=3)
        table.add_column('Mitglied')
        table.add_column('Hinweis')
        self._populate()

    def _footprints(self):  # noqa: ANN202
        members = self.app.group_members.get(self.group_id, [])
        fps = build_footprints(members, self.app.group_members, self.app.direct_projects)
        return members, fps, majority_footprint(fps)

    def _populate(self) -> None:
        table = self.query_one('#perms-group-members', DataTable)
        table.clear()
        members, fps, maj = self._footprints()
        self._member_rows = sorted(
            members, key=lambda u: self.app.principal_label('user', u).lower()
        )
        for uid in self._member_rows:
            dev = footprint_deviation(fps[uid], maj)
            direct = {e for e in fps[uid] if e[0] == 'project'}
            flag = Text('▲', style='bold yellow') if dev else Text(' ')
            notes = []
            if dev:
                notes.append(f'fehlt: {self._fmt_elements(dev)}')
            if direct:
                notes.append(Text(f'⚠ direkt: {self._fmt_elements(direct)}', 'yellow').plain)
            table.add_row(
                flag,
                self.app.principal_label('user', uid),
                Text('; '.join(notes), style='yellow' if (dev or direct) else 'dim'),
                key=str(uid),
            )

    def _fmt_elements(self, elements) -> str:  # noqa: ANN001
        labels = []
        for kind, oid in sorted(elements):
            if kind == 'group':
                labels.append(self.app.config.remote.groups.get(oid, f'G#{oid}'))
            else:
                labels.append(self.app.projects.get(oid, f'P#{oid}'))
        return ', '.join(labels)

    def _current_member(self) -> int | None:
        table = self.query_one('#perms-group-members', DataTable)
        if table.cursor_row is None or not self._member_rows:
            return None
        return self._member_rows[table.cursor_row]

    # --- actions ---------------------------------------------------------

    def action_add_member(self) -> None:
        members = set(self.app.group_members.get(self.group_id, []))
        options = sorted(
            ((name, uid) for uid, name in self.app.config.remote.users.items() if uid not in members),
            key=lambda o: o[0].lower(),
        )

        def _on_pick(result: object) -> None:
            if not isinstance(result, int):
                return
            self.app.perms_queue.add(AddGroupMembers(group_id=self.group_id, user_ids={result}))
            self._notify_queued()

        self.app.push_screen(ListPickerScreen(options), _on_pick)

    def action_heal(self) -> None:
        uid = self._current_member()
        if uid is None:
            return
        members, fps, maj = self._footprints()
        dev = footprint_deviation(fps.get(uid, set()), maj)
        if not dev:
            self.notify('Keine Abweichung — nichts zu heilen.', timeout=3)
            return
        role = self.app.member_role_id()
        group_ids = {oid for kind, oid in dev if kind == 'group'}
        memberships = {
            (oid, frozenset({role} if role is not None else set()))
            for kind, oid in dev if kind == 'project'
        }
        self.app.perms_queue.add(CloneInto(
            target_user_id=uid, group_ids=group_ids, memberships=memberships,
        ))
        self._notify_queued()

    def action_new_user(self) -> None:
        from op.tui.perms_new_user_modal import PermsNewUserModal

        def _on_done(_: object) -> None:
            self._notify_queued()

        self.app.push_screen(PermsNewUserModal(), _on_done)

    def action_review(self) -> None:
        if self.app.perms_queue.count == 0:
            self.notify('Keine geplanten Änderungen.', timeout=3)
            return
        from op.tui.perms_review_screen import PermsReviewScreen

        self.app.push_screen(PermsReviewScreen())

    def action_back(self) -> None:
        self.app.pop_screen()

    def on_screen_resume(self) -> None:
        if self.app.loaded:
            self._populate()

    def _notify_queued(self) -> None:
        self.notify(
            f'{self.app.perms_queue.count} geplante Änderung(en). "g" zum Review.',
            timeout=4,
        )
