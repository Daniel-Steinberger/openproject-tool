# openproject-tool

Fast, keyboard-driven CLI and TUI for [OpenProject](https://www.openproject.org/).

Search, update, and manage OpenProject tasks from the command line or in an
aptitude-style interactive terminal UI.

## Status

Early development — interfaces may change.

## Features

- Quick ID, title-word, and filter-based search
- Interactive TUI (Textual) with multi-select and batch updates
- Terminal-hyperlink output (clickable `OP#1234` in modern terminals)
- Async HTTP (httpx) — parallel pagination and metadata loading
- Generic — works with any OpenProject v3 instance

## Installation

```bash
pip install openproject-tool
```

or with [pipx](https://pipx.pypa.io/):

```bash
pipx install openproject-tool
```

## Quickstart

1. Create a config file (written on first run):
   ```bash
   op --help
   ```
2. Edit `~/.config/openproject-tool/config.toml` — set `base_url`.
3. Provide your API key via environment variable (recommended):
   ```bash
   export OP_API_KEY="your-api-key"
   ```
4. Load remote metadata (statuses, types, users, projects, custom fields):
   ```bash
   op --load-remote-data
   ```
5. Search:
   ```bash
   op 1234                      # task by ID
   op deployment pipeline       # title-word search
   op typ=bug status=*          # filter search
   op -i                        # interactive mode
   ```

## Search syntax

| Input | Meaning |
|---|---|
| `1234` (digits only) | Look up task by ID |
| `word1 word2` | Tasks whose title contains all words (any order) |
| `key=value` | Filter (e.g. `typ=bug`, `status=offen`) |
| `key=val1,val2` | OR-filter |
| `key=*` | Override default — match any value |

Filters and words can be combined: `op deploy typ=bug status=*`.

## Default filters

Configured in `[defaults]` in the config file — applied when not specified on
the command line. Use `key=*` to override a default for a single query.

## Interactive mode

Invoke with `-i`. Keybindings:

| Key | Action |
|---|---|
| `↑` / `↓` | Navigate |
| `Space` | Toggle selection |
| `i` | Invert selection |
| `Enter` | Open task detail |
| `u` | Update dialog (batch if multi-selected) |
| `/` | Search |
| `q` | Quit / back |

## Configuration

Config file location: `~/.config/openproject-tool/config.toml` (XDG-compliant;
honors `$XDG_CONFIG_HOME`).

API key authentication — either:
- `OP_API_KEY` environment variable (recommended), or
- `api_key = "..."` in the config file (ensure the file is only readable
  by your user: `chmod 600`).

The environment variable always takes precedence over the config entry.

## Contributing

Issues and pull requests welcome. See `CONTRIBUTING.md` (coming soon) for
guidelines.

## License

MIT — see [LICENSE](LICENSE).
