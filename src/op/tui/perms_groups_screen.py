"""Group list view for `op perms` — toggle with `v` from the project tree."""

from __future__ import annotations

from rich.text import Text
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header

from op.perms import build_footprints, footprint_deviation, majority_footprint

_FLAG_DEVIATION = Text('▲', style='bold yellow')
_FLAG_OK = Text(' ')


class PermsGroupsScreen(Screen[None]):
    """Flat list of groups with member/project counts and a deviation flag
    (`▲` when at least one member's footprint differs from the group majority)."""

    BINDINGS = [
        Binding('v', 'to_projects', 'Projektsicht', show=True),
        Binding('g', 'review', 'Review/Apply', show=True),
        Binding('q', 'quit_app', 'Quit', show=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[int] = []

    def compose(self):  # noqa: ANN201
        yield Header()
        yield DataTable(id='perms-groups', cursor_type='row', zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self.app.sub_title = 'Gruppen'
        table = self.query_one('#perms-groups', DataTable)
        table.add_column('', width=3)
        table.add_column('Gruppe')
        table.add_column('Mitglieder', width=11)
        table.add_column('Projekte', width=9)
        self._populate()

    def _populate(self) -> None:
        table = self.query_one('#perms-groups', DataTable)
        table.clear()
        self._rows = sorted(
            self.app.config.remote.groups,
            key=lambda gid: self.app.config.remote.groups[gid].lower(),
        )
        for gid in self._rows:
            name = self.app.config.remote.groups[gid]
            members = self.app.group_members.get(gid, [])
            nproj = len(self.app.group_projects(gid))
            table.add_row(
                _FLAG_DEVIATION if self._has_deviation(gid) else _FLAG_OK,
                name,
                str(len(members)),
                str(nproj),
                key=str(gid),
            )

    def _has_deviation(self, gid: int) -> bool:
        members = self.app.group_members.get(gid, [])
        fps = build_footprints(members, self.app.group_members, self.app.direct_projects)
        maj = majority_footprint(fps)
        if not maj:
            return False
        return any(footprint_deviation(fps[uid], maj) for uid in members)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        from op.tui.perms_group_detail_screen import PermsGroupDetailScreen

        self.app.push_screen(PermsGroupDetailScreen(int(event.row_key.value)))

    def action_to_projects(self) -> None:
        self.app.pop_screen()  # back to the project tree (root)

    def action_review(self) -> None:
        if self.app.perms_queue.count == 0:
            self.notify('Keine geplanten Änderungen.', timeout=3)
            return
        from op.tui.perms_review_screen import PermsReviewScreen

        self.app.push_screen(PermsReviewScreen())

    def action_quit_app(self) -> None:
        self.app.exit()

    def on_screen_resume(self) -> None:
        if self.app.loaded:
            self._populate()
