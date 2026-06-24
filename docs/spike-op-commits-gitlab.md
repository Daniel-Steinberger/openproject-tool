# Spike: Git-Commits am OpenProject Work Package anzeigen (`op commits`)

**Status: abgeschlossen — gewünschtes Ergebnis mit der OpenProject-API nicht erreichbar.**
Branch `feature/op-commits` (Issue #23) wird vorerst nicht nach `main` gemergt.

## Ziel

Zu einer Task die zugehörigen Git-Commits anzeigen — als **kompakte, verlinkte
Liste** (`commit <hash> <erste Zeile>`, Hash → on-prem-GitLab
`https://gitlab.dvs.ag/dvs/dvs/-/commit/<sha>`), **nicht** als gerenderter
Text-/Kommentar-Block, sondern im Stil der system-generierten Änderungszeilen
(„Projekt geändert von … zu …").

## Untersuchte Wege & Ergebnis

| Weg | Ergebnis |
|---|---|
| **Synthetische „Änderungs"-Zeile** (`Activity` mit `details`) per API | **Nicht möglich.** Diese kompakten Zeilen erzeugt OpenProject ausschließlich aus echten Feld-Änderungen. Der Activities-Endpoint akzeptiert nur `comment` (Kommentar-Block). `activities/schema` → 404. |
| **Markdown-Kommentar** (`POST .../activities`) | Funktioniert, Links rendern — aber explizit als **Textblock im Verlauf** (unerwünscht). |
| **Langtext-Custom-Field „Commits"** (`PATCH customField<id> {raw, format:markdown}`) | Funktioniert, kompakt & verlinkt, eigener Feldbereich — **erfordert aber das Anlegen eines Custom Fields** (Admin-Oberfläche; per v3-API nicht anlegbar). Aktuell nicht gewünscht/möglich. |
| **Native GitLab-Integration, Push-Event** (`POST /webhooks/gitlab?key=…`) | Funktioniert (HTTP 200) — erzeugt aber einen **Aktivitäts-Eintrag im Kommentar-Stil** (nicht kompakt). Siehe unten. |
| **GitLab-Reiter** am Work Package | Zeigt **nur Merge Requests und Issues/Tickets** (+ Pipeline-Status). **Keine** Commit-/Push-Sektion. Wird nur von MR-/Issue-Events gefüllt. |

### Entscheidender Live-Test
`op commits <sha> --push` an WP **7292** (Commit `eb9d1a3f`, Message mit `OP#7292`):
- HTTP **200**, der Commit erschien — aber als **Kommentar-Box** im Activity-Tab
  („**In refs/heads/main gepusht:** … OP#7292 …").
- Im **GitLab-Reiter**: weiterhin leer (nur „Tickets" / „Merge Requests").

→ Bestätigt: **Commits/Pushes werden in OpenProject grundsätzlich als Activity-Kommentar dargestellt; eine kompakte, dedizierte Commit-Anzeige existiert nicht.**

## Web-Recherche (Stand Juni 2026)

- Das Kommentar-Verhalten ist **dokumentiertes Standardverhalten** des Plugins:
  *„OpenProject will add comments to work package for the following events … Push commits"*.
- Der GitLab-Reiter ist **MR-/Issue-zentriert** (keine Commit-Sektion).
- **Kein** exakt passendes Feature-Request gefunden („dedizierte Commit-Sektion
  statt Kommentar"). Nächstliegend: btey-Issue #34 (Issues im Reiter anzeigen).

Quellen:
- GitLab integration – OpenProject (Admin-Doku): <https://www.openproject.org/docs/system-admin-guide/integrations/gitlab-integration/>
- opf/openproject-gitlab-integration README: <https://github.com/opf/openproject-gitlab-integration/blob/master/README.md>
- btey-Issue #34 – Show referenced issues in GitLab tab: <https://github.com/btey/openproject-gitlab-integration/issues/34>
- Epic #23673 – GitLab integration: <https://community.openproject.org/work_packages/23673>
- Feature #53969 – Log time via commit message: <https://community.openproject.org/work_packages/53969>
- Bug #53774 – GitLab Integration still blank: <https://community.openproject.org/journals/566471/diff/description>

## Fazit

Die Kombination **„Commits + kompakt + nicht als Kommentar/Box"** ist mit der
OpenProject-API **nicht** umsetzbar. Sinnvoll wäre ein **Feature-Request** im
Epic #23673 (dedizierte Commit-Anzeige im GitLab-Reiter). Falls eine kompakte,
selbst kontrollierte Darstellung doch akzeptabel ist, bleibt das
**Custom-Field „Commits"** der gangbare Weg (sobald das Feld anlegbar ist).

## Was der Spike hinterlässt (Branch `feature/op-commits`, nicht gemergt)

`op commits [<range|sha>] [--repo PATH] [--dry-run] [--comment] [--push]`:
- liest lokales `git log` (Repo aus `$PWD` bzw. `--repo`; wichtig, da `op` via
  `uv --directory` läuft), findet `#<id>`/`OP#<id>`-Referenzen, gruppiert nach Task;
- `--dry-run`: rein lokale Vorschau (kein API/Feld);
- `--comment`: Markdown-Kommentar;
- Custom-Field-Schreiben (`set_custom_field_text`, additiv, dedupe per Hash);
- `--push`: vollständiges GitLab-„Push Hook"-Payload an `/webhooks/gitlab` (`[gitlab] webhook_token`).

Code: `src/op/commits.py`, `op commits`-Zweig in `src/op/cli.py`,
`OpenProjectClient.set_custom_field_text`/`send_gitlab_push`, `GitlabConfig`.
Tests: `tests/test_commits*.py`.
