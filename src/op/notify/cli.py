"""`op notify` — command line side of the notification triage.

The mode does three things in one pass: fetch and group the unread inbox, have
the model classify and summarise it, and — if asked — mark what is done with as
read. Everything the model is not needed for still works without it (`--no-llm`),
because an unreachable model must not stand between the user and their inbox.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from op.api import ConnectionFailedError, OpenProjectError
from op.config import Config, default_config_path, get_api_key, get_llm_api_key, load_config
from op.logging_setup import setup_logging
from op.notify.analysis import GroupAnalysis, analyse_groups, build_report, render_blocks
from op.notify.api import NotificationsClient
from op.notify.cache import AnalysisCache
from op.notify.grouping import group_by_work_package
from op.notify.llm import LlmClient, LlmError, LlmUnavailableError
from op.notify.mark import MarkQueue, select_analyses
from op.notify.models import NotificationGroup
from op.notify.tui.app import NotifyApp

log = logging.getLogger('op.notify.cli')

_CLASSIFICATION_LABEL = {
    'relevant': '[bold red]relevant[/bold red]',
    'worth_knowing': '[yellow]zur Kenntnis[/yellow]',
    'churn': '[dim]Rauschen[/dim]',
}
_CLASSIFICATION_ORDER = {'relevant': 0, 'worth_knowing': 1, 'churn': 2}


def parse_notify_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog='op notify',
        description='Die persönliche Benachrichtigungs-Inbox sichten — gruppiert nach Work '
                    'Package, eingestuft und zusammengefasst von einem lokalen LLM.',
    )
    parser.add_argument('-i', '--interactive', action='store_true',
                        help='Interaktive TUI statt Terminal-Bericht.')
    parser.add_argument('--no-llm', action='store_true',
                        help='Nur gruppierte Rohsicht, ohne Modell.')
    parser.add_argument('--refresh', action='store_true',
                        help='Zwischengespeicherte Analysen übergehen.')
    parser.add_argument('--mark-read', nargs='+', type=int, default=[], metavar='ID',
                        help='Genannte Work-Package- oder Benachrichtigungs-IDs als gelesen '
                             'markieren.')
    parser.add_argument('--mark-read-churn', action='store_true',
                        help='Alles als Rauschen Eingestufte als gelesen markieren.')
    parser.add_argument('--mark-read-all', action='store_true',
                        help='Die komplette Inbox als gelesen markieren.')
    args = parser.parse_args(argv)
    args.command = 'notify'
    return args


async def run_notify(
    args: argparse.Namespace,
    *,
    config: Config | None = None,
    config_path: Path | None = None,
    console: Console | None = None,
) -> int:
    console = console or Console()
    if config is None:
        config_path = config_path or default_config_path()
        config = load_config(config_path)
        setup_logging(config)

    api_key = get_api_key(config)
    if not api_key:
        console.print('[red]Kein API-Key gefunden.[/red] OP_API_KEY setzen oder api_key in '
                      'der Config eintragen.')
        return 2

    wants_marking = bool(args.mark_read) or args.mark_read_churn or args.mark_read_all
    if args.no_llm and args.mark_read_churn:
        console.print('[red]--mark-read-churn braucht die Einstufung[/red] — ohne Modell gibt '
                      'es kein Rauschen zu markieren. Ohne --no-llm erneut aufrufen.')
        return 2

    try:
        async with NotificationsClient(config.connection.base_url, api_key) as client:
            own_user_id, user_name = await client.get_me()
            notifications = await client.get_unread_notifications()
            groups = group_by_work_package(notifications)

            if not groups:
                console.print('[green]Keine ungelesenen Benachrichtigungen.[/green]')
                return 0

            if args.no_llm:
                blocks = await render_blocks(
                    groups, op=client, own_user_id=own_user_id,
                    hide_own=config.notifications.hide_own_activities,
                    user_names=_user_names(groups, config),
                )
                analyses = [
                    _unanalysed(group, blocks.get(group.work_package_id or -1, ''))
                    for group in groups
                ]
                if args.interactive:
                    await _run_tui(args, config, client, analyses, None,
                                   own_user_id=own_user_id, user_name=user_name)
                    return 0
                console.print(_raw_table(groups))
            else:
                llm = _build_llm(config)
                try:
                    # The client stays open across the TUI: the detail view asks
                    # it what a work package wants from the reader.
                    async with llm:
                        if not config.llm.model:
                            console.print(await _model_hint(llm))
                            return 2
                        analyses = await _analyse(
                            groups, client, config, llm,
                            own_user_id=own_user_id, user_name=user_name,
                            refresh=args.refresh,
                        )
                        if args.interactive:
                            await _run_tui(args, config, client, analyses, llm,
                                           own_user_id=own_user_id, user_name=user_name)
                            return 0
                        report = await build_report(
                            _sorted(analyses), llm=llm, user_name=user_name,
                            extra_instructions=config.notifications.extra_instructions,
                        )
                except LlmUnavailableError as exc:
                    console.print(_llm_unavailable(exc, config))
                    return 3
                except LlmError as exc:
                    console.print(f'[red]Das Modell hat keine brauchbare Antwort geliefert:[/red] '
                                  f'{exc}')
                    return 1
                console.print(Markdown(report))
                console.print(_overview(analyses))

            if wants_marking:
                return await _mark(args, analyses, client, console)
            return 0
    except ConnectionFailedError as exc:
        console.print(f'[red]Keine Verbindung zum OpenProject-Server:[/red] {exc}')
        return 3
    except OpenProjectError as exc:
        console.print(f'[red]OpenProject-Fehler:[/red] {exc}')
        return 1


def _build_llm(config: Config) -> LlmClient:
    return LlmClient(
        base_url=config.llm.base_url,
        model=config.llm.model,
        api_key=get_llm_api_key(config),
        temperature=config.llm.temperature,
        max_tokens=config.llm.max_tokens,
        timeout=config.llm.timeout,
        parallel=config.llm.parallel,
        disable_thinking=config.llm.disable_thinking,
    )


async def _analyse(
    groups: list[NotificationGroup],
    client: NotificationsClient,
    config: Config,
    llm: LlmClient,
    *,
    own_user_id: int,
    user_name: str,
    refresh: bool,
) -> list[GroupAnalysis]:
    cache = AnalysisCache(enabled=config.notifications.cache_enabled and not refresh)
    return await analyse_groups(
        groups, op=client, llm=llm, user_name=user_name, cache=cache,
        own_user_id=own_user_id,
        hide_own=config.notifications.hide_own_activities,
        user_names=_user_names(groups, config),
        extra_instructions=config.notifications.extra_instructions,
    )


async def _run_tui(
    args: argparse.Namespace,
    config: Config,
    client: NotificationsClient,
    analyses: list[GroupAnalysis],
    llm: LlmClient | None,
    *,
    own_user_id: int,
    user_name: str,
) -> None:
    app = NotifyApp(
        config=config, client=client, analyses=analyses, llm=llm,
        own_user_id=own_user_id, user_name=user_name,
    )
    await app.run_async()


async def _model_hint(llm: LlmClient) -> str:
    """Ask the server which models it serves, so the message is actionable."""
    try:
        available = await llm.available_models()
    except LlmError:
        available = []
    offer = ', '.join(available) if available else '— Server nennt keine'
    return (
        '[red]Kein Modell konfiguriert.[/red] In der Config unter [bold][llm][/bold] '
        f'[bold]model[/bold] eintragen.\nVerfügbar auf {llm.base_url}: {offer}'
    )


def _user_names(groups: list[NotificationGroup], config: Config) -> dict[int, str]:
    """Names for activity authors — from the notifications themselves plus the cache.

    The activity's user link carries no title on every instance, and the actors
    of the very notifications we are looking at are the most likely authors.
    """
    names: dict[int, str] = dict(config.remote.users)
    for group in groups:
        for notification in group.notifications:
            if notification.actor_id and notification.actor_name:
                names[notification.actor_id] = notification.actor_name
    return names


async def _mark(
    args: argparse.Namespace,
    analyses: list[GroupAnalysis],
    client: NotificationsClient,
    console: Console,
) -> int:
    try:
        selected = select_analyses(
            analyses,
            work_package_ids=args.mark_read or None,
            churn=args.mark_read_churn,
            all_groups=args.mark_read_all,
        )
    except ValueError as exc:
        console.print(f'[red]{exc}[/red]')
        return 2

    if not selected:
        console.print('[yellow]Nichts zu markieren.[/yellow]')
        return 0

    queue = MarkQueue()
    for analysis in selected:
        queue.add(analysis)
    result = await queue.apply(client)

    console.print(
        f'[green]{result.marked} Benachrichtigung(en) als gelesen markiert[/green] '
        f'({queue.count} Work Package(s)).'
    )
    for notification_id, message in result.failed:
        console.print(f'[red]  #{notification_id} fehlgeschlagen:[/red] {message}')
    return 1 if result.failed else 0


def _raw_table(groups: list[NotificationGroup]) -> Table:
    table = Table(title='Ungelesene Benachrichtigungen', show_lines=False, expand=True)
    table.add_column('WP', justify='right', min_width=5, no_wrap=True)
    table.add_column('Titel', overflow='ellipsis', no_wrap=True, ratio=1)
    table.add_column('Projekt', max_width=18, overflow='ellipsis', no_wrap=True)
    table.add_column('Anzahl', justify='right', min_width=6, no_wrap=True)
    table.add_column('Gründe', max_width=22, overflow='ellipsis', no_wrap=True)
    table.add_column('Zuletzt', min_width=16, no_wrap=True)
    for group in groups:
        reasons = ', '.join(f'{r}×{c}' for r, c in group.reason_counts.items())
        table.add_row(
            str(group.work_package_id or '—'), group.title, group.project_name or '—',
            str(group.count), reasons, (group.latest or '')[:16].replace('T', ' '),
        )
    return table


def _overview(analyses: list[GroupAnalysis]) -> Table:
    table = Table(title='Einstufung', show_lines=False, expand=True)
    table.add_column('WP', justify='right', min_width=5, no_wrap=True)
    table.add_column('Einstufung', min_width=12, no_wrap=True)
    table.add_column('Titel', overflow='ellipsis', no_wrap=True, ratio=1)
    table.add_column('Wartet', justify='center', min_width=6, no_wrap=True)
    for analysis in _sorted(analyses):
        label = _CLASSIFICATION_LABEL.get(analysis.classification, analysis.classification)
        if analysis.error:
            label = '[red]Fehler[/red]'
        table.add_row(
            str(analysis.work_package_id or '—'), label, analysis.title,
            '✓' if analysis.waits_for_me else '',
        )
    return table


def _sorted(analyses: list[GroupAnalysis]) -> list[GroupAnalysis]:
    return sorted(
        analyses,
        key=lambda a: (_CLASSIFICATION_ORDER.get(a.classification, 9), a.latest or ''),
    )


def _unanalysed(group: NotificationGroup, block: str = '') -> GroupAnalysis:
    """Stand-in used with --no-llm so marking works the same way."""
    return GroupAnalysis(
        work_package_id=group.work_package_id,
        title=group.title,
        classification='worth_knowing',
        summary='',
        notification_ids=group.notification_ids,
        project_name=group.project_name,
        count=group.count,
        latest=group.latest,
        block=block,
    )


def _llm_unavailable(exc: LlmUnavailableError, config: Config) -> str:
    return (
        f'[red]LLM nicht erreichbar.[/red] {exc}\n'
        f'  • [bold]base_url[/bold] in der Config prüfen ([cyan]{config.llm.base_url}[/cyan])\n'
        '  • läuft der Server?\n'
        '  • ohne Modell weiterarbeiten: [bold]op notify --no-llm[/bold]'
    )


def main() -> None:
    """Entry point of the `opn` shortcut — identical to `op notify`."""
    import sys

    from op.cli import main as op_main

    sys.argv = [sys.argv[0], 'notify', *sys.argv[1:]]
    op_main()
