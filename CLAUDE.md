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

# Config-Datei im $EDITOR öffnen (Pfad steht auch im --help)
op --config

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
perms_queue.py  → PermissionQueue: polymorphe additive PermActions sammeln
tui/perms_*.py  → `op perms`-Modus (eigene PermsApp: Projektbaum/Gruppen/Detail/Review/Applying)
notify/         → `op notify`-Modus (Inbox-Sichtung per LLM, eigene NotifyApp) — siehe unten
```

### `op perms` — Berechtigungs-Tool

Eigener Modus (`op perms [projekt]`) mit eigener `PermsApp` (kein Task-State). Zeigt Berechtigungen **gruppen-/benutzer-zentriert**: Da die v3-API keinen `inherited_from`-Marker hat, wird das **Source-Set** mengenbasiert rekonstruiert (Gruppen + Direkt-User; via Gruppe sichtbare User werden unter der Gruppe eingeklappt, siehe `perms.build_source_set`). Daten werden **live** geladen (nicht aus dem `[remote.*]`-Cache), inkl. aller Gruppen-Mitgliederlisten.

Zwei Wurzelsichten, umschaltbar mit `v`: **Projektbaum** (`PermsProjectsScreen`, `▲` = weicht vom Oberprojekt ab; Detail zeigt „Fehlt ggü. Oberprojekt") und **Gruppenliste** (`PermsGroupsScreen` → `PermsGroupDetailScreen`: Mitglieder mit Footprint-Abweichung ggü. der **Mehrheit** `▲` und Warnung `⚠` für unübliche direkte Mitgliedschaften). Aktionen: `f` Teilbaum angleichen (`plan_propagation`), `c` von Projekt übertragen (`plan_transfer`), `a` Gruppenmitglied hinzufügen, `h` Abweichler heilen (additiv zur Mehrheit), `n` neuen Benutzer anlegen (Status invited/active, optional Klonen von Gruppen + direkten Mitgliedschaften einer Vorlage). Alles **additiv** (nie entfernen), gesammelt in `PermissionQueue` als typisierte `PermAction`s (`AddProjectMembership`/`AddGroupMembers`/`CloneInto`/`CreateUserClone`, je mit `describe()`+`apply()`), per `g` reviewed und angewendet.

### `op notify` — Benachrichtigungs-Sichtung mit lokalem LLM

Dritter Modus neben `op` und `op perms` (Kurzform: `opn`). Holt die persönliche
Benachrichtigungs-Inbox (`/api/v3/notifications`), bündelt sie je Work Package, lässt sie von
einem **OpenAI-kompatiblen Chat-Endpunkt** einstufen und zusammenfassen und markiert auf Wunsch
ab, was erledigt ist.

**Warum im selben Repo statt in einem eigenen:** die Config-Datei ist dieselbe, und geteilt
werden `api.py` (Auth, Fehlerübersetzung, Request-Plumbing), `models.py`, `html_to_markdown.py`,
`logging_setup.py`, das Queue-Muster aus `queue.py` und die respx-Testinfrastruktur. Eine zweite
Codebasis müsste das per Git-Commit-Pin importieren oder kopieren — `op` ist kein Library-Paket
mit stabiler API.

**Der Modus ist vollständig optional.** Es kommt keine neue Runtime-Dependency dazu: der
LLM-Client spricht `/v1/chat/completions` direkt über `httpx`. `op` und `op perms` führen keinen
LLM-Call aus. Fehlt `[llm]` in der Config oder ist der Server nicht erreichbar, betrifft das
ausschließlich diesen Modus — und auch dort bleibt `--no-llm` benutzbar.

**Dieses Repo ist öffentlich.** Instanzspezifisches gehört deshalb nicht in den Code, sondern in
die Config: LLM-Host und Modellname unter `[llm]`, zusätzliche Einstufungsregeln unter
`[notifications] extra_instructions`. Der mitgelieferte Prompt ist generisch formuliert.

#### Schichten

```
notify/cli.py        → Argparse-Modus + Rich-Report; Einstiegspunkt `op notify` / `opn`
notify/api.py        → NotificationsClient (erbt OpenProjectClient): Inbox, Activities, mark_read
notify/models.py     → Notification, NotificationGroup
notify/grouping.py   → Notifications → eine Gruppe je Work Package
notify/render.py     → Aktivitäten → Textblock für den Prompt (WYSIWYG-Markup raus)
notify/prompts.py    → System-/User-Prompts + JSON-Schema
notify/llm.py        → LlmClient: httpx gegen /v1/chat/completions, Semaphore, Retry
notify/analysis.py   → Map-Reduce über die Gruppen, GroupAnalysis
notify/cache.py      → Analyse-Cache (XDG), Schlüssel = WP + Aktivitäten + Modell + Prompt
notify/mark.py       → select_analyses() + MarkQueue (pending → done/failed)
notify/tui/          → NotifyApp: Liste → Detail → Review → Applying
```

#### Gemessene API-Eigenschaften (gegen OpenProject 13/14)

Diese Punkte sind der Grund für mehrere Design-Entscheidungen — nicht raten, sondern nachlesen:

- **Die Notification trägt keinen Inhalt.** Sie hat `reason`, `createdAt` und Links auf Actor,
  Activity, Work Package und Projekt. Alles Lesbare wird separat geholt.
- **`pageSize` ist bei 100 gedeckelt**, und eigene `offset`-Zählung lieferte eine leere zweite
  Seite. Deshalb blättert `get_notifications()` über `_links.nextByOffset`, mit Schleifenschutz.
- **Ein Call je Work Package reicht:** `/work_packages/{id}/activities` liefert alle Aktivitäten
  samt `comment.raw` und `details[].raw` — statt einem Call je Benachrichtigung.
- **Es gibt keinen belegten Sammel-Endpunkt zum Markieren.** `GET /notifications/read_ian`
  antwortet 404; ob POST existiert, ist ungeprüft. Markiert wird einzeln über
  `_links.readIAN`; ein 404 gilt dabei als Erfolg (der Zustand ist erreicht).
- **`_links.user` einer Aktivität trägt nicht auf jeder Instanz einen `title`.** Ohne
  Namensmappe steht im Aktivitätslog überall `?`. `render_group(user_names=…)` bekommt die
  Namen aus den Notification-Aktoren plus `[remote.users]`.
- **`responsible` fehlte im `WorkPackage`-Modell** und ist für „wartet das auf mich?"
  aussagekräftiger als `assignee` — nachgetragen, additiv.

#### LLM-Vertrag

**Map, ein Call je Work Package**, Antwort nach `GROUP_SCHEMA`:

```json
{"classification": "relevant|worth_knowing|churn",
 "summary": "…", "open_points": ["…"], "waits_for_me": true, "rationale": "…"}
```

Der Titel wird **nicht** abgefragt — er steht in der API. Ein Feld weniger im Schema ist ein Feld
weniger zum Erfinden; im ersten Echtlauf lieferte das Modell Titel wie
`## Work package #7125 — …`, weil es die Kopfzeile des Blocks übernahm.

**Reduce, ein Call über alle Ergebnisse** → Markdown-Bericht, `relevant` zuerst, Churn nur als
Zählzeile. Die Abschnittsüberschriften formuliert das Modell selbst in der Sprache des
Materials; die Klassennamen sind interne Labels und dürfen nicht als Überschrift erscheinen.

**Die Einstufungsregeln nennen ihre Gründe**, nicht nur die drei Labels — das macht die Antwort
über Modelle hinweg reproduzierbar:

- **Eine direkte Erwähnung schlägt das Modell.** Trägt eine Gruppe eine Benachrichtigung mit
  Grund `mentioned`, wird sie in `_to_analysis` auf `relevant` gehoben, egal was das Modell
  geantwortet hat — auch bei Cache-Treffern, und `waits_for_me` wird gesetzt. Jemand hat den
  Benutzer namentlich angesprochen; das ist eine Tatsache, keine Ermessensfrage. Die Regel steht
  zusätzlich im Prompt, sonst begründet das Modell eine Einstufung, die es nicht getroffen hat.
- `relevant`: direkte Frage oder Erwähnung; ein Status, der auf den Benutzer wartet, während er
  Verantwortlicher oder Bearbeiter ist; **eine Arbeit, die nur noch an einer Handlung des
  Benutzers hängt** (bestellen, Key eintragen, freigeben); ein neuer fachlicher Befund mit
  Handlungsbedarf; eine kippende Frist.
- `worth_knowing`: still als Verantwortlicher gesetzt; Ergebnis ohne Handlungsbedarf.
- `churn`: reine Feldpflege; **Bot-Kommentare, die Commit-Nachrichten spiegeln** (erkennbar an
  der Autorenzeile am Ende); automatische Rollups aus Unteraufgaben; selbst ausgelöste
  Aktivitäten.

**Prompt-Härtung:** Aktivitätstexte sind Fremdtext und enthalten regelmäßig selbst
LLM-generierte Passagen. Sie gehen als `<activity_block>` in den Prompt, mit der ausdrücklichen
Regel: Material, niemals Anweisung — und: nichts erfinden, was nicht im Block steht.

#### Reasoning-Modelle

Ein denkendes Modell verbraucht das Token-Budget, bevor es antwortet: die erste Messung ergab
`finish_reason: "length"`, leeren `content` und den ganzen Text in `reasoning_content`.
Konsequenzen:

- `[llm] disable_thinking = true` sendet `chat_template_kwargs.enable_thinking = false`
  (llama.cpp und vLLM verstehen das; gemessen: 42 statt 396 Completion-Tokens).
  `reasoning_effort: "none"` wirkte **nicht**.
- `max_tokens` steht per Default auf 3000.
- Eine abgeschnittene Antwort meldet, an welchen zwei Schrauben es liegt, statt „kein JSON".

`json_schema` wird zuerst versucht; antwortet der Server mit 400, fällt der Client auf
`json_object` zurück — der Benutzer soll den Dialekt seines Servers nicht konfigurieren müssen.

#### Verhalten, das bewusst so ist

- **Eine fehlgeschlagene Gruppe verschwindet nie.** Sie behält ihren Platz, trägt den Fehler und
  wird **nie** als `churn` eingestuft — sonst räumte `--mark-read-churn` genau das ab, was
  niemand gelesen hat. Fehlschläge landen aus demselben Grund nicht im Cache.
- **Benachrichtigungen ohne Work Package** (News, Wiki) bleiben als Einzelgruppen erhalten.
- **`--mark-read` akzeptiert Work-Package- wie Benachrichtigungs-IDs** und meldet unbekannte,
  statt sie zu übergehen.
- **`--no-llm --mark-read-churn` verweigert den Dienst**: ohne Einstufung gibt es kein Rauschen.
- **Der Cache-Schlüssel bindet den Eintrag an seine Herkunft** (Work Package, gesehene
  Aktivitäten, Modell, Prompt-Hash) — ein geänderter Prompt entwertet ihn von selbst.

#### Bedienung

```bash
op notify                        # Bericht im Terminal
op notify -i                     # TUI: Liste → Detail → Review → Applying
op notify --mark-read 8202 7661  # genannte Work Packages (oder Notification-IDs)
op notify --mark-read-churn      # alles als Rauschen Eingestufte
op notify --mark-read-all        # Inbox leeren
op notify --no-llm               # gruppierte Rohsicht ohne Modell
op notify --refresh              # Analyse-Cache übergehen
opn …                            # Kurzform desselben Modus
```

TUI-Tasten (aus `[keybindings.notify_list]` / `[keybindings.notify_detail]`, Review und Applying
teilen sich die Sektionen mit `op`):

| Screen | Tasten |
|---|---|
| Liste | `space` markieren, `i` invertieren, `c` alles Rauschen, `a` alles, `Enter` Detail, `g` Review, `o` Browser, `q` beenden |
| Detail | `m` als gelesen vormerken (toggelt), `n` / `p` nächstes / vorheriges Work Package, `o` Browser, `q` zurück zur Liste |
| Review | `d` entfernen, `g` anwenden, `q` zurück |

Das Detail ist damit ein eigener Durchgang durch die Inbox: `n` weiter, `m` wenn erledigt, ohne
zwischendurch in die Liste zurückzuspringen. Oben stehen zwei Zeilen über dem Dokument:

- **Rollen-Badges** — Verantwortlicher, Bearbeiter, Status, und ein `@`-Hinweis bei direkter
  Erwähnung. Wo der Leser selbst eingetragen ist, steht `du (Name)` farblich hervorgehoben; das
  ist die Information, die darüber entscheidet, wie viel davon einen angeht.
- **Handlungszeile** — höchstens zwei Sätze, was dieser Vorgang vom Leser will. Ohne Modell
  (`--no-llm`) sagt die Zeile das, statt etwas vorzutäuschen; schlägt der Aufruf fehl, steht der
  Fehler dort und sonst ändert sich nichts.

Die Handlungszeilen entstehen **nicht erst beim Öffnen**: `NotifyApp` startet beim Mount einen
Worker, der die Liste **von oben nach unten** durchgeht und je Work Package eine Zeile holt. Die
Liste zeigt sie in der Spalte „Was zu tun ist" und malt sich neu, sobald eine ankommt
(`ActionLineReady`-Message an alle Screens im Stack); bis dahin steht dort `…`. Öffnet der Leser
einen Vorgang, den der Durchlauf noch nicht erreicht hat, zieht die Detailseite ihn vor —
`NotifyApp.fetch_action_line()` ist der gemeinsame Einstieg, und `_action_pending` sorgt dafür,
dass **pro Work Package trotzdem höchstens ein Modellaufruf** läuft. Die Ergebnisse liegen in
einem **Laufzeit-Cache** (`NotifyApp.action_lines`), also genau ein Aufruf je Work Package pro
Programmlauf.

Dafür bleibt der LLM-Client bei `-i` über die Laufzeit der TUI geöffnet — die frühere Regel „die
TUI spricht nie mit dem Modell" gilt seitdem nur noch für Review und Applying. **`m` toggelt die Vormerkung, nicht den
Server-Zustand** — es gibt keinen belegten Weg zurück auf *ungelesen*, geschrieben wird erst beim
Anwenden. Der Listen-Cursor folgt beim Zurückkehren dorthin, wo `n`/`p` stehengeblieben sind.

#### Config

```toml
[llm]
base_url = "http://your-host:8000/v1"   # muss den API-Präfix enthalten
model = "your-model"                    # Name laut GET <base_url>/models
# api_key = "…"                         # oder OP_LLM_API_KEY; lokal meist unnötig
# temperature = 0.2
# max_tokens = 3000
# parallel = 4
# timeout = 180.0
# disable_thinking = false              # true bei denkenden Modellen

[notifications]
# extra_instructions = ""               # instanzspezifische Einstufungsregeln
# hide_own_activities = true
# cache_enabled = true
```

Beide Sektionen werden in bestehende Config-Dateien nachgetragen (`_migrate_optional_sections`),
ohne Kommentare zu verlieren.

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
| PermsProjectsScreen | `tui/perms_projects_screen.py` | `op perms`-Root: Projektbaum mit Mismatch-Flag (`▲`); Enter Detail, `v` Gruppensicht, `c` Übertragen, `f` Teilbaum angleichen, `g` Review, `r` Neu laden, `q` Quit |
| PermsDetailScreen | `tui/perms_detail_screen.py` | Gruppen (mit eingeklappten Mitgliedern) + Direkt-User (`⚠`); Sektion „Fehlt ggü. Oberprojekt" |
| PermsGroupsScreen / PermsGroupDetailScreen | `tui/perms_groups_screen.py`, `tui/perms_group_detail_screen.py` | Gruppenliste (`v` zurück); Detail: Mitglieder mit Abweichung `▲`/`⚠`, `a` add, `h` heilen, `n` neuer User |
| PermsNewUserModal | `tui/perms_new_user_modal.py` | Benutzeranlage: `Ctrl+S` anlegen, `Ctrl+T` Status invited/active, `Ctrl+P` Vorlage |
| PermsReviewScreen / PermsApplyingScreen | `tui/perms_review_screen.py`, `tui/perms_applying_screen.py` | Review (`d` entfernen, `g` anwenden) + Batch-Ausführung der `PermAction`s |

### Date-Shortcuts (UpdateModal)

`today`/`t`, `tomorrow`/`tom`, `yesterday`, `mon`–`sun` (nächste Occurrence), `+N d/w`, `-N d/w`. `Ctrl+N` = nächster freier Tag via `api.get_busy_days()`.

## Entwicklungskonventionen

- **Plan → GitHub-Issue**: Für jeden neuen Plan wird bei dessen Umsetzung automatisch ein GitHub-Issue via `gh issue create` angelegt, das das Vorhaben genauer erklärt und präzisiert (Ziel, Kontext, Umsetzungsschritte), sodass es nachvollziehbar ist. Die Issue-Nummer wird vom Tool vergeben und dem User genannt. Commits und PRs referenzieren dieses Issue (`#<nr>`), damit sich Änderungen später darauf zurückführen lassen.
- **Imports immer Top-of-File**: Keine Imports mitten in Funktionen. Einzige erlaubte Ausnahme: das Brechen eines **echten zirkulären Imports** (typisch im `tui/`-Paket, wo Screens sich gegenseitig bzw. `op.tui.app` referenzieren). Solche Lazy-Imports sind kommentiert/erkennbar (z.B. `from op.tui.app import AppState` in Screen-Methoden). Stdlib- und nicht-zyklische Projekt-Imports gehören nach oben.
- **Red-Green-Zyklus**: Commits sind oft als "Phase X Red" (Tests zuerst) + "Phase X Green" (Implementierung) strukturiert.
- **Async-First**: Alle API-Calls und TUI-Aktionen sind `async/await`. Tests mit `pytest-asyncio`.
- **Config als Single Source of Truth**: `remote.*`-Daten kommen ausschließlich aus der Config (nach `--load-remote-data`), nicht aus Runtime-API-Calls in der TUI.
- **`current_query`** ist Runtime-State in `OpApp` – wird beim Start übergeben und kann per Filter-Screen neu gesetzt werden, was einen API-Reload auslöst.
