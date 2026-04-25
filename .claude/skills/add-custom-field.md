# Skill: Custom Field hinzufügen

Dieser Skill beschreibt, wie ein neues OpenProject-Custom-Field vollständig in das Tool integriert wird – von der API bis zur TUI.

## Hintergrund: OpenProject Custom Field API

Custom Fields erscheinen im Work Package JSON an zwei Stellen:

- **Skalare Typen** (text, integer, float, boolean, date): direkt im Root-Objekt als `customFieldN`
- **Ressourcen-Referenzen** (list/CustomOption, user, version): im `_links`-Abschnitt als HAL-Link

```json
{
  "customField1": "Textinhalt",
  "_links": {
    "customField42": { "href": "/api/v3/custom_options/94", "title": "Alan Umarow AUM" },
    "customField4":  { "href": "/api/v3/users/5", "title": "Max Mustermann" }
  }
}
```

### Typen und ihre `field_format`-Werte (aus Schema `type`-Feld, lowercase)

| OpenProject-Typ | `field_format` | Speicherort im WP | Config-Ziel |
|---|---|---|---|
| Textzeile | `string` | Root-Attribut | — |
| Langer Text | `text` | Root-Attribut | — |
| Integer | `integer` | Root-Attribut | — |
| Float | `float` | Root-Attribut | — |
| Boolean | `boolean` | Root-Attribut | — |
| Datum | `date` | Root-Attribut | — |
| **Liste (Einfach)** | `customoption` | `_links` → `/api/v3/custom_options/{id}` | `custom_field_options` |
| **Liste (Mehrfach)** | `[]customoption` | `_links` → Array von custom_options | `custom_field_options` |
| Hierarchie (Mehrfach) | `[]customfield::hierarchy::item` | `_links` → Array | — |
| **Benutzer** | `user` | `_links` → `/api/v3/users/{id}` | `custom_field_users` |
| Version | `version` | `_links` → `/api/v3/versions/{id}` | — |

### KRITISCH: Zwei verschiedene API-Endpoints für allowedValues

Der **Schema-Endpoint** (`/work_packages/schemas`) gibt für list-type CFs **keine** Optionen zurück — `_links` ist leer `{}`, auch mit `embed[]=allowedValues`:

```json
"customField42": {
  "type": "CustomOption",
  "name": "PM",
  "_links": {}
}
```

Der **Form-Endpoint** (`POST /projects/{id}/work_packages/form`) gibt `_embedded.allowedValues` vollständig zurück:

```json
"customField42": {
  "type": "CustomOption",
  "name": "PM",
  "_embedded": {
    "allowedValues": [
      {"_type": "CustomOption", "id": 94, "value": "Alan Umarow AUM"},
      {"_type": "CustomOption", "id": 95, "value": "Adam Baranowski ABR"}
    ]
  }
}
```

**→ `get_custom_fields()` in `api.py` lädt deshalb list-type CFs in zwei Phasen:**
1. Schema-Batch: findet welche CFs existieren + welches (project, type)-Paar sie enthält
2. Form-Calls: lädt `allowedValues` für alle `customoption`/`[]customoption`-CFs nach

---

## Aktuelle Infrastruktur

### Modelle (`models.py`)
- `CustomField.allowed_users: dict[int, str]` – User-ID → Name (user-type CFs)
- `CustomField.allowed_options: dict[int, str]` – Option-ID → Wert (list-type CFs, vom Form-Endpoint)
- `WorkPackage.custom_fields` – Raw-Root-Attribute (`customFieldN: wert`)
- `WorkPackage.custom_field_links: dict[int, int | None]` – CF-ID → verknüpfte ID (aus `_links.customFieldN`)
  - Funktioniert für beide Typen: User-ID bei user-type, Option-ID bei list-type

### Konfiguration (`config.py`)
- `RemoteConfig.custom_fields: dict[int, str]` – CF-ID → CF-Name
- `RemoteConfig.custom_field_users: dict[int, dict[int, str]]` – CF-ID → {User-ID → Name}
- `RemoteConfig.custom_field_options: dict[int, dict[int, str]]` – CF-ID → {Option-ID → Wert}
- `RemoteConfig.pm_users` – Property: gibt `custom_field_users[42]` ODER `custom_field_options[42]` zurück (CF#42 kann je nach Instanz user- oder customoption-type sein)

### API-Abruf (`api.py`)
- `get_custom_fields()`: zweistufig — Schema-Batch → Form-Calls für list-type CFs
- `_enrich_list_cf_options()`: parallel Form-POST je Representative-(project,type)-Pair
- `_fetch_form_schema(project_id, type_id)`: `POST /projects/{id}/work_packages/form`

### Suche (`search.py`)
- `cf<N>=<Wert>`: generischer Filter für alle CFs (löst Name → ID auf, sucht in `custom_field_options[N]` und `custom_field_users[N]`)
- `pm=<Name>`: Alias für `customField42`, sucht via `pm_users`-Property

### TUI
- **DetailScreen** (`_cf_lines()`): zeigt user-type und list-type CFs an
- **UpdateModal**: Selects für user-type (`sel-cf-{id}`) und list-type (`sel-cfo-{id}`) CFs
- **UpdateForm**: `set_custom_field_user()` / `set_custom_field_option()`; PATCH-Serialisierung

---

## Checkliste: Neues Custom Field einbinden

### Schritt 1: Daten laden

```bash
op --load-remote-data
```

Danach sind in `~/.config/openproject-tool/config.toml` die Werte unter `[remote.custom_field_options]` bzw. `[remote.custom_field_users]` eingetragen. Zur Diagnose:

```bash
python -c "
from op.config import load_config
c = load_config()
print('CFs:', c.remote.custom_fields)
print('CF-Options:', c.remote.custom_field_options)
print('CF-Users:', c.remote.custom_field_users)
"
```

### Schritt 2: field_format prüfen (bei Problemen)

Wenn ein CF nicht geladen wird, direkt via API prüfen:

```python
# field_format aller CFs ausgeben
import asyncio
from op.config import load_config, get_api_key
from op.api import OpenProjectClient

async def main():
    cfg = load_config()
    async with OpenProjectClient(cfg.connection.base_url, get_api_key(cfg)) as c:
        projects = await c.get_projects()
        types = await c.get_types()
        cfs = await c.get_custom_fields(
            project_ids=[p.id for p in projects],
            type_ids=[t.id for t in types],
        )
        for cf in cfs:
            print(f'CF#{cf.id} {cf.name!r}: format={cf.field_format!r} options={len(cf.allowed_options)} users={len(cf.allowed_users)}')

asyncio.run(main())
```

Bekannte `field_format`-Werte aus dieser Instanz:
- `customoption` → list-type, Optionen via Form-Endpoint
- `[]customoption` → multi-select list-type
- `[]customfield::hierarchy::item` → Hierarchie (noch nicht unterstützt)
- `integer`, `string`, `date` → skalare Typen (nur lesend)
- `user` → user-type

### Schritt 3: Suche testen

```bash
# List-type CF (z.B. CF#42 = "PM")
op cf42=AUM
op pm=AUM          # Alias für CF#42

# user-type CF
op cf4="Max Mustermann"
```

### Schritt 4: Benannten Alias in search.py eintragen (optional)

Für häufig verwendete list-type CFs in `_FILTER_KEY_MAP`:

```python
# src/op/search.py
_FILTER_KEY_MAP = {
    # ...
    'pm': ('customField42', ('pm_users',)),  # bestehend
    # Für list-type CFs: RemoteConfig hat keine direkte Property → cfN-Syntax bevorzugen
    # Für user-type CFs mit Property: analog zu pm
}
```

Für generische CFs ohne Alias funktioniert `cf<N>=<Wert>` sofort.

### Schritt 5: Tests schreiben

```python
# test_models.py — Optionen aus Form-Endpoint (embedded)
def test_custom_field_list_allowed_options():
    payload = {
        'id': 42, 'name': 'PM', 'field_format': 'customoption',
        '_embedded': {'allowedValues': [
            {'_type': 'CustomOption', 'id': 94, 'value': 'Alan Umarow AUM'},
            {'_type': 'CustomOption', 'id': 95, 'value': 'Adam Baranowski ABR'},
        ]},
        '_links': {},
    }
    cf = CustomField.from_api(payload)
    assert cf.allowed_options == {94: 'Alan Umarow AUM', 95: 'Adam Baranowski ABR'}
    assert cf.allowed_users == {}

# test_search.py — cfN-Filter
def test_cf_filter_list_type():
    remote = RemoteConfig(custom_field_options={42: {94: 'Alan Umarow AUM'}})
    filters = build_api_filters(parse(['cf42=AUM']), remote)
    assert {'customField42': {'operator': '=', 'values': ['94']}} in filters

# test_update_form.py — PATCH-Serialisierung
def test_set_custom_field_option():
    form = UpdateForm()
    form.set_custom_field_option(42, 94)
    assert form.api_changes()['_links']['customField42'] == {
        'href': '/api/v3/custom_options/94'
    }
```

---

## PATCH-Format für verschiedene CF-Typen

### List-type (CustomOption, Einfach oder Mehrfach)
```json
{ "_links": { "customField42": { "href": "/api/v3/custom_options/94" } } }
```

### User-type
```json
{ "_links": { "customField4": { "href": "/api/v3/users/5" } } }
```

### Löschen (auf leer setzen)
```json
{ "_links": { "customField42": { "href": null } } }
```

### Skalare Typen (text, integer, boolean, date)
```json
{ "customField1": "Neuer Text", "customField3": 42 }
```

Skalare Typen sind derzeit **nicht** in der TUI editierbar.

---

## Erweiterungspunkte

### Skalare Custom Fields (text/integer/date/boolean) editierbar machen

1. **`UpdateForm`**: `_cf_scalars: dict[int, Any]`; `set_custom_field_scalar()`; in `api_changes()` als Root-Attribut
2. **`UpdateModal`**: `Input`-Widget statt `Select`, Placeholder je nach `field_format`
3. **`DetailScreen`**: Lesen aus `wp.custom_fields` statt `wp.custom_field_links`

### Hierarchie-CFs (`[]customfield::hierarchy::item`)

Diese kommen als Array von hrefs in `_links`. Noch nicht unterstützt. Die Optionen müssten ebenfalls via Form-Endpoint geladen werden.

### Mehrfach-Auswahl (multi-select)

`[]customoption`-CFs speichern einen einzelnen Wert im `UpdateModal` (Single-Select). Für echte Multi-Select-Unterstützung müsste `UpdateForm` ein `list[int]` statt `int | None` für diese CFs speichern und das PATCH-Format ein Array von hrefs senden.
