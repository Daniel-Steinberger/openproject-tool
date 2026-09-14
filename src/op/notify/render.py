"""Turn a notification group into the text block the model reads.

Two things matter here. First, comments arrive as OpenProject's WYSIWYG markup
(`<mention>`, `<details>` blocks from commit bots, HTML entities) — raw, that is
mostly noise. Second, the block must stay readable as *data*: it is quoted third
party text, and the prompt says so explicitly (see `prompts.py`).
"""

from __future__ import annotations

import html
import re

from op.models import Activity, WorkPackage
from op.notify.models import NotificationGroup

_DEFAULT_MAX_COMMENT_CHARS = 1200

_MENTION_RE = re.compile(r'<mention\b[^>]*>(.*?)</mention>', flags=re.DOTALL | re.IGNORECASE)
# Commit bots post <details><summary>headline</summary>full message</details>.
# The headline carries the information, the body repeats the commit text.
_DETAILS_RE = re.compile(
    r'<details\b[^>]*>\s*<summary\b[^>]*>(.*?)</summary>.*?(?:</details>|$)',
    flags=re.DOTALL | re.IGNORECASE,
)
_TAG_RE = re.compile(r'<[^>]+>')
_WHITESPACE_RE = re.compile(r'\s+')


def clean_comment(raw: str | None, *, max_chars: int = _DEFAULT_MAX_COMMENT_CHARS) -> str:
    """Reduce a comment to plain, single-spaced text.

    Mentions keep their handle, `<details>` blocks shrink to their summary, and
    anything longer than `max_chars` is cut — a 5 000 character commit dump adds
    nothing to a classification that hinges on the first two sentences.
    """
    if not raw:
        return ''
    text = _DETAILS_RE.sub(lambda m: m.group(1), raw)
    text = _MENTION_RE.sub(lambda m: m.group(1), text)
    text = _TAG_RE.sub('', text)
    text = html.unescape(text)
    text = text.replace('\xa0', ' ')
    text = _WHITESPACE_RE.sub(' ', text).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + ' …'
    return text


def render_group(
    group: NotificationGroup,
    work_package: WorkPackage | None,
    activities: list[Activity],
    *,
    own_user_id: int | None = None,
    hide_own: bool = True,
    max_comment_chars: int = _DEFAULT_MAX_COMMENT_CHARS,
) -> str:
    """Render one group as a Markdown block: header facts plus activity log."""
    lines = [f'## Work package #{group.work_package_id or "?"} — {group.title}']
    lines.extend(_header_lines(group, work_package))
    lines.append('')

    relevant = [a for a in activities if a.id in set(group.activity_ids)]
    relevant.sort(key=lambda a: (a.created_at or '', a.id))

    rendered = 0
    for activity in relevant:
        is_own = own_user_id is not None and activity.user_id == own_user_id
        if is_own and hide_own:
            continue
        lines.extend(_activity_lines(activity, is_own=is_own, max_chars=max_comment_chars))
        rendered += 1

    if not rendered:
        lines.append(
            '- (keine fremden Aktivitäten — alle Einträge dieser Gruppe sind eigene Aktionen)'
            if relevant
            else '- (keine Aktivitäten abrufbar)'
        )
    return '\n'.join(lines)


def _header_lines(group: NotificationGroup, work_package: WorkPackage | None) -> list[str]:
    reasons = ', '.join(f'{reason} ×{count}' for reason, count in group.reason_counts.items())
    lines = [
        f'- Projekt: {group.project_name or "?"}',
        f'- Benachrichtigungen: {group.count} ({reasons})',
        f'- Beteiligte: {", ".join(group.actors) or "?"}',
        f'- Zeitraum: {_short(group.earliest)} bis {_short(group.latest)}',
    ]
    if work_package is not None:
        lines.extend([
            f'- Typ/Status: {work_package.type_name} / {work_package.status_name}',
            f'- Verantwortlich: {work_package.responsible_name or "—"}',
            f'- Zugewiesen an: {work_package.assignee_name or "—"}',
        ])
    return lines


def _activity_lines(activity: Activity, *, is_own: bool, max_chars: int) -> list[str]:
    who = activity.user_name or '?'
    marker = ' (selbst ausgelöst)' if is_own else ''
    lines = [f'- [{_short(activity.created_at)}] {who}{marker}']
    for detail in activity.details:
        lines.append(f'  - Änderung: {clean_comment(detail, max_chars=max_chars)}')
    comment = clean_comment(activity.comment, max_chars=max_chars)
    if comment:
        lines.append(f'  - Kommentar: {comment}')
    return lines


def _short(timestamp: str | None) -> str:
    """`2026-09-14T10:32:00.143Z` → `2026-09-14 10:32`."""
    if not timestamp:
        return '?'
    return timestamp[:16].replace('T', ' ')
