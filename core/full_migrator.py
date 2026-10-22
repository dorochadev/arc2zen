#!/usr/bin/env python3
"""One-shot "move everything from Arc to Zen".

Creates the Zen workspaces to match your Arc spaces (no manual setup),
imports pinned tabs and folders into them, then migrates your logged-in
cookies. Everything is backed up first and the run needs no prompts.

Zen must be closed.
"""

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from .arc_exporter import Colors
from .models import ArcSpace, Bookmark, BookmarkFolder
from .zen_profile import find_zen_profile
from .zen_importer import (
    read_lz4_json,
    write_lz4_json,
    get_arc_spaces,
    import_spaces_to_zen,
    clean_all_pinned_tabs_and_folders,
    count_items,
)
from .cookie_migrator import migrate_cookies

DEFAULT_THEME = {"type": "gradient", "gradientColors": [], "opacity": 0.5, "texture": 0}


def _session_files(profile_path: Path):
    return (
        profile_path / "zen-sessions.jsonlz4",
        profile_path / "sessionstore-backups" / "recovery.jsonlz4",
        profile_path / "sessionstore-backups" / "recovery.baklz4",
        profile_path / "sessionstore.jsonlz4",
    )


def _is_reusable_placeholder(zen_sessions: dict) -> bool:
    """True when the profile has a single, empty default workspace we can
    rename instead of leaving behind as clutter (the fresh-install case)."""
    spaces = zen_sessions.get("spaces", [])
    if len(spaces) != 1:
        return False
    has_pins = any(
        tab.get("pinned") and not tab.get("zenIsEmpty")
        for tab in zen_sessions.get("tabs", [])
    )
    return not has_pins


def ensure_workspaces(profile_path: Path, arc_space_names: List[str]) -> Dict[str, str]:
    """Make sure a Zen workspace exists for each Arc space, creating any that
    are missing. Returns {arc_space_name: workspace_uuid}.

    Existing workspaces are matched by name (case-insensitive) and never
    renamed, except a lone empty default workspace, which is reused for the
    first Arc space so a fresh Zen doesn't end up with a stray "Space".
    """
    zs_path, rec_path, recb_path, ss_path = _session_files(profile_path)
    zen_sessions = read_lz4_json(zs_path)

    theme = zen_sessions["spaces"][0]["theme"] if zen_sessions.get("spaces") else DEFAULT_THEME
    space_defs = list(zen_sessions.get("spaces", []))
    by_name = {s["name"].strip().lower(): s for s in space_defs}
    reusable = _is_reusable_placeholder(zen_sessions)

    mapping: Dict[str, str] = {}
    for name in arc_space_names:
        existing = by_name.get(name.strip().lower())
        if existing:
            mapping[name] = existing["uuid"]
            continue
        if reusable and space_defs:
            space_defs[0]["name"] = name
            mapping[name] = space_defs[0]["uuid"]
            reusable = False
            continue
        new_uuid = "{" + str(uuid.uuid4()) + "}"
        space_defs.append({
            "uuid": new_uuid,
            "name": name,
            "theme": json.loads(json.dumps(theme)),
            "containerTabId": 0,
            "hasCollapsedPinnedTabs": False,
        })
        mapping[name] = new_uuid

    # Write the space definitions into every session mirror so Zen agrees with
    # itself regardless of which file it loads at startup.
    zen_sessions["spaces"] = space_defs
    write_lz4_json(zs_path, zen_sessions)
    for path in (rec_path, recb_path, ss_path):
        if path.exists():
            data = read_lz4_json(path)
            if data.get("windows"):
                data["windows"][0]["spaces"] = space_defs
                write_lz4_json(path, data)

    return mapping


def _backup_session_files(profile_path: Path) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for path in _session_files(profile_path):
        if path.exists():
            shutil.copy2(path, path.with_name(path.name + f".arc2zen_{timestamp}.bak"))
    return timestamp


def migrate_everything(arc_profile: str = "Default") -> bool:
    """Move as much as possible from Arc to Zen in one pass. Caller must ensure
    Zen is closed."""
    profile_path = find_zen_profile()
    if not profile_path:
        print(f"{Colors.RED}No Zen profile found. Open Zen once, then close it.{Colors.RESET}")
        return False

    print(f"\n{Colors.GREEN}Backing up your Zen data first, so nothing can be lost...{Colors.RESET}")
    timestamp = _backup_session_files(profile_path)
    print(f"  saved as *.arc2zen_{timestamp}.bak in your Zen profile")

    # --- bookmarks, spaces, pinned tabs & folders ---
    print(f"\n{Colors.CYAN}Moving spaces, pinned tabs and folders...{Colors.RESET}")
    try:
        arc_spaces: List[ArcSpace] = get_arc_spaces()
    except Exception as exc:
        print(f"{Colors.RED}Could not read Arc data: {exc}{Colors.RESET}")
        arc_spaces = []

    if arc_spaces:
        names = [s.name for s in arc_spaces]
        mapping = ensure_workspaces(profile_path, names)
        clean_all_pinned_tabs_and_folders(profile_path)
        import_spaces_to_zen(profile_path, arc_spaces, mapping)
        # Keep the clean-shutdown snapshot in step with the live session.
        rec_path = profile_path / "sessionstore-backups" / "recovery.jsonlz4"
        ss_path = profile_path / "sessionstore.jsonlz4"
        if rec_path.exists() and ss_path.exists():
            shutil.copy2(rec_path, ss_path)
        bookmarks, folders, standalone = count_items(arc_spaces)
        print(f"{Colors.GREEN}  moved {len(names)} spaces, "
              f"{bookmarks + standalone} pinned tabs, {folders} folders{Colors.RESET}")
    else:
        print(f"{Colors.YELLOW}  no pinned Arc tabs found, skipping.{Colors.RESET}")

    # --- cookies (keep sites logged in) ---
    print(f"\n{Colors.CYAN}Moving logins (cookies)...{Colors.RESET}")
    migrate_cookies(arc_profile=arc_profile)

    print(f"\n{Colors.GREEN}{Colors.BOLD}All done. Open Zen and enjoy.{Colors.RESET}")
    print(f"{Colors.GREY}Tip: for sites that still want a login (e.g. Slack), import your "
          f"saved passwords from Arc.{Colors.RESET}")
    return True
