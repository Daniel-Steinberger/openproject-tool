from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shlex
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

log = logging.getLogger(__name__)

from rich.console import Console, Group
from rich.text import Text

from op.actions import load_remote_data
from op.api import AuthError, OpenProjectClient, OpenProjectError
from op.commits import (
    build_push_payload,
    commit_markdown_line,
    git_log_command,
    merge_commit_lines,
    parse_git_log,
)
from op.config import Config, DefaultsConfig, default_config_path, get_api_key, load_config
from op.html_to_markdown import html_to_markdown
from op.logging_setup import setup_logging
from op.models import WorkPackage
from op.search import FILTER_KEYS, build_api_filter_variants, parse
from op.tui.app import OpApp
from op.tui.perms_app import PermsApp


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


# Sub-modes dispatched by the first positional token (before the query parser).
# Listed in --help via the epilog since argparse itself doesn't know them.
_MODES: list[tuple[str, str]] = [
    ('perms [projekt]', 'Berechtigungs-Tool (eigener TUI-Modus): Projekt-/Gruppensicht, '
                        'Übertragen, Hierarchie angleichen, Benutzerverwaltung.'),
    ('commits [range]', 'Git-Commits (mit OP#<id>/#<id> in der Message) verlinkt ans '
                        'Work Package schreiben. Optionen: --dry-run, --comment.'),
]


def _modes_epilog() -> str:
    lines = ['Modi (als erstes Argument statt einer Suchanfrage):']
    for name, desc in _MODES:
        lines.append(f'  op {name:18} {desc}')
    lines.append("\nHilfe zu einem Modus: z. B. `op perms --help`.")
    return '\n'.join(lines)


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

    if argv and argv[0] == 'commits':
        cm = argparse.ArgumentParser(prog='op commits')
        cm.add_argument('range', nargs='?', default='HEAD~50..HEAD',
                        help='git-Range (z.B. HEAD~50..HEAD) ODER ein einzelner Commit (SHA).')
        cm.add_argument('--repo', default=None,
                        help='Pfad zum git-Repository (Default: aktuelles Verzeichnis).')
        cm.add_argument('--dry-run', action='store_true', help='Nur anzeigen, nichts schreiben')
        cm.add_argument('--comment', action='store_true',
                        help='Als Kommentar statt ins "Commits"-Custom-Field schreiben')
        cm.add_argument('--push', action='store_true',
                        help='Commits als GitLab-Push-Event an die OpenProject-Integration '
                             'senden (Vorschau ohne echten Webhook). Braucht [gitlab] webhook_token.')
        ns = cm.parse_args(argv[1:])
        return argparse.Namespace(
            command='commits', commits_range=ns.range, commits_repo=ns.repo,
            commits_dry_run=ns.dry_run, commits_comment=ns.comment, commits_push=ns.push,
            load_remote_data=False, interactive=False, query=[],
        )

    parser = argparse.ArgumentParser(
        prog='op',
        description='Fast, keyboard-driven CLI and TUI for OpenProject.',
        epilog=_modes_epilog(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
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
        '--config',
        action='store_true',
        help=f'Open the config file ({_highlight_path(default_config_path())}) in $EDITOR.',
    )
    parser.add_argument(
        'query',
        nargs='*',
        help=_build_query_help(defaults),
    )
    return parser.parse_args(argv)


def _highlight_path(path: Path) -> str:
    """Cyan-highlight a path for --help, but only on a TTY (plain when piped)."""
    text = str(path)
    if sys.stdout.isatty():
        return f'\033[36m{text}\033[0m'
    return text


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


def _open_config_in_editor(path: Path, console: Console) -> int:
    """Open the config file in $EDITOR (creating it from the template if absent)."""
    if not path.exists():
        try:
            load_config(path)  # writes the default template when the file is missing
        except Exception:  # noqa: BLE001
            pass
    editor = (
        os.environ.get('EDITOR')
        or os.environ.get('VISUAL')
        or shutil.which('nano')
        or shutil.which('vi')
        or 'vi'
    )
    console.print(f'Öffne Config-Datei: [cyan]{path}[/cyan]')
    try:
        subprocess.run([*shlex.split(editor), str(path)], check=False)
    except FileNotFoundError:
        console.print(
            f'[yellow]Kein Editor gefunden[/yellow] ($EDITOR nicht gesetzt). '
            f'Config-Datei: [cyan]{path}[/cyan]'
        )
    return 0


async def run(
    args: argparse.Namespace,
    *,
    config: Config | None = None,
    config_path: Path | None = None,
    console: Console | None = None,
) -> int:
    console = console or Console()
    if getattr(args, 'config', False):
        return _open_config_in_editor(config_path or default_config_path(), console)
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

        if getattr(args, 'command', None) == 'commits':
            return await _run_commits(args, client, config, console)

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
    app = PermsApp(config=config, client=client, start_project=start)
    await app.run_async()
    return 0


async def _run_commits(
    args: argparse.Namespace,
    client: OpenProjectClient,
    config: Config,
    console: Console,
) -> int:
    """Attach git commits (referencing OP#<id>/#<id>) to their work packages."""
    gl = config.gitlab
    if not gl.is_configured:
        console.print(
            '[red]GitLab nicht konfiguriert.[/red] Bitte [gitlab] base_url und project '
            'in der config.toml setzen.'
        )
        return 2

    # The "Commits" custom field is only required for a real CF write. Dry-run is
    # a pure local preview (no API, no field); --comment and --push don't need it.
    cf_id = next(
        (cid for cid, name in config.remote.custom_fields.items()
         if name.strip().lower() == 'commits'),
        None,
    )
    needs_cf = not (args.commits_dry_run or args.commits_comment or args.commits_push)
    if needs_cf and cf_id is None:
        console.print(
            '[red]Kein Custom Field "Commits" gefunden.[/red] In OpenProject als '
            'Langtext-CF anlegen, dann `op --load-remote-data`. Oder `--comment` / '
            '`--push` / `--dry-run` nutzen.'
        )
        return 2

    # `op` is often run via `uv --directory <tool> run op`, which changes the
    # process cwd to the tool repo. The user's actual directory survives in $PWD.
    repo = args.commits_repo or os.environ.get('PWD') or os.getcwd()
    try:
        out = subprocess.run(
            git_log_command(args.commits_range),
            capture_output=True, text=True, check=True, cwd=repo,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        console.print(
            f'[red]git log fehlgeschlagen[/red] (repo: [cyan]{repo}[/cyan]): {exc}. '
            f'Ggf. `--repo <pfad>` angeben.'
        )
        return 2

    commits = parse_git_log(out)
    by_task: dict[int, list] = defaultdict(list)
    for c in commits:
        for tid in c.task_ids:
            by_task[tid].append(c)
    if not by_task:
        console.print(
            f'Keine Commits mit Task-Referenz (#id / OP#id) gefunden '
            f'(repo: [cyan]{repo}[/cyan], range: {args.commits_range}).'
        )
        return 0

    base, proj = gl.base_url, gl.project

    # Dry-run: pure local preview — no API calls, no field needed.
    if args.commits_dry_run:
        console.print(
            f'[dim](dry-run — es wird nichts geschrieben; repo {repo}, range '
            f'{args.commits_range})[/dim]'
        )
        for task_id, task_commits in sorted(by_task.items()):
            console.print(f'[cyan]#{task_id}[/cyan] ({len(task_commits)}):')
            for c in task_commits:
                # markup=False: the markdown link `[<sha>](…)` must not be eaten by Rich.
                console.print('  ' + commit_markdown_line(c, base, proj), markup=False)
        return 0

    # --push: send a synthetic GitLab push event to OpenProject's integration
    # webhook (preview without configuring a real GitLab webhook).
    if args.commits_push:
        token = gl.resolved_webhook_token()
        if not token:
            console.print(
                '[red]Kein GitLab-Webhook-Token.[/red] [gitlab] webhook_token in der '
                'config.toml setzen (oder Env OP_GITLAB_WEBHOOK_TOKEN).'
            )
            return 2
        all_commits = [c for cs in by_task.values() for c in cs]
        # de-dup by sha, preserve order
        seen: set[str] = set()
        unique = [c for c in all_commits if not (c.full_sha in seen or seen.add(c.full_sha))]
        payload = build_push_payload(unique, base, proj)
        status, text = await client.send_gitlab_push(
            webhook_token=token, payload=payload, secret=gl.webhook_secret or None,
        )
        if 200 <= status < 300:
            console.print(
                f'[green]Push gesendet[/green] ({len(unique)} Commit(s), HTTP {status}). '
                f'Tasks: {", ".join(f"#{t}" for t in sorted(by_task))}. In OpenProject prüfen.'
            )
            return 0
        console.print(f'[red]Webhook abgelehnt (HTTP {status}).[/red]')
        body = text.strip()
        if '<html' in body[:2000].lower():
            body = html_to_markdown(body).strip()
        console.print(body or '(leere Antwort)')
        if status >= 500:
            console.print(
                '[dim]HTTP 500 = serverseitige Exception in OpenProject beim Verarbeiten '
                'des Push-Events. Die genaue Ursache steht in den OpenProject-Server-Logs '
                '(z.B. docker logs / /var/log) — die HTML-Seite zeigt sie nicht.[/dim]'
            )
        return 1

    for task_id, task_commits in sorted(by_task.items()):
        wp = await client.get_work_package(task_id)
        if wp is None:
            console.print(f'[yellow]#{task_id} nicht gefunden — übersprungen.[/yellow]')
            continue
        if args.commits_comment:
            body = '\n'.join(commit_markdown_line(c, base, proj) for c in task_commits)
            await client.add_comment(task_id, body)
            console.print(f'[green]#{task_id}[/green]: {len(task_commits)} Commit(s) als Kommentar.')
            continue
        existing = wp.custom_field_text(cf_id)
        merged, added = merge_commit_lines(existing, task_commits, base, proj)
        if not added:
            console.print(f'#{task_id}: nichts Neues.')
            continue
        await client.set_custom_field_text(
            task_id, lock_version=wp.lock_version, cf_id=cf_id, markdown=merged
        )
        console.print(f'[green]#{task_id}[/green]: {len(added)} neue(r) Commit(s) ergänzt.')
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
