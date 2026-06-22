from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

from rich.console import Console, Group
from rich.text import Text

from op.actions import load_remote_data
from op.api import AuthError, OpenProjectClient, OpenProjectError
from op.config import Config, DefaultsConfig, default_config_path, get_api_key, load_config
from op.logging_setup import setup_logging
from op.models import WorkPackage
from op.search import FILTER_KEYS, build_api_filter_variants, parse
from op.tui.app import OpApp


def main() -> None:
    try:
        _cfg = load_config(default_config_path())
        _defaults = _cfg.defaults
    except Exception:
        _defaults = None
    args = _parse_args(sys.argv[1:], defaults=_defaults)
    try:
        exit_code = asyncio.run(run(args))
    except AuthError as exc:
        Console(stderr=True).print(f'[red]Authentication error:[/red] {exc}')
        exit_code = 2
    except OpenProjectError as exc:
        Console(stderr=True).print(f'[red]OpenProject API error:[/red] {exc}')
        exit_code = 1
    sys.exit(exit_code or 0)


def _parse_args(argv: list[str], *, defaults: DefaultsConfig | None = None) -> argparse.Namespace:
    # `op perms [projekt]` is a distinct mode (own TUI), kept separate from the
    # work-package query parser so the positional `query` semantics are unchanged.
    if argv and argv[0] == 'perms':
        perms = argparse.ArgumentParser(prog='op perms')
        perms.add_argument('project', nargs='?', help='Projekt-ID, -Name oder -Identifier')
        ns = perms.parse_args(argv[1:])
        return argparse.Namespace(
            command='perms', perms_project=ns.project,
            load_remote_data=False, interactive=False, query=[],
        )

    parser = argparse.ArgumentParser(
        prog='op',
        description='Fast, keyboard-driven CLI and TUI for OpenProject.',
    )
    parser.set_defaults(command=None)
    parser.add_argument(
        '--load-remote-data',
        action='store_true',
        help='Fetch statuses, types, priorities, projects, users and custom fields from '
        'OpenProject and cache them in the config file.',
    )
    parser.add_argument(
        '-i',
        '--interactive',
        action='store_true',
        help='Open the interactive TUI instead of printing results.',
    )
    parser.add_argument(
        'query',
        nargs='*',
        help=_build_query_help(defaults),
    )
    return parser.parse_args(argv)


def _build_query_help(defaults: DefaultsConfig | None) -> str:
    keys_str = ', '.join(FILTER_KEYS) + ', cf<N>'
    parts = [
        f'Search tokens: an ID (e.g. 1234), free-text words, or key=value filters. '
        f'Filter keys: {keys_str}. '
        f'Values are matched case-insensitively and as substrings (e.g. "bug" matches "Bug Feature"). '
        f'Multiple values comma-separated (e.g. type=Bug,Task). '
        f'Use * to override a default (e.g. status=*), ! to find unset fields (e.g. assignee=! pm=!).',
    ]
    if defaults:
        active: list[str] = []
        if defaults.status:
            active.append(f'status={",".join(defaults.status)}')
        if defaults.type:
            active.append(f'type={",".join(defaults.type)}')
        if active:
            parts.append(f'Active defaults (use * to disable): {" ".join(active)}.')
    return ' '.join(parts)


async def run(
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
        Console(stderr=True).print(
            '[red]No API key found.[/red] Set OP_API_KEY or add api_key to your config.'
        )
        return 2

    async with OpenProjectClient(config.connection.base_url, api_key) as client:
        if args.load_remote_data:
            path = config_path or default_config_path()
            await load_remote_data(client, path)
            console.print('[green]Remote data loaded.[/green]')
            return 0

        if getattr(args, 'command', None) == 'perms':
            return await _run_perms(args, client, config, console)

        try:
            query = parse(args.query, defaults=config.defaults)
        except ValueError as exc:
            console.print(f'[red]Invalid query:[/red] {exc}')
            return 2
        if args.interactive:
            initial_tasks = await _initial_tasks(client, query, config)
            log.info(
                'Starting TUI: client=%s tasks=%d',
                type(client).__name__, len(initial_tasks),
            )
            effective_config_path = config_path or default_config_path()
            app = OpApp(
                tasks=initial_tasks,
                config=config,
                client=client,
                config_path=effective_config_path,
                query=query,
            )
            await app.run_async()
            log.info('TUI exited cleanly')
            return 0

        if query.task_id is not None:
            wp = await client.get_work_package(query.task_id)
            if wp is None:
                Console(stderr=True).print(
                    f'[red]Task #{query.task_id} not found.[/red]'
                )
                return 1
            console.print(format_task_detail(wp, config.connection.base_url))
            return 0

        if query.task_ids:
            results = await client.get_work_packages_by_ids(query.task_ids)
            for wp in results:
                console.print(format_result_line(wp, config.connection.base_url))
            missing = [i for i in query.task_ids if i not in {wp.id for wp in results}]
            if missing:
                Console(stderr=True).print(
                    f'[yellow]Nicht gefunden:[/yellow] {", ".join(f"#{i}" for i in missing)}'
                )
            return 0

        try:
            filter_variants = build_api_filter_variants(query, config.remote)
        except ValueError as exc:
            console.print(f'[red]Invalid search query:[/red] {exc}')
            return 2
        results = await client.search_work_packages_variants(filter_variants=filter_variants)
        for wp in results:
            console.print(format_result_line(wp, config.connection.base_url))
        return 0


async def _run_perms(
    args: argparse.Namespace,
    client: OpenProjectClient,
    config: Config,
    console: Console,
) -> int:
    """Launch the interactive permission tool (`op perms [projekt]`)."""
    if not config.remote.projects:
        console.print(
            '[red]Keine Projekt-Metadaten.[/red] Bitte zuerst `op --load-remote-data` ausführen.'
        )
        return 2
    start = _resolve_project(args.perms_project, config) if args.perms_project else None
    if args.perms_project and start is None:
        console.print(f'[red]Projekt nicht gefunden:[/red] {args.perms_project!r}')
        return 2
    from op.tui.perms_app import PermsApp

    app = PermsApp(config=config, client=client, start_project=start)
    await app.run_async()
    return 0


def _resolve_project(token: str, config: Config) -> int | None:
    """Resolve a project token (numeric id, exact name or case-insensitive substring)."""
    projects = config.remote.projects
    if token.isdigit() and int(token) in projects:
        return int(token)
    needle = token.casefold()
    exact = [pid for pid, name in projects.items() if name.casefold() == needle]
    if exact:
        return exact[0]
    subs = [pid for pid, name in projects.items() if needle in name.casefold()]
    return subs[0] if len(subs) == 1 else (subs[0] if subs else None)


async def _initial_tasks(
    client: OpenProjectClient, query, config: Config
) -> list[WorkPackage]:
    if query.task_id is not None:
        wp = await client.get_work_package(query.task_id)
        return [wp] if wp else []
    if query.task_ids:
        return await client.get_work_packages_by_ids(query.task_ids)
    if not query.words and not query.filters and not query.empty_filters:
        return []
    filter_variants = build_api_filter_variants(query, config.remote)
    return await client.search_work_packages_variants(filter_variants=filter_variants)


def format_result_line(wp: WorkPackage, base_url: str) -> Text:
    url = f'{base_url}/work_packages/{wp.id}'
    line = Text()
    line.append(f'OP#{wp.id}', style=f'bold cyan link {url}')
    line.append(f'  {wp.subject}')
    return line


def format_task_detail(wp: WorkPackage, base_url: str) -> Group:
    url = f'{base_url}/work_packages/{wp.id}'
    header = Text()
    header.append(f'OP#{wp.id}', style=f'bold cyan link {url}')
    header.append(f'  {wp.subject}', style='bold')

    meta = Text()
    meta.append('Status: ', style='dim')
    meta.append(wp.status_name)
    meta.append('   Type: ', style='dim')
    meta.append(wp.type_name)
    meta.append('   Project: ', style='dim')
    meta.append(wp.project_name)
    if wp.priority_name:
        meta.append('   Priority: ', style='dim')
        meta.append(wp.priority_name)

    parts: list[Text] = [header, meta]
    if wp.assignee_name:
        assignee = Text()
        assignee.append('Assignee: ', style='dim')
        assignee.append(wp.assignee_name)
        parts.append(assignee)
    if wp.description:
        parts.append(Text(''))
        parts.append(Text(wp.description))
    return Group(*parts)
