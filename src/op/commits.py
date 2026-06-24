"""Pure helpers for the `op commits` spike — parse git log, build GitLab-linked
markdown lines, and merge them additively into an existing field value.

The tool reads the *local* git log; the GitLab base URL is only used to build
the commit links (no GitLab API call). Commits are attached to a work package
when their message references it as ``#<id>`` or ``OP#<id>``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Record/field separators used in our `git log --format=...` calls.
# Fields: full sha, short sha, subject, committer-date (ISO), author name, author email, body.
GIT_LOG_FORMAT = '%H%x1f%h%x1f%s%x1f%cI%x1f%an%x1f%ae%x1f%b%x1e'
_REC_SEP = '\x1e'
_FIELD_SEP = '\x1f'
_NULL_SHA = '0' * 40

_TASK_REF_RE = re.compile(r'(?:OP)?#(\d+)', re.IGNORECASE)


@dataclass
class Commit:
    full_sha: str
    short_sha: str
    subject: str
    task_ids: set[int] = field(default_factory=set)
    timestamp: str = ''
    author_name: str = ''
    author_email: str = ''


def parse_task_refs(message: str) -> set[int]:
    """Work-package ids referenced as `#123` or `OP#123` (case-insensitive)."""
    return {int(m) for m in _TASK_REF_RE.findall(message or '')}


def parse_git_log(raw: str) -> list[Commit]:
    """Parse output produced with GIT_LOG_FORMAT into Commit objects."""
    commits: list[Commit] = []
    for record in raw.split(_REC_SEP):
        record = record.strip('\n')
        if not record:
            continue
        parts = record.split(_FIELD_SEP)
        if len(parts) < 7:
            continue
        full, short, subject, ts, an, ae, body = parts[:7]
        refs = parse_task_refs(f'{subject}\n{body}')
        commits.append(Commit(
            full.strip(), short.strip(), subject.strip(), refs,
            timestamp=ts.strip(), author_name=an.strip(), author_email=ae.strip(),
        ))
    return commits


DEFAULT_MAX_COUNT = 50


def git_log_command(range_or_rev: str | None) -> list[str]:
    """git log args for the default (last N commits), a range (`a..b`) or a
    single revision (sha). A count-based default works even in repos with very
    few commits (where `HEAD~50..HEAD` would fail)."""
    fmt = f'--format={GIT_LOG_FORMAT}'
    if not range_or_rev:
        return ['git', 'log', '-n', str(DEFAULT_MAX_COUNT), fmt]
    if '..' in range_or_rev:
        return ['git', 'log', range_or_rev, fmt]
    return ['git', 'log', '-1', range_or_rev, fmt]


def commit_url(full_sha: str, base_url: str, project: str) -> str:
    return f'{base_url.rstrip("/")}/{project.strip("/")}/-/commit/{full_sha}'


def commit_markdown_line(commit: Commit, base_url: str, project: str) -> str:
    """A single markdown bullet: `- [<short>](<url>) <subject>`."""
    url = commit_url(commit.full_sha, base_url, project)
    return f'- [{commit.short_sha}]({url}) {commit.subject}'


_FALLBACK_TS = '2024-01-01T00:00:00+00:00'


def build_push_payload(
    commits: list[Commit], base_url: str, project: str,
    *, ref: str = 'refs/heads/main', user_name: str = 'op-commits',
    project_id: int = 1,
) -> dict:
    """A complete GitLab 'Push Hook' payload (matching GitLab's real format, so
    OpenProject's integration doesn't choke). OpenProject scans each commit
    message for OP#<id> and links it to that work package."""
    base = base_url.rstrip('/')
    ns = project.strip('/')
    repo = f'{base}/{ns}'
    name = ns.split('/')[-1]
    git_http = f'{repo}.git'
    head = commits[0].full_sha if commits else _NULL_SHA
    author_email = next((c.author_email for c in commits if c.author_email), 'op-commits@local')

    return {
        'object_kind': 'push',
        'event_name': 'push',
        'before': _NULL_SHA,
        'after': head,
        'ref': ref,
        'ref_protected': False,
        'checkout_sha': head,
        'message': None,
        'user_id': 0,
        'user_name': user_name,
        'user_username': user_name,
        'user_email': author_email,
        'user_avatar': None,
        'project_id': project_id,
        'project': {
            'id': project_id,
            'name': name,
            'description': '',
            'web_url': repo,
            'avatar_url': None,
            'git_ssh_url': f'git@{ns}.git',
            'git_http_url': git_http,
            'namespace': ns.split('/')[0] if '/' in ns else ns,
            'visibility_level': 0,
            'path_with_namespace': ns,
            'default_branch': 'main',
            'homepage': repo,
            'url': git_http,
            'ssh_url': f'git@{ns}.git',
            'http_url': git_http,
        },
        'commits': [
            {
                'id': c.full_sha,
                'message': c.subject,
                'title': c.subject,
                'timestamp': c.timestamp or _FALLBACK_TS,
                'url': commit_url(c.full_sha, base_url, project),
                'author': {
                    'name': c.author_name or user_name,
                    'email': c.author_email or 'op-commits@local',
                },
                'added': [],
                'modified': [],
                'removed': [],
            }
            for c in commits
        ],
        'total_commits_count': len(commits),
        'repository': {
            'name': name,
            'url': git_http,
            'description': '',
            'homepage': repo,
            'git_http_url': git_http,
            'git_ssh_url': f'git@{ns}.git',
            'visibility_level': 0,
        },
    }


def merge_commit_lines(
    existing_raw: str, commits: list[Commit], base_url: str, project: str
) -> tuple[str, list[Commit]]:
    """Append markdown lines for commits whose full sha is not already present.

    Returns (new_field_value, newly_added_commits). Order: existing kept, new
    commits appended in the given order. Idempotent — re-running adds nothing.
    """
    existing = existing_raw or ''
    added: list[Commit] = []
    new_lines: list[str] = []
    for c in commits:
        if c.full_sha and c.full_sha in existing:
            continue
        if any(c.full_sha == a.full_sha for a in added):
            continue
        added.append(c)
        new_lines.append(commit_markdown_line(c, base_url, project))
    if not new_lines:
        return existing, []
    combined = '\n'.join([existing.rstrip('\n')] + new_lines) if existing.strip() else '\n'.join(new_lines)
    return combined, added
