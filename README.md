# Arc2Zen

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Move your life from **Arc** to **Zen** in one command: spaces, pinned tabs,
folders, and your **logged-in sessions** (cookies), so most sites stay signed in.

> This is a fork of [olegfour3/arc2zen](https://github.com/olegfour3/arc2zen),
> which does the bookmark/space migration. It adds cookie migration (keep sites
> logged in), a one-shot "move everything" flow, and a fix for Zen profile
> detection. See [Credits](#credits).

**macOS only.** Arc is Chromium-based and Zen is a Firefox fork, so this bridges
the two very different data formats. **[RU](README_RU.md)**

## Features

- **Move everything** from Arc to Zen in one pass, with no manual setup
- **Spaces, pinned tabs and folders** become Zen workspaces (created for you)
- **Cookies / logins** carried over so most sites stay signed in
- **Export Arc or Zen bookmarks** to HTML (works with any browser)
- **Backs up your Zen data first**, and never overwrites existing cookies

## Quick Start

### With uv (recommended)

```bash
git clone https://github.com/dorochadev/arc2zen.git
cd arc2zen
uv run main.py
```

`uv` creates a virtual environment and installs dependencies automatically.

### With pip

```bash
git clone https://github.com/dorochadev/arc2zen.git
cd arc2zen
pip install lz4 cryptography
python main.py
```

## Requirements

- macOS, Python 3.10+
- `lz4` (Zen session files) and `cryptography` (cookie decryption)

## Usage

**Quit Zen first** (its data files are locked while it runs), then run the tool:

```
  arc → zen   move your stuff from Arc to Zen
  ────────────────────────────────────────────────
  ✓ your Zen data gets backed up first, so you can't lose anything

  1  Move everything  spaces, pinned tabs, folders + logins

  ── or just one part ──
  2  Move bookmarks & spaces
  3  Move logins (cookies)
  4  Export Arc bookmarks to HTML
  5  Export Zen bookmarks to HTML

  6  Restore Zen from a backup
  7  Delete backups

  0  Quit
```

### 1. Move everything (recommended)

Creates a Zen workspace for each Arc space, imports the pinned tabs and folders,
then migrates your cookies. You get **one macOS prompt** to let it read Arc's
cookie key from your Keychain, click **Always Allow**.

### 2 / 3. Move one part

Run just the bookmark/space migration, or just the cookie migration.

### 4 / 5. Export to HTML

Export Arc or Zen pinned bookmarks to a standard HTML file for any browser.

### 6 / 7. Backups

Restore your Zen session from an automatic backup, or delete old backups.

## What transfers (and what can't)

| Data | Transfers? |
| --- | --- |
| Spaces, pinned tabs, folders | Yes, as Zen workspaces |
| Logins stored in cookies | Mostly yes |
| Saved passwords | Manually (see below), it's the reliable fallback |
| Session-only logins, or logins kept in localStorage/IndexedDB (e.g. Slack) | No, different browser engines |
| History, extensions, split views | No |

Because Arc (Chromium) and Zen (Firefox) use different engines, live sessions
can't all be transplanted. Cookie-based logins usually survive; sites that bind
sessions to the browser or store tokens outside cookies will ask you to log in
again. For those, migrating passwords makes re-login one click.

## How the cookie migration works

Arc stores cookies in an encrypted Chromium database. The key lives in your
login Keychain as "Arc Safe Storage". The tool:

1. reads that key locally (it never leaves your machine),
2. decrypts Arc's **persistent** cookies (AES-128-CBC, `v10`),
3. converts timestamps (Firefox stores cookie expiry in **milliseconds**),
4. inserts them into Zen's `cookies.sqlite` with `INSERT OR IGNORE`,
5. raises `network.cookie.maxNumber` so Zen keeps them all.

Zen's cookie files are backed up first (`*.cookiebak_<timestamp>`).

## Migrating passwords (manual)

Different security systems, so passwords are a quick manual step:

1. In Arc, open `arc://password-manager/settings` and **Export** to CSV.
2. In Zen, open `about:logins` → **⋯** → **Import from a File** → pick the CSV.
3. **Delete the CSV** afterward, it holds plain-text passwords.

## File locations

- Arc sidebar: `~/Library/Application Support/Arc/StorableSidebar.json`
- Arc cookies: `~/Library/Application Support/Arc/User Data/Default/Cookies`
- Zen profiles: `~/Library/Application Support/zen/Profiles/`

## Project structure

```
arc2zen/
├── main.py                   # Menu / entry point
├── core/
│   ├── arc_exporter.py       # Read + parse Arc data
│   ├── zen_exporter.py       # Export Zen bookmarks to HTML
│   ├── zen_importer.py       # Import Arc bookmarks/spaces into Zen
│   ├── zen_profile.py        # Locate the active Zen profile
│   ├── cookie_migrator.py    # Decrypt Arc cookies -> Zen cookies.sqlite
│   ├── full_migrator.py      # "Move everything" orchestration
│   └── models.py
└── tests/                    # Unit tests
```

## Troubleshooting

- **"No Zen profile found":** open Zen once, then fully quit it and retry.
- **"Could not read Arc Safe Storage":** click **Always Allow** on the macOS prompt.
- **Sites still logged out:** those use non-cookie sessions, import passwords instead.
- **Only pinned tabs migrated:** unpinned "today" tabs are not included (by design).
- **Want to undo:** menu option 6 restores from an automatic backup.

## Credits

- Original tool and bookmark/space migration: [Oleg Pashuk (olegfour3)](https://github.com/olegfour3/arc2zen)
- Zen profile-detection fix: [Piers](https://github.com/olegfour3/arc2zen/pull/3)
- Cookie migration, one-shot flow, and packaging in this fork

## License

[MIT](LICENSE).
