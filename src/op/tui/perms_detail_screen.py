"""Detail view for `op perms` — principals of one project, group-centric.

Groups are shown as the unit with their visible members nested beneath them;
genuinely-direct users are listed separately. The materialised per-user entries
OpenProject creates from a group are NOT listed individually (folded away).
"""

from __future__ import annotations

from rich.text import Text
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header

from op.perms import build_source_set, missing_entries, visible_members


class PermsDetailScreen(Screen[None]):
    BINDINGS = [
        Binding('q', 'back', 'Zurück', show=True),
        Binding('escape', 'back', 'Zurück', show=False),
    ]

    def __init__(self, project_id: int) -> None:
        super().__init__()
        self.project_id = project_id

    def compose(self):  # noqa: ANN201
        yield Header()
        yield DataTable(id='perms-detail', cursor_type='row', zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        name = self.app.projects.get(self.project_id, str(self.project_id))
        self.app.sub_title = f'Berechtigungen · {name}'
        table = self.query_one('#perms-detail', DataTable)
        table.add_column('Principal')
        table.add_column('Rollen', width=30)

        memberships = self.app.memberships.get(self.project_id, [])
        source = build_source_set(memberships, self.app.group_members)
        vis = visible_members(memberships, self.app.group_members)
        roles_by_principal = {
            (e.kind, e.principal_id): sorted(e.role_ids) for e in source
        }

        groups = sorted(
            (e for e in source if e.kind == 'group'),
            key=lambda e: self.app.principal_label('group', e.principal_id).lower(),
        )
        users = sorted(
            (e for e in source if e.kind == 'user'),
            key=lambda e: self.app.principal_label('user', e.principal_id).lower(),
        )

        if not groups and not users:
            table.add_row(Text('(keine direkten Berechtigungen)', style='dim'), Text(''))

        for g in groups:
            gname = self.app.principal_label('group', g.principal_id)
            table.add_row(
                Text(f'▸ {gname}', style='bold'),
                self.app.role_label(roles_by_principal[('group', g.principal_id)]),
            )
            for uid in sorted(
                vis.get(g.principal_id, []),
                key=lambda u: self.app.principal_label('user', u).lower(),
            ):
                table.add_row(
                    Text(f'    {self.app.principal_label("user", uid)}', style='dim'),
                    Text('via Gruppe', style='dim'),
                )
        for u in users:
            table.add_row(
                Text(f'⚠ {self.app.principal_label("user", u.principal_id)}', style='yellow'),
                Text(
                    f'{self.app.role_label(roles_by_principal[("user", u.principal_id)])}'
                    '  · direkt (unüblich)',
                    style='yellow',
                ),
            )

        self._add_deviation_section(table, source)

    def _add_deviation_section(self, table: DataTable, source) -> None:  # noqa: ANN001
        """List what this project is missing compared to its parent project."""
        parent = self.app.parents.get(self.project_id)
        if parent is None or parent not in self.app.projects:
            return
        missing = missing_entries(self.app.source_set(parent), source)
        if not missing:
            return
        pname = self.app.projects.get(parent, str(parent))
        table.add_row(Text(''), Text(''))
        table.add_row(Text(f'▲ Fehlt ggü. Oberprojekt ({pname}):', style='bold yellow'), Text(''))
        for e in sorted(missing, key=lambda x: (x.kind, x.principal_id)):
            prefix = '▸ ' if e.kind == 'group' else '⚠ '
            table.add_row(
                Text(f'  {prefix}{self.app.principal_label(e.kind, e.principal_id)}', style='yellow'),
                Text(self.app.role_label(sorted(e.role_ids)), style='yellow'),
            )

    def action_back(self) -> None:
        self.app.pop_screen()
