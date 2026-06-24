from __future__ import annotations

from op.commits import (
    Commit,
    build_push_payload,
    commit_markdown_line,
    commit_url,
    git_log_command,
    merge_commit_lines,
    parse_git_log,
    parse_task_refs,
)

BASE = 'https://gitlab.dvs.ag'
PROJ = 'dvs/dvs'


class TestParseTaskRefs:
    def test_plain_hash(self) -> None:
        assert parse_task_refs('Fix login #7190') == {7190}

    def test_op_prefix(self) -> None:
        assert parse_task_refs('OP#7190 done') == {7190}

    def test_multiple_and_dedup(self) -> None:
        assert parse_task_refs('#1 and OP#2 and #1') == {1, 2}

    def test_none(self) -> None:
        assert parse_task_refs('no refs here') == set()


class TestMarkdown:
    def test_commit_url(self) -> None:
        assert commit_url('ec18df40', BASE, PROJ) == \
            'https://gitlab.dvs.ag/dvs/dvs/-/commit/ec18df40'

    def test_line(self) -> None:
        c = Commit('ec18df40a2', 'ec18df4', 'Fix thing', {7190})
        assert commit_markdown_line(c, BASE, PROJ) == \
            '- [ec18df4](https://gitlab.dvs.ag/dvs/dvs/-/commit/ec18df40a2) Fix thing'


class TestParseGitLog:
    def test_parses_records(self) -> None:
        raw = (
            'FULL1\x1fshort1\x1fSubject one OP#10\x1fbody line\x1e'
            'FULL2\x1fshort2\x1fSubject two\x1f#11 in body\x1e'
        )
        commits = parse_git_log(raw)
        assert [c.short_sha for c in commits] == ['short1', 'short2']
        assert commits[0].task_ids == {10}
        assert commits[1].task_ids == {11}


class TestMerge:
    def test_appends_new_and_dedups(self) -> None:
        c1 = Commit('aaa111', 'aaa', 'first', {1})
        c2 = Commit('bbb222', 'bbb', 'second', {1})
        existing = '- [aaa](https://gitlab.dvs.ag/dvs/dvs/-/commit/aaa111) first'
        merged, added = merge_commit_lines(existing, [c1, c2], BASE, PROJ)
        assert [a.full_sha for a in added] == ['bbb222']
        assert 'aaa111' in merged and 'bbb222' in merged
        assert merged.count('aaa111') == 1  # not duplicated

    def test_empty_existing(self) -> None:
        c1 = Commit('aaa111', 'aaa', 'first', {1})
        merged, added = merge_commit_lines('', [c1], BASE, PROJ)
        assert merged == '- [aaa](https://gitlab.dvs.ag/dvs/dvs/-/commit/aaa111) first'
        assert len(added) == 1

    def test_nothing_new_returns_existing(self) -> None:
        c1 = Commit('aaa111', 'aaa', 'first', {1})
        existing = '- [aaa](https://gitlab.dvs.ag/dvs/dvs/-/commit/aaa111) first'
        merged, added = merge_commit_lines(existing, [c1], BASE, PROJ)
        assert merged == existing and added == []


class TestGitLogCommand:
    def test_range(self) -> None:
        cmd = git_log_command('HEAD~5..HEAD')
        assert cmd[:3] == ['git', 'log', 'HEAD~5..HEAD'] and '-1' not in cmd

    def test_single_commit(self) -> None:
        cmd = git_log_command('44836a9')
        assert '-1' in cmd and '44836a9' in cmd


class TestPushPayload:
    def test_payload_shape(self) -> None:
        c = Commit('ec18df40a2', 'ec18df4', 'Fix OP#7190', {7190})
        p = build_push_payload([c], BASE, PROJ)
        assert p['object_kind'] == 'push'
        assert p['project']['web_url'] == 'https://gitlab.dvs.ag/dvs/dvs'
        assert p['total_commits_count'] == 1
        commit = p['commits'][0]
        assert commit['id'] == 'ec18df40a2'
        assert commit['message'] == 'Fix OP#7190'
        assert commit['url'] == 'https://gitlab.dvs.ag/dvs/dvs/-/commit/ec18df40a2'
