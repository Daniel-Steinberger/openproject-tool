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
GIT_LOG_FORMAT = '%H%x1f%h%x1f%s%x1f%b%x1e'
_REC_SEP = '\x1e'
_FIELD_SEP = '\x1f'

_TASK_REF_RE = re.compile(r'(?:OP)?#(\d+)', re.IGNORECASE)


@dataclass
class Commit:
    full_sha: str
    short_sha: str
    subject: str
    task_ids: set[int] = field(default_factory=set)


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
        if len(parts) < 4:
            continue
        full, short, subject, body = parts[0], parts[1], parts[2], parts[3]
        refs = parse_task_refs(f'{subject}\n{body}')
        commits.append(Commit(full.strip(), short.strip(), subject.strip(), refs))
    return commits


def git_log_command(range_or_rev: str) -> list[str]:
    """git log args for either a range (`a..b`) or a single revision (sha)."""
    if '..' in range_or_rev:
        return ['git', 'log', range_or_rev, f'--format={GIT_LOG_FORMAT}']
    return ['git', 'log', '-1', range_or_rev, f'--format={GIT_LOG_FORMAT}']


def commit_url(full_sha: str, base_url: str, project: str) -> str:
    return f'{base_url.rstrip("/")}/{project.strip("/")}/-/commit/{full_sha}'


def commit_markdown_line(commit: Commit, base_url: str, project: str) -> str:
    """A single markdown bullet: `- [<short>](<url>) <subject>`."""
    url = commit_url(commit.full_sha, base_url, project)
    return f'- [{commit.short_sha}]({url}) {commit.subject}'


def build_push_payload(
    commits: list[Commit], base_url: str, project: str,
    *, ref: str = 'refs/heads/main', user_name: str = 'op-commits',
) -> dict:
    """Minimal GitLab 'Push Hook' payload. OpenProject's GitLab integration scans
    each commit message for OP#<id> and links it to that work package."""
    repo = f'{base_url.rstrip("/")}/{project.strip("/")}'
    return {
        'object_kind': 'push',
        'event_name': 'push',
        'ref': ref,
        'user_name': user_name,
        'project': {
            'id': 0,
            'name': project.rstrip('/').split('/')[-1],
            'path_with_namespace': project.strip('/'),
            'web_url': repo,
            'http_url': f'{repo}.git',
        },
        'repository': {'name': project.strip('/'), 'homepage': repo, 'url': f'{repo}.git'},
        'commits': [
            {
                'id': c.full_sha,
                'message': c.subject,
                'title': c.subject,
                'timestamp': '',
                'url': commit_url(c.full_sha, base_url, project),
                'author': {'name': user_name, 'email': 'op-commits@local'},
            }
            for c in commits
        ],
        'total_commits_count': len(commits),
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
