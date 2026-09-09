"""Locate the Zen profile used by the installed browser."""

from configparser import ConfigParser
from pathlib import Path
from typing import Iterable, Optional


def _profile_paths_from_ini(zen_root: Path) -> Iterable[Path]:
    """Yield configured profiles in Zen's active-profile preference order."""
    profiles_ini = zen_root / "profiles.ini"
    if not profiles_ini.exists():
        return

    config = ConfigParser(interpolation=None)
    config.read(profiles_ini)

    # Firefox-family browsers use Install* sections to record the profile that
    # a particular installed build opens. It takes precedence over Profile*
    # sections' older Default=1 marker.
    sections = [
        section for section in config.sections() if section.lower().startswith("install")
    ]
    sections += [
        section
        for section in config.sections()
        if section.lower().startswith("profile")
        and config.getboolean(section, "default", fallback=False)
    ]
    sections += [
        section for section in config.sections() if section.lower().startswith("profile")
    ]

    seen: set[Path] = set()
    for section in sections:
        configured_path = config.get(section, "path", fallback="")
        if not configured_path:
            configured_path = config.get(section, "default", fallback="")
        if not configured_path:
            continue

        is_relative = config.getboolean(section, "isrelative", fallback=True)
        profile_path = zen_root / configured_path if is_relative else Path(configured_path)
        if profile_path not in seen:
            seen.add(profile_path)
            yield profile_path


def find_zen_profile() -> Optional[Path]:
    """Find Zen's active profile, preferring the profile registered by Zen."""
    zen_root = Path.home() / "Library" / "Application Support" / "zen"
    profiles_root = zen_root / "Profiles"
    if not profiles_root.exists():
        return None

    for profile_path in _profile_paths_from_ini(zen_root):
        if profile_path.is_dir():
            return profile_path

    profile_dirs = [path for path in profiles_root.iterdir() if path.is_dir()]
    # Without a usable registry, favour a profile containing a session over an
    # empty legacy profile whose directory happens to be listed first.
    for profile_path in profile_dirs:
        if (profile_path / "zen-sessions.jsonlz4").exists():
            return profile_path

    for profile_path in profile_dirs:
        if "default" in profile_path.name.lower():
            return profile_path

    return profile_dirs[0] if profile_dirs else None
