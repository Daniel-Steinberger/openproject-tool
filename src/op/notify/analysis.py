"""Map-reduce over the notification groups.

Map: one model call per work package, answered as JSON. Reduce: one call over
all results for the closing report. A group that fails keeps its place in the
output with an `error` — losing a work package silently is the one outcome this
tool must not produce.
"""

from __future__ import annotations

import asyncio
import logging
import typing as T

from pydantic import BaseModel, Field

from op.models import Activity, WorkPackage
from op.notify.cache import AnalysisCache
from op.notify.llm import LlmError
from op.notify.models import NotificationGroup
from op.notify.prompts import GROUP_SCHEMA, build_group_messages, build_report_messages
from op.notify.render import render_group

log = logging.getLogger('op.notify.analysis')

CLASSIFICATIONS = ('relevant', 'worth_knowing', 'churn')
# Anything the model invents lands here: visible, but never silently cleared.
_FALLBACK_CLASSIFICATION = 'worth_knowing'

_EMPTY_REPORT = 'Keine ungelesenen Benachrichtigungen.'


class GroupAnalysis(BaseModel):
    work_package_id: int | None
    title: str
    classification: str
    summary: str
    open_points: list[str] = Field(default_factory=list)
    waits_for_me: bool = False
    rationale: str = ''
    notification_ids: list[int] = Field(default_factory=list)
    project_name: str | None = None
    count: int = 0
    latest: str | None = None
    cached: bool = False
    error: str | None = None
    # The rendered activity block the analysis was made from — shown in the TUI
    # detail view so the summary can be checked against its source.
    block: str = ''

    @property
    def is_churn(self) -> bool:
        return self.classification == 'churn' and not self.error


class _OpLike(T.Protocol):
    async def get_work_package(self, wp_id: int) -> WorkPackage | None: ...
    async def get_activities(self, wp_id: int) -> list[Activity]: ...


class _LlmLike(T.Protocol):
    model: str

    async def complete_json(
        self, *, system: str, user: str, schema: dict[str, T.Any], **kwargs: T.Any
    ) -> dict[str, T.Any]: ...

    async def complete_text(self, *, system: str, user: str) -> str: ...


async def analyse_groups(
    groups: list[NotificationGroup],
    *,
    op: _OpLike,
    llm: _LlmLike,
    user_name: str,
    cache: AnalysisCache,
    own_user_id: int | None = None,
    hide_own: bool = True,
    user_names: dict[int, str] | None = None,
    extra_instructions: str = '',
) -> list[GroupAnalysis]:
    """Analyse every group, preserving the input order."""
    results = await asyncio.gather(*(
        _analyse_one(
            group, op=op, llm=llm, user_name=user_name, cache=cache,
            own_user_id=own_user_id, hide_own=hide_own, user_names=user_names or {},
            extra_instructions=extra_instructions,
        )
        for group in groups
    ))
    return list(results)


async def render_blocks(
    groups: list[NotificationGroup],
    *,
    op: _OpLike,
    own_user_id: int | None = None,
    hide_own: bool = True,
    user_names: dict[int, str] | None = None,
) -> dict[int, str]:
    """Activity blocks without any model involved — used by `--no-llm`."""
    blocks = await asyncio.gather(*(
        _render(group, op=op, own_user_id=own_user_id, hide_own=hide_own,
                user_names=user_names or {})
        for group in groups
    ))
    return {
        group.work_package_id: block
        for group, block in zip(groups, blocks, strict=True)
        if group.work_package_id is not None
    }


async def build_report(
    analyses: list[GroupAnalysis], *, llm: _LlmLike, user_name: str, extra_instructions: str = ''
) -> str:
    """Fold the per-group results into one report. Raises on model failure."""
    if not analyses:
        return _EMPTY_REPORT
    payload = [
        {
            'work_package_id': a.work_package_id,
            'title': a.title,
            'classification': a.classification,
            'summary': a.summary,
            'open_points': a.open_points,
            'waits_for_me': a.waits_for_me,
        }
        for a in analyses
    ]
    system, user = build_report_messages(
        payload, user_name=user_name, extra_instructions=extra_instructions
    )
    return await llm.complete_text(system=system, user=user)


async def _analyse_one(
    group: NotificationGroup,
    *,
    op: _OpLike,
    llm: _LlmLike,
    user_name: str,
    cache: AnalysisCache,
    own_user_id: int | None,
    hide_own: bool,
    user_names: dict[int, str],
    extra_instructions: str,
) -> GroupAnalysis:
    block = await _render(
        group, op=op, own_user_id=own_user_id, hide_own=hide_own, user_names=user_names
    )
    system, user = build_group_messages(
        block=block, user_name=user_name, extra_instructions=extra_instructions
    )
    key = AnalysisCache.key_for(group, model=llm.model, prompt=system)

    cached = cache.get(key)
    if cached is not None:
        return _to_analysis(group, cached, cached_hit=True, block=block)

    try:
        answer = await llm.complete_json(system=system, user=user, schema=GROUP_SCHEMA)
    except LlmError as exc:
        log.warning('analysis failed for work package %s: %s', group.work_package_id, exc)
        return _failed(group, str(exc), block=block)

    # Only successful answers are cached — a failure must be retried next run.
    cache.set(key, answer)
    return _to_analysis(group, answer, cached_hit=False, block=block)


async def _render(
    group: NotificationGroup,
    *,
    op: _OpLike,
    own_user_id: int | None,
    hide_own: bool,
    user_names: dict[int, str],
) -> str:
    if group.work_package_id is None:
        return render_group(group, None, [], own_user_id=own_user_id, hide_own=hide_own,
                            user_names=user_names)
    work_package, activities = await asyncio.gather(
        op.get_work_package(group.work_package_id),
        op.get_activities(group.work_package_id),
    )
    return render_group(
        group, work_package, activities,
        own_user_id=own_user_id, hide_own=hide_own, user_names=user_names,
    )


def _to_analysis(
    group: NotificationGroup, answer: dict[str, T.Any], *, cached_hit: bool, block: str = ''
) -> GroupAnalysis:
    classification = answer.get('classification')
    if classification not in CLASSIFICATIONS:
        classification = _FALLBACK_CLASSIFICATION
    return GroupAnalysis(
        work_package_id=group.work_package_id,
        # The title comes from the API, never from the model.
        title=group.title,
        classification=classification,
        summary=str(answer.get('summary') or ''),
        open_points=[str(p) for p in answer.get('open_points') or []],
        waits_for_me=bool(answer.get('waits_for_me')),
        rationale=str(answer.get('rationale') or ''),
        notification_ids=group.notification_ids,
        project_name=group.project_name,
        count=group.count,
        latest=group.latest,
        cached=cached_hit,
        block=block,
    )


def _failed(group: NotificationGroup, message: str, *, block: str = '') -> GroupAnalysis:
    return GroupAnalysis(
        work_package_id=group.work_package_id,
        title=group.title,
        classification=_FALLBACK_CLASSIFICATION,
        summary='Analyse fehlgeschlagen — Inhalt ungeprüft.',
        notification_ids=group.notification_ids,
        project_name=group.project_name,
        count=group.count,
        latest=group.latest,
        error=message,
        block=block,
    )
