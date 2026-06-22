# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Tests ausführen
pytest                        # alle Tests
pytest tests/test_api.py      # einzelne Datei
pytest tests/test_api.py::test_name  # einzelner Test
pytest -x                     # bei erstem Fehler abbrechen

# TUI starten (interaktiv)
op -i [query]

# Metadaten vom Server laden (befüllt [remote.*] in Config)
op --load-remote-data

# Paket installieren (entwicklungsmodus)
pip install -e .
```

`pytest-asyncio` ist mit `asyncio_mode = "auto"` konfiguriert – alle `async def test_*`-Funktionen werden automatisch erkannt.

HTTP-Requests werden in Tests mit `respx` gemockt.

## Architektur

**Schichten (von oben nach unten):**

```
cli.py          → Argparse, Rich-Terminal-Output, Einstiegspunkt `op`
search.py       → Query-Parsing: ID / Worte / key=value Filter → OpenProject-JSON-Filter
tui/app.py      → Textual Root-App, AppState-Enum (SELECTOR/DETAIL/REVIEW/APPLYING)
tui/*.py        → Textual Screens und Modals (Screen-Stack)
api.py          → httpx Async-Client für OpenProject v3 REST API
models.py       → Pydantic-Modelle, HAL-JSON-Parsing (WorkPackage, User, Status, Role, Membership, …)
config.py       → TOML-Config (XDG: ~/.config/openproject-tool/config.toml), tomlkit
queue.py        → OperationQueue: PendingOperations sammeln, mergen, batch-applyen
perms.py        → Reine Berechtigungslogik (Source-Set-Rekonstruktion, Hierarchie, Diff/Propagation)
perms_queue.py  → PermissionQueue: geplante additive Mitgliedschaften sammeln
tui/perms_*.py  → `op perms`-Modus (eigene PermsApp: Projektbaum, Detail, Review, Applying)
```

### `op perms` — Berechtigungs-Tool

Eigener Modus (`op perms [projekt]`) mit eigener `PermsApp` (kein Task-State). Zeigt Projekt-Berechtigungen **gruppen-/benutzer-zentriert**: Da die v3-API keinen `inherited_from`-Marker hat, wird das **Source-Set** mengenbasiert rekonstruiert (Gruppen + Direkt-User; via Gruppe sichtbare User werden unter der Gruppe eingeklappt, siehe `perms.build_source_set`). Mitgliedschaften werden **live** geladen (nicht aus dem `[remote.*]`-Cache). Funktionen: `f` gleicht den **gesamten Teilbaum** eines Oberprojekts an (`plan_propagation`), `c` überträgt Berechtigungen von einem anderen Projekt (`plan_transfer`) — beides **additiv** (nie entfernen). Geplante Änderungen werden gesammelt (`PermissionQueue`), per `g` reviewed und angewendet (`create_membership`/`update_membership_roles`).

### Datenfluss

1. `cli.py::run()` – Argparse, Config laden, Query parsen
2. `search.py::parse()` + `build_api_filters()` – Nutzer-Token → OpenProject-Filter-JSON
3. `actions.py::load_remote_data()` – Metadaten-Caching (Statuses, Types, Users, Projects, …) → `[remote.*]` in Config
4. `api.py::OpenProjectClient` – Async HTTPX, Pagination, HAL-JSON → Pydantic-Objekte
5. `tui/app.py` – Screens mit Screen-Stack, `OperationQueue` als geteilter Zustand
6. `queue.py::OperationQueue` – Review → Apply (PATCH je PendingOperation)

### Wichtige Klassen

**`SearchQuery`** (`search.py`): Parst `op type=Bug,Feature status=open #123 Suchbegriff` in strukturierte Filter. `_FILTER_KEY_MAP` übersetzt Filter-Keys zu API-Feldern und Remote-Caches. Substring-Fuzzy-Match mit Ambiguity-Detection. Eine einzelne Zahl → `task_id` (Detail/Einzel-Task); mehrere Zahlen und/oder Ranges (`6619 7190 7338..7342`, ohne Filter/Worte) → `task_ids` (per `get_work_packages_by_ids` in Eingabereihenfolge geladen). Pipe im Wort (`sapv|pallinet`) → ODER-Varianten.

**`Config`** (`config.py`): Hält `connection`, `defaults`, `remote`, `logging`, `filter`. `remote.*` wird von `--load-remote-data` befüllt und ist Voraussetzung für Filter-Auflösung. `tomlkit` wird verwendet, um Kommentare im TOML zu erhalten.

**`OpenProjectClient`** (`api.py`): Async Context-Manager. `AuthError` bei HTTP 401, `OpenProjectError` als Basisklasse. `get_custom_fields()` nutzt Schema-Batch-API.

**`WorkPackage`** (`models.py`): `from_api(payload)` parst HAL-JSON. `custom_fields` als `dict[int, Any]`.

**`OperationQueue`** (`queue.py`): `id → PendingOperation`. Mehrfach-Edits auf derselben Task werden automatisch gemergt. Status: `pending → running → done/failed`.

**`UpdateForm`** (`tui/update_form.py`): Pending-Changes State. `api_changes()` liefert das PATCH-JSON für OpenProject. Mehrwertige Custom Fields (OpenProject-Typ `[]…`, erkannt via `CustomField.is_multi`, persistiert in `remote.custom_field_multi`) akkumulieren per `toggle_custom_field_multi()` und werden als HAL-Array gesendet; `init_custom_field_multi()` seedet den Ausgangswert ohne ihn als Änderung zu markieren. Im UpdateModal verhalten sich solche Picker wie die Beobachter-Felder (auswählen sammelt/toggelt, Anzeige der Auswahl direkt im Feld via `PickerWidget.set_blank_display()`).

### TUI-Screens und Keybindings

| Screen/Modal | Datei | Wichtige Keys |
|---|---|---|
| MainScreen | `tui/main_screen.py` | `space` Auswahl, `i` Invert, `u` Edit, `g` Review, `f` Filter, `o` Browser, `/` Suche, `q` Quit |
| DetailScreen | `tui/detail_screen.py` | `e` Edit, `c` Kommentar, `/` Textsuche (n/N), `o` Browser |
| UpdateModal | `tui/update_modal.py` | `g` Apply, `q`/Esc Cancel, `Ctrl+D` Kalender, `Ctrl+T` Today, `Ctrl+N` Next Free Day, `/` Parent-Suche (nur bei Fokus im Parent-Feld) |
| WorkPackagePickerScreen | `tui/picker_widget.py` | Inkrementelle Task-Suche (Substring), Enter wählt, Esc Cancel |
| FilterScreen | `tui/filter_screen.py` | `Ctrl+G`/Enter Apply, Esc Cancel |
| ProjectFilterScreen | `tui/project_filter_screen.py` | Hierarchie-aware, persistiert in Config |
| ReviewScreen | `tui/review_screen.py` | Batch-Review vor Apply |
| ApplyingScreen | `tui/applying_screen.py` | Batch-PATCH-Ausführung |
| PermsProjectsScreen | `tui/perms_projects_screen.py` | `op perms`-Root: Projektbaum mit Mismatch-Flag (`▲`); Enter Detail, `c` Übertragen, `f` Teilbaum angleichen, `g` Review, `r` Neu laden, `q` Quit |
| PermsDetailScreen | `tui/perms_detail_screen.py` | Gruppen (mit eingeklappten Mitgliedern) + Direkt-User eines Projekts |
| PermsReviewScreen / PermsApplyingScreen | `tui/perms_review_screen.py`, `tui/perms_applying_screen.py` | Review (`d` entfernen, `g` anwenden) + Batch-Ausführung der Mitgliedschaften |

### Date-Shortcuts (UpdateModal)

`today`/`t`, `tomorrow`/`tom`, `yesterday`, `mon`–`sun` (nächste Occurrence), `+N d/w`, `-N d/w`. `Ctrl+N` = nächster freier Tag via `api.get_busy_days()`.

## Entwicklungskonventionen

- **Plan → GitHub-Issue**: Für jeden neuen Plan wird bei dessen Umsetzung automatisch ein GitHub-Issue via `gh issue create` angelegt, das das Vorhaben genauer erklärt und präzisiert (Ziel, Kontext, Umsetzungsschritte), sodass es nachvollziehbar ist. Die Issue-Nummer wird vom Tool vergeben und dem User genannt. Commits und PRs referenzieren dieses Issue (`#<nr>`), damit sich Änderungen später darauf zurückführen lassen.
- **Red-Green-Zyklus**: Commits sind oft als "Phase X Red" (Tests zuerst) + "Phase X Green" (Implementierung) strukturiert.
- **Async-First**: Alle API-Calls und TUI-Aktionen sind `async/await`. Tests mit `pytest-asyncio`.
- **Config als Single Source of Truth**: `remote.*`-Daten kommen ausschließlich aus der Config (nach `--load-remote-data`), nicht aus Runtime-API-Calls in der TUI.
- **`current_query`** ist Runtime-State in `OpApp` – wird beim Start übergeben und kann per Filter-Screen neu gesetzt werden, was einen API-Reload auslöst.
