import hashlib
import sqlite3
import time
import unittest

from core.cookie_migrator import (
    chromium_us_to_firefox_ms,
    chromium_us_to_firefox_us,
    map_same_site,
    strip_domain_hash,
    _insert_rows,
)

# A Chromium timestamp (microseconds since 1601) for a date well in the future.
# 2027-01-01T00:00:00Z == 1798761600 unix seconds.
FUTURE_UNIX_S = 1798761600
FUTURE_CHROMIUM_US = (FUTURE_UNIX_S + 11_644_473_600) * 1_000_000


class ConversionTests(unittest.TestCase):
    def test_expiry_is_milliseconds_not_seconds(self):
        """Firefox cookie expiry is milliseconds; using seconds makes Zen
        treat every imported cookie as expired and purge it on startup."""
        expiry = chromium_us_to_firefox_ms(FUTURE_CHROMIUM_US)
        self.assertEqual(expiry, FUTURE_UNIX_S * 1000)
        self.assertEqual(len(str(expiry)), 13)  # 13 digits == ms for a 2027 date

    def test_timestamp_microseconds_conversion(self):
        micros = chromium_us_to_firefox_us(FUTURE_CHROMIUM_US)
        self.assertEqual(micros, FUTURE_UNIX_S * 1_000_000)

    def test_same_site_mapping(self):
        self.assertEqual(map_same_site(-1), 0)  # unspecified -> none
        self.assertEqual(map_same_site(0), 0)   # none
        self.assertEqual(map_same_site(1), 1)   # lax
        self.assertEqual(map_same_site(2), 2)   # strict
        self.assertEqual(map_same_site(99), 0)  # unknown -> none

    def test_strip_domain_hash_removes_prefix_when_present(self):
        host = ".example.com"
        value = b"session=abc123"
        prefixed = hashlib.sha256(host.encode()).digest() + value
        self.assertEqual(strip_domain_hash(prefixed, host), value)

    def test_strip_domain_hash_keeps_value_without_prefix(self):
        host = ".example.com"
        value = b"session=abc123"
        self.assertEqual(strip_domain_hash(value, host), value)


class InsertRowsTests(unittest.TestCase):
    """_insert_rows should write valid, future-dated cookies and never
    overwrite ones Zen already has."""

    MOZ_COOKIES_SCHEMA = (
        "CREATE TABLE moz_cookies (id INTEGER PRIMARY KEY, originAttributes TEXT "
        "NOT NULL DEFAULT '', name TEXT, value TEXT, host TEXT, path TEXT, expiry "
        "INTEGER, lastAccessed INTEGER, creationTime INTEGER, isSecure INTEGER, "
        "isHttpOnly INTEGER, inBrowserElement INTEGER DEFAULT 0, sameSite INTEGER "
        "DEFAULT 0, schemeMap INTEGER DEFAULT 0, isPartitionedAttributeSet INTEGER "
        "DEFAULT 0, updateTime INTEGER, CONSTRAINT moz_uniqueid UNIQUE "
        "(name, host, path, originAttributes));"
    )

    def _fake_db(self, tmp_path):
        db = tmp_path / "cookies.sqlite"
        conn = sqlite3.connect(db)
        conn.execute(self.MOZ_COOKIES_SCHEMA)
        conn.commit()
        conn.close()
        return db

    def test_inserts_future_cookie_and_dedupes(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as d:
            db = self._fake_db(Path(d))
            key = b"0" * 16

            # Patch decrypt_value so we exercise the DB/timestamp logic without
            # needing a real AES key.
            rows = [
                # host, name, enc, path, expires_utc, is_secure, is_httponly,
                # last_utc, creation_utc, same_site, is_persistent, has_expires
                (".example.com", "sid", b"enc", "/", FUTURE_CHROMIUM_US, 1, 1,
                 FUTURE_CHROMIUM_US, FUTURE_CHROMIUM_US, 1, 1, 1),
                # duplicate unique key -> should be ignored
                (".example.com", "sid", b"enc", "/", FUTURE_CHROMIUM_US, 1, 1,
                 FUTURE_CHROMIUM_US, FUTURE_CHROMIUM_US, 1, 1, 1),
                # session cookie -> skipped
                (".example.com", "tmp", b"enc", "/", FUTURE_CHROMIUM_US, 1, 1,
                 FUTURE_CHROMIUM_US, FUTURE_CHROMIUM_US, 1, 0, 0),
                # already expired -> skipped
                (".old.com", "dead", b"enc", "/", 11_644_473_600 * 1_000_000, 1,
                 1, 0, 0, 0, 1, 1),
            ]
            with patch("core.cookie_migrator.decrypt_value", return_value="value1"):
                imported, duplicate, skipped, failed = _insert_rows(db, rows, key)

            self.assertEqual(imported, 1)
            self.assertEqual(duplicate, 1)
            self.assertEqual(skipped, 2)
            self.assertEqual(failed, 0)

            conn = sqlite3.connect(db)
            expiry, scheme, same_site = conn.execute(
                "SELECT expiry, schemeMap, sameSite FROM moz_cookies"
            ).fetchone()
            conn.close()
            self.assertEqual(expiry, FUTURE_UNIX_S * 1000)   # milliseconds
            self.assertGreater(expiry, int(time.time() * 1000))
            self.assertEqual(scheme, 2)                      # secure -> https
            self.assertEqual(same_site, 1)                   # lax


if __name__ == "__main__":
    unittest.main()
