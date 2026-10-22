#!/usr/bin/env python3
"""Migrate cookies from Arc (Chromium) into Zen (Firefox), so logged-in
sites stay logged in after switching browsers.

macOS only. Arc stores cookies in an encrypted Chromium database; the
encryption key lives in the login Keychain under "Arc Safe Storage".
This module decrypts Arc's persistent cookies and inserts them into
Zen's cookies.sqlite.

What does NOT transfer (different browser engines):
  * session-only cookies (they expire when the browser closes anyway)
  * logins backed by localStorage / IndexedDB tokens or device binding
    (e.g. Slack). For those, migrate saved passwords instead.

Safety:
  * Zen must be closed (the DB is locked while it runs).
  * cookies.sqlite is backed up before any write.
  * INSERT OR IGNORE: an existing Zen cookie is never overwritten.
  * The Arc key is read locally and never leaves the machine.
"""

import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional, Tuple

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except ImportError:  # pragma: no cover - import guard
    Cipher = None  # type: ignore

from .arc_exporter import Colors
from .zen_profile import find_zen_profile

# Chromium timestamps count microseconds since 1601-01-01; Firefox counts
# from the Unix epoch (1970). These are the offsets between the two epochs.
EPOCH_DELTA_US = 11_644_473_600 * 1_000_000   # microseconds (1601 -> 1970)
EPOCH_DELTA_MS = 11_644_473_600 * 1_000       # milliseconds (1601 -> 1970)

ARC_ROOT = Path(os.path.expanduser("~/Library/Application Support/Arc"))


# --------------------------------------------------------------------------
# Pure helpers (unit tested)
# --------------------------------------------------------------------------

def chromium_us_to_firefox_ms(expires_utc: int) -> int:
    """Convert a Chromium expiry (microseconds since 1601) to the Firefox
    cookie expiry unit, which is MILLISECONDS since the Unix epoch.

    Getting this unit wrong is the classic mistake: Firefox silently drops
    every imported cookie as "already expired" if seconds are used here.
    """
    return int(expires_utc / 1000 - EPOCH_DELTA_MS)


def chromium_us_to_firefox_us(chromium_utc: int) -> int:
    """Convert a Chromium timestamp (microseconds since 1601) to Firefox
    microseconds since the Unix epoch (used for creation/lastAccessed)."""
    return int(chromium_utc - EPOCH_DELTA_US)


def map_same_site(chromium_value: int) -> int:
    """Map Chromium's same_site enum to Firefox's.

    Chromium: -1 unspecified, 0 none, 1 lax, 2 strict.
    Firefox:   0 none,        1 lax,  2 strict.
    """
    return {-1: 0, 0: 0, 1: 1, 2: 2}.get(chromium_value, 0)


def strip_domain_hash(plaintext: bytes, host_key: str) -> bytes:
    """Chromium >= M127 prepends a 32-byte SHA-256 of the cookie's domain to
    the plaintext before encrypting. Strip it when present."""
    if len(plaintext) >= 32 and plaintext[:32] == hashlib.sha256(host_key.encode()).digest():
        return plaintext[32:]
    return plaintext


# --------------------------------------------------------------------------
# Decryption
# --------------------------------------------------------------------------

def get_arc_key() -> bytes:
    """Read "Arc Safe Storage" from the Keychain and derive the AES key.

    Triggers one macOS permission prompt the first time. Raises RuntimeError
    if the key cannot be read (denied, or Arc never installed)."""
    result = subprocess.run(
        ["security", "find-generic-password", "-w", "-s", "Arc Safe Storage"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(
            "Could not read 'Arc Safe Storage' from the Keychain. "
            "Click 'Always Allow' on the macOS prompt and try again."
        )
    password = result.stdout.strip().encode()
    # Chromium on macOS: PBKDF2-HMAC-SHA1, salt "saltysalt", 1003 iterations.
    return hashlib.pbkdf2_hmac("sha1", password, b"saltysalt", 1003, dklen=16)


def decrypt_value(encrypted: bytes, key: bytes, host_key: str) -> Optional[str]:
    """Decrypt a Chromium v10 cookie value (AES-128-CBC, IV = 16 spaces).
    Returns None for values that are not v10-encrypted."""
    if Cipher is None:
        raise RuntimeError("The 'cryptography' package is required. Install it with: pip install cryptography")
    if not encrypted or encrypted[:3] != b"v10":
        return None
    ciphertext = encrypted[3:]
    if len(ciphertext) % 16:
        return None
    decryptor = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).decryptor()
    plaintext = decryptor.update(ciphertext) + decryptor.finalize()
    if plaintext:  # strip PKCS7 padding
        pad = plaintext[-1]
        if 1 <= pad <= 16:
            plaintext = plaintext[:-pad]
    plaintext = strip_domain_hash(plaintext, host_key)
    return plaintext.decode("utf-8", "replace")


# --------------------------------------------------------------------------
# Profile helpers
# --------------------------------------------------------------------------

def get_arc_cookie_db(arc_profile: str = "Default") -> Path:
    """Path to an Arc Chromium profile's cookie database."""
    return ARC_ROOT / "User Data" / arc_profile / "Cookies"


def raise_cookie_limit(profile_path: Path, needed: int) -> None:
    """Raise network.cookie.maxNumber in prefs.js if the incoming count would
    exceed Firefox's default cap (3000), otherwise Zen evicts the overflow.
    Zen must be closed when this is called."""
    prefs = profile_path / "prefs.js"
    if not prefs.exists():
        return
    target = max(6000, needed + 1000)
    lines = [
        line for line in prefs.read_text(encoding="utf-8").splitlines()
        if "network.cookie.maxNumber" not in line
    ]
    lines.append(f'user_pref("network.cookie.maxNumber", {target});')
    prefs.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------

def migrate_cookies(arc_profile: str = "Default") -> bool:
    """Decrypt Arc's persistent cookies and insert them into Zen.
    Returns True on success. Caller must ensure Zen is closed."""
    if sys.platform != "darwin":
        print(f"{Colors.RED}Cookie migration is macOS only.{Colors.RESET}")
        return False

    arc_db = get_arc_cookie_db(arc_profile)
    if not arc_db.exists():
        print(f"{Colors.RED}Arc cookies not found at {arc_db}{Colors.RESET}")
        return False

    profile_path = find_zen_profile()
    if not profile_path:
        print(f"{Colors.RED}No Zen profile found.{Colors.RESET}")
        return False
    zen_db = profile_path / "cookies.sqlite"
    if not zen_db.exists():
        print(f"{Colors.RED}Zen cookies.sqlite not found. Open Zen once, then close it.{Colors.RESET}")
        return False

    try:
        key = get_arc_key()
    except RuntimeError as exc:
        print(f"{Colors.RED}{exc}{Colors.RESET}")
        return False
    print(f"{Colors.GREEN}Got Arc encryption key from Keychain.{Colors.RESET}")

    # Back up Zen's cookie files.
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    for suffix in ("", "-wal", "-shm"):
        source = Path(str(zen_db) + suffix)
        if source.exists():
            shutil.copy2(source, f"{source}.cookiebak_{timestamp}")
    print(f"Backed up Zen cookies (*.cookiebak_{timestamp}).")

    # Read Arc cookies from a copy to avoid lock contention.
    tmp_dir = Path(tempfile.mkdtemp())
    tmp_db = tmp_dir / "arc_cookies.db"
    shutil.copy2(arc_db, tmp_db)
    source = sqlite3.connect(f"file:{tmp_db}?mode=ro", uri=True)
    rows = source.execute(
        "SELECT host_key, name, encrypted_value, path, expires_utc, is_secure, "
        "is_httponly, last_access_utc, creation_utc, samesite, is_persistent, "
        "has_expires FROM cookies"
    ).fetchall()
    source.close()

    imported, duplicate, skipped, failed = _insert_rows(zen_db, rows, key)

    shutil.rmtree(tmp_dir, ignore_errors=True)

    if imported:
        raise_cookie_limit(profile_path, imported + duplicate)

    print()
    print(f"{Colors.GREEN}Cookie migration complete.{Colors.RESET}")
    print(f"  imported            : {imported}")
    print(f"  already in Zen      : {duplicate}")
    print(f"  skipped (session/expired): {skipped}")
    print(f"  failed to decrypt   : {failed}")
    print(f"  total Arc cookies   : {len(rows)}")
    print("\nOpen Zen and check your sites. Anything still logged out uses a")
    print("non-cookie session; import your saved passwords for those.")
    return True


def _insert_rows(zen_db: Path, rows, key: bytes) -> Tuple[int, int, int, int]:
    """Insert decrypted rows into Zen's moz_cookies. Returns
    (imported, duplicate, skipped, failed)."""
    connection = sqlite3.connect(zen_db)
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    cursor = connection.cursor()

    imported = duplicate = skipped = failed = 0
    now_us = int(time.time() * 1_000_000)
    now_ms = int(time.time() * 1000)

    for (host, name, encrypted, path, expires_utc, is_secure, is_httponly,
         last_utc, creation_utc, same_site, is_persistent, has_expires) in rows:
        if not is_persistent or not has_expires:
            skipped += 1
            continue
        try:
            value = decrypt_value(encrypted, key, host)
        except RuntimeError:
            raise
        if value is None:
            failed += 1
            continue
        expiry_ms = chromium_us_to_firefox_ms(expires_utc)
        if expiry_ms <= now_ms:
            skipped += 1
            continue
        last_access = chromium_us_to_firefox_us(last_utc) if last_utc else now_us
        creation = chromium_us_to_firefox_us(creation_utc) if creation_utc else now_us
        try:
            cursor.execute(
                "INSERT OR IGNORE INTO moz_cookies ("
                "originAttributes, name, value, host, path, expiry, lastAccessed, "
                "creationTime, isSecure, isHttpOnly, inBrowserElement, sameSite, "
                "schemeMap, isPartitionedAttributeSet, updateTime) "
                "VALUES ('', ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 0, ?)",
                (name, value, host, path, expiry_ms, last_access, creation,
                 1 if is_secure else 0, 1 if is_httponly else 0,
                 map_same_site(same_site), 2 if is_secure else 1, now_us),
            )
            if cursor.rowcount:
                imported += 1
            else:
                duplicate += 1
        except sqlite3.Error:
            failed += 1

    connection.commit()
    connection.execute("PRAGMA wal_checkpoint(FULL)")
    connection.close()
    return imported, duplicate, skipped, failed
