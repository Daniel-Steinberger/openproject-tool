# Handoff: Commits-Sektion im OpenProject-GitLab-Tab — Implementierung

**Antwort auf:** [`spike-op-commits-gitlab.md`](./spike-op-commits-gitlab.md)
**Status:** Implementierung im OpenProject-Source abgeschlossen, lokal lauffähig, Tests grün. Frontend-Live-Reload muss einmal manuell neu gestartet werden, danach end-to-end testbar.
**Repo:** `~/src/openproject` (Fork des OpenProject-Source, Branch wurde noch nicht angelegt — Änderungen liegen aktuell uncommitted auf `dev`).
**Datum:** 2026-06-24

## Kurzfassung

Der Spike hatte gezeigt: über die OpenProject-API ist eine kompakte, dedizierte
Commit-Anzeige nicht erreichbar. Konsequenz: das Feature direkt im
OpenProject-Source ergänzen.

Umsetzung folgt dem Plan in
`~/src/openproject/docs/development/gitlab-commits-section/plan.md`:

1. **Persistenz** für Commits analog zu `GitlabMergeRequest`/`GitlabIssue`
2. **PushHook** legt zusätzlich `GitlabCommit`-Datensätze an
3. **Dedizierte Commits-Sektion** im bestehenden GitLab-Tab (unter MRs/Issues)
4. **Setting** zum optionalen Abschalten der bisherigen Push-Kommentare

Keine Änderung am Webhook-Schema. Bestehende Verhalten bleibt per Default
identisch — die neue Sektion ist additiv.

## Was im OpenProject-Repo geändert wurde

Alle Pfade relativ zu `~/src/openproject`.

### Datenmodell

- **Migration**: `modules/gitlab_integration/db/migrate/20260624180000_create_gitlab_commits.rb`
  - Tabelle `gitlab_commits` (`sha` unique, `message`, `commit_url`, `author_name`/`author_email`, `repository`, `ref`, `committed_at`, `gitlab_user_id` FK optional)
  - Join-Tabelle `gitlab_commits_work_packages`
- **Model**: `modules/gitlab_integration/app/models/gitlab_commit.rb`
  - `has_and_belongs_to_many :work_packages`, `belongs_to :gitlab_user, optional: true`
  - Helpers `short_sha`, `message_first_line`, Scope `recent_first`
- **Patches**:
  - `WorkPackage` bekommt `has_and_belongs_to_many :gitlab_commits`
    (in `lib/open_project/gitlab_integration/patches/work_package_patch.rb`)
  - `GitlabUser` bekommt `has_many :gitlab_commits`

### Ingestion

- `lib/open_project/gitlab_integration/notification_handler/push_hook.rb`:
  - Persistiert pro referenziertem Work Package einen `GitlabCommit`
    (idempotent über `sha` — `find_or_initialize_by`)
  - Kommentar-Pfad wird nur ausgeführt, wenn
    `Setting.gitlab_integration_suppress_push_comments?` falsch ist
    (Default: false → Bestandsverhalten)

### Setting

- Neue Setting-Registrierung in `engine.rb` via `Settings::Definition.add`:
  - Key: `gitlab_integration_suppress_push_comments`, Boolean, Default `false`
  - ENV-Override:
    `OPENPROJECT_GITLAB__INTEGRATION__SUPPRESS__PUSH__COMMENTS=true`
  - i18n-Label in `modules/gitlab_integration/config/locales/en.yml`

### V3-API

- `modules/gitlab_integration/lib/api/v3/gitlab_commits/gitlab_commits_by_work_package_api.rb`
  → Route `/api/v3/work_packages/:id/gitlab_commits`, sortiert `committed_at DESC`
- `gitlab_commit_representer.rb` (HAL-Felder: `sha`, `shortSha`,
  `messageFirstLine`, `message`, `commitUrl`, `authorName`, `authorEmail`,
  `repository`, `ref`, `committedAt`, `createdAt`, `updatedAt`)
- `gitlab_commit_collection_representer.rb`
- Mount + `add_api_path :gitlab_commits_by_work_package` in `engine.rb`
- Link `gitlab_commits` im WorkPackage-Representer
  (`patches/api/work_package_representer.rb`)
- Tab-Badge im Engine zählt zusätzlich `work_package.gitlab_commits.count`

### Frontend (Angular)

- Neue Komponenten:
  - `frontend/module/tab-header-commits/` (Header „COMMITS" + Sass)
  - `frontend/module/tab-commits/` (Liste + Service `wp-gitlab-commits.service.ts` + Sass)
- Templates & Typings:
  - Einbindung in `frontend/module/gitlab-tab/gitlab-tab.template.html` als
    dritte Sektion unter MRs/Issues
  - `IGitlabCommitResource` in `frontend/module/typings.d.ts`
  - `main.ts`: neue Imports, Provider, Declarations, Exports;
    `workPackageGitlabCount` zählt Commits mit
- i18n-Keys: `js.gitlab_integration.tab_header_commits.title` und
  `js.gitlab_integration.tab_commits.empty` in
  `config/locales/js-en.yml`

### Tests (alle grün, 16/16)

- `spec/models/gitlab_commit_spec.rb` (Assoziationen, Validierungen, Helpers, Scope)
- `spec/lib/open_project/gitlab_integration/notification_handler/push_hook_commits_spec.rb`
  (Persistierung idempotent, kein Commit ohne WP-Referenz, Suppress AN/AUS)
- `spec/lib/api/v3/gitlab_commits/gitlab_commit_representer_spec.rb` (HAL-JSON)
- `spec/factories/gitlab_commits.rb`

### Setup-Verifikation

- `bin/rails db:migrate` lokal durchgelaufen
- `bundle exec rspec` über die neuen Specs: **16 examples, 0 failures**
- Bestehender `push_hook_spec.rb`: **2 examples, 0 failures** (Bestandsverhalten unverändert)

## Was noch offen ist

1. **Frontend-Neustart**: Beim ersten Hochfahren erschien ein
   `NG8001: 'tab-header-commits' is not a known element`-Popup. Das ist
   Angular-Live-Reload, der das geänderte NgModule nicht inkrementell neu lädt.
   Lösung: `bin/dev` einmal stoppen und neu starten.
2. **End-to-End-Test mit echtem GitLab-Push**: noch nicht durchgeführt.
   Kann mit dem bestehenden `op commits --push` aus diesem Tool gegen
   `http://localhost:3000/webhooks/gitlab?key=<api-token>` erfolgen.
3. **GitlabUser-Verknüpfung**: Aktuell wird nur `author_name`/`author_email` am
   Commit gespeichert. Eine Auflösung auf bestehende `GitlabUser`-Records (über
   E-Mail oder push-event `user_id`) ist möglich, war aber nicht im Plan-Scope.
4. **Linting**: Rubocop/erb_lint noch nicht über die neuen Files gelaufen.
5. **Branch & Commit**: Änderungen liegen uncommitted auf `dev`. Vor einer
   Übergabe an Upstream sollte ein Feature-Branch `feature/gitlab-commits-section`
   angelegt und Commits sauber strukturiert werden.

## Bezug zu diesem Tool (openproject-tool)

`op commits --push` aus dem Spike-Branch `feature/op-commits` ist mit dieser
neuen Backend-Logik **kombinierbar als externes Backfill-Werkzeug**:

- Das Script iteriert über `git log`, baut GitLab-„Push Hook"-Payloads und
  sendet sie an `/webhooks/gitlab`.
- Mit der neuen Persistenz im OpenProject-Backend resultiert jeder so gesendete
  Commit automatisch in einem `GitlabCommit`-Datensatz und erscheint in der
  neuen Tab-Sektion. Das Tool muss dafür nicht angepasst werden.
- Damit lassen sich auch historische Commits nachträglich in die Anzeige
  bringen (das Feature selbst hat keinen automatischen Backfill, siehe Plan).

Empfehlung: den `feature/op-commits`-Branch bei der nächsten Testrunde
einmal gegen die neue Backend-Variante laufen lassen — das ist die einfachste
Möglichkeit, mehrere reale Commits gleichzeitig in die Anzeige zu bekommen.

## Upstream-Übergabe (nicht jetzt)

Sobald das Feature lokal mit echten Pushes validiert ist:

1. Feature-Request am Epic
   [#23673 — GitLab integration](https://community.openproject.org/work_packages/23673)
2. PR gegen `opf/openproject` mit Branch `feature/gitlab-commits-section`
3. Migration-Timestamp ggf. anpassen (falls jemand zwischenzeitlich eine
   höhere Nummer gemerged hat)

## Referenzen

- Plan im OpenProject-Repo: `docs/development/gitlab-commits-section/plan.md`
- Spike-Dokument (Vorgänger dieser Datei): `./spike-op-commits-gitlab.md`
- Geänderte Engine-Datei:
  `modules/gitlab_integration/lib/open_project/gitlab_integration/engine.rb`
