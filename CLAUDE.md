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
models.py       → Pydantic-Modelle, HAL-JSON-Parsing (WorkPackage, User, Status, …)
config.py       → TOML-Config (XDG: ~/.config/openproject-tool/config.toml), tomlkit
queue.py        → OperationQueue: PendingOperations sammeln, mergen, batch-applyen
```

### Datenfluss

1. `cli.py::run()` – Argparse, Config laden, Query parsen
2. `search.py::parse()` + `build_api_filters()` – Nutzer-Token → OpenProject-Filter-JSON
3. `actions.py::load_remote_data()` – Metadaten-Caching (Statuses, Types, Users, Projects, …) → `[remote.*]` in Config
4. `api.py::OpenProjectClient` – Async HTTPX, Pagination, HAL-JSON → Pydantic-Objekte
5. `tui/app.py` – Screens mit Screen-Stack, `OperationQueue` als geteilter Zustand
6. `queue.py::OperationQueue` – Review → Apply (PATCH je PendingOperation)

### Wichtige Klassen

**`SearchQuery`** (`search.py`): Parst `op type=Bug,Feature status=open #123 Suchbegriff` in strukturierte Filter. `_FILTER_KEY_MAP` übersetzt Filter-Keys zu API-Feldern und Remote-Caches. Substring-Fuzzy-Match mit Ambiguity-Detection.

**`Config`** (`config.py`): Hält `connection`, `defaults`, `remote`, `logging`, `filter`. `remote.*` wird von `--load-remote-data` befüllt und ist Voraussetzung für Filter-Auflösung. `tomlkit` wird verwendet, um Kommentare im TOML zu erhalten.

**`OpenProjectClient`** (`api.py`): Async Context-Manager. `AuthError` bei HTTP 401, `OpenProjectError` als Basisklasse. `get_custom_fields()` nutzt Schema-Batch-API.

**`WorkPackage`** (`models.py`): `from_api(payload)` parst HAL-JSON. `custom_fields` als `dict[int, Any]`.

**`OperationQueue`** (`queue.py`): `id → PendingOperation`. Mehrfach-Edits auf derselben Task werden automatisch gemergt. Status: `pending → running → done/failed`.

**`UpdateForm`** (`tui/update_form.py`): Pending-Changes State. `api_changes()` liefert das PATCH-JSON für OpenProject.

### TUI-Screens und Keybindings

| Screen/Modal | Datei | Wichtige Keys |
|---|---|---|
| MainScreen | `tui/main_screen.py` | `space` Auswahl, `i` Invert, `u` Edit, `g` Review, `f` Filter, `o` Browser, `/` Suche, `q` Quit |
| DetailScreen | `tui/detail_screen.py` | `e` Edit, `c` Kommentar, `/` Textsuche (n/N), `o` Browser |
| UpdateModal | `tui/update_modal.py` | `g` Apply, `q`/Esc Cancel, `Ctrl+D` Kalender, `Ctrl+T` Today, `Ctrl+N` Next Free Day |
| FilterScreen | `tui/filter_screen.py` | `Ctrl+G`/Enter Apply, Esc Cancel |
| ProjectFilterScreen | `tui/project_filter_screen.py` | Hierarchie-aware, persistiert in Config |
| ReviewScreen | `tui/review_screen.py` | Batch-Review vor Apply |
| ApplyingScreen | `tui/applying_screen.py` | Batch-PATCH-Ausführung |

### Date-Shortcuts (UpdateModal)

`today`/`t`, `tomorrow`/`tom`, `yesterday`, `mon`–`sun` (nächste Occurrence), `+N d/w`, `-N d/w`. `Ctrl+N` = nächster freier Tag via `api.get_busy_days()`.

## Entwicklungskonventionen

- **Red-Green-Zyklus**: Commits sind oft als "Phase X Red" (Tests zuerst) + "Phase X Green" (Implementierung) strukturiert.
- **Async-First**: Alle API-Calls und TUI-Aktionen sind `async/await`. Tests mit `pytest-asyncio`.
- **Config als Single Source of Truth**: `remote.*`-Daten kommen ausschließlich aus der Config (nach `--load-remote-data`), nicht aus Runtime-API-Calls in der TUI.
- **`current_query`** ist Runtime-State in `OpApp` – wird beim Start übergeben und kann per Filter-Screen neu gesetzt werden, was einen API-Reload auslöst.
