import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.zen_profile import find_zen_profile


class FindZenProfileTests(unittest.TestCase):
    def test_prefers_installed_profile_over_empty_legacy_default_profile(self):
        """The Install section names the profile opened by the installed Zen build."""
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            zen_root = home / "Library" / "Application Support" / "zen"
            profiles_root = zen_root / "Profiles"
            empty_profile = profiles_root / "a3aluz5l.Default Profile"
            active_profile = profiles_root / "jw2vzbzo.Default (release)"
            empty_profile.mkdir(parents=True)
            active_profile.mkdir()
            (active_profile / "zen-sessions.jsonlz4").touch()
            (zen_root / "profiles.ini").write_text(
                "[Profile0]\n"
                "Name=Default (release)\n"
                "IsRelative=1\n"
                "Path=Profiles/jw2vzbzo.Default (release)\n\n"
                "[Profile1]\n"
                "Name=Default Profile\n"
                "IsRelative=1\n"
                "Path=Profiles/a3aluz5l.Default Profile\n"
                "Default=1\n\n"
                "[Install6ED35B3CA1B5D3AF]\n"
                "Default=Profiles/jw2vzbzo.Default (release)\n"
                "Locked=1\n"
            )

            with patch("core.zen_profile.Path.home", return_value=home):
                self.assertEqual(find_zen_profile(), active_profile)

    def test_falls_back_to_profile_with_session_data_when_registry_is_absent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            profiles_root = (
                home / "Library" / "Application Support" / "zen" / "Profiles"
            )
            empty_profile = profiles_root / "a3aluz5l.Default Profile"
            session_profile = profiles_root / "jw2vzbzo.Default (release)"
            empty_profile.mkdir(parents=True)
            session_profile.mkdir()
            (session_profile / "zen-sessions.jsonlz4").touch()

            with patch("core.zen_profile.Path.home", return_value=home):
                self.assertEqual(find_zen_profile(), session_profile)


if __name__ == "__main__":
    unittest.main()
