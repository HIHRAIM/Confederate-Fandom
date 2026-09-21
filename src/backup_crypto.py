"""Encrypted, consistent SQLite backups — standard library only.

Builds an authenticated-encrypted snapshot of the database:

  * The snapshot is taken with SQLite's online-backup API, so it is internally
    consistent even while the bot keeps writing (the DB runs in WAL mode).
  * The snapshot bytes are encrypted with an authenticated stream cipher built on
    BLAKE2: a keyed-BLAKE2 keystream in counter mode (XORed with the plaintext),
    plus a keyed-BLAKE2 tag over the ciphertext (encrypt-then-MAC). This uses only
    the Python standard library, so the bot needs no third-party crypto package.
    Whatever stores the file only ever sees ciphertext it cannot read or tamper
    with undetected.

The key is read from the BACKUP_KEY environment variable and is DIFFERENT per
project. Keep it out of the repo and store a copy somewhere other than the
server (password manager + offline copy): if the key is lost, every existing
backup becomes permanently unreadable.

The reason the file is encrypted at all is where it goes: a Telegram topic or
a Discord channel, which keeps it for as long as the chat exists and shows it
to everybody who can read there. `fd.db` holds who was appointed on which
wiki, every task anybody has asked for and the page lists they walked.

There is nothing here for encrypting a short secret, and its absence is
deliberate. This bot keeps no secret in its database at all: the two it has
— the messenger tokens and the wiki BotPassword — live in `src/.env` and in
the copy `wiki/site.py` writes for Pywikibot, and neither ever reaches
`fd.db`. A helper for putting one there, written before anything needs it,
would only be a way of starting.

Restore a backup with restore_backup.py.
"""
import hashlib
import hmac
import os
import sqlite3
import struct
import tempfile

ENC_SUFFIX = ".enc"
_MAGIC = b"BKP1"

DB_FILE = "fd.db"
"""The database this bot backs up, by the same relative path db/ opens it with.

Relative on purpose: the process runs with cwd = src/ (main.py and the control
panel both start it that way), and a backup that resolved the path differently
from the connection would quietly snapshot a different file."""

def _consistent_snapshot_bytes(db_path):
    """Return the bytes of a consistent copy of db_path (safe under WAL writes)."""
    fd, tmp = tempfile.mkstemp(suffix=".dbsnap")
    os.close(fd)
    leftovers = (tmp, tmp + "-wal", tmp + "-shm", tmp + "-journal")
    try:
        src = sqlite3.connect(db_path)
        try:
            dst = sqlite3.connect(tmp)
            try:
                with dst:
                    src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        with open(tmp, "rb") as f:
            return f.read()
    finally:
        for path in leftovers:
            try:
                os.remove(path)
            except OSError:
                pass

def _master_key():
    """The backup key from the environment. Refuses to proceed when unset:
    silently writing a plaintext copy of the whole database would be worse
    than failing the backup."""
    key = os.environ.get("BACKUP_KEY")
    if not key:
        raise RuntimeError(
            "BACKUP_KEY is not set - refusing to produce an unencrypted backup"
        )
    return key.encode("utf-8")

def _subkeys(master):
    """Derive separate encryption and authentication keys from the master
    key — one key must never do both jobs."""
    base = hashlib.sha256(master).digest()
    k_enc = hashlib.blake2b(b"enc", key=base, digest_size=32).digest()
    k_mac = hashlib.blake2b(b"mac", key=base, digest_size=32).digest()
    return k_enc, k_mac

def _keystream(k_enc, nonce, length):
    """Keystream bytes: keyed BLAKE2 over nonce+counter, concatenated until
    long enough. The nonce makes the stream unique per backup, which is what
    keeps XOR safe here."""
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hashlib.blake2b(nonce + struct.pack(">Q", counter), key=k_enc, digest_size=64).digest()
        counter += 1
    return bytes(out[:length])

def _xor(a, b):
    """XOR two equal-length byte strings (via one big-integer operation,
    which is far faster than a Python loop over megabytes)."""
    if not a:
        return b""
    return (int.from_bytes(a, "big") ^ int.from_bytes(b, "big")).to_bytes(len(a), "big")

def encrypt_bytes(master, plaintext):
    """Authenticated-encrypt plaintext. master = BACKUP_KEY bytes. Returns bytes."""
    k_enc, k_mac = _subkeys(master)
    nonce = os.urandom(16)
    ciphertext = _xor(plaintext, _keystream(k_enc, nonce, len(plaintext)))
    tag = hashlib.blake2b(nonce + ciphertext, key=k_mac, digest_size=32).digest()
    return _MAGIC + nonce + tag + ciphertext

def decrypt_bytes(master, blob):
    """Verify and decrypt a blob produced by encrypt_bytes. Returns plaintext bytes."""
    if len(blob) < 52 or blob[:4] != _MAGIC:
        raise ValueError("Unrecognized backup format")
    nonce, tag, ciphertext = blob[4:20], blob[20:52], blob[52:]
    k_enc, k_mac = _subkeys(master)
    expected = hashlib.blake2b(nonce + ciphertext, key=k_mac, digest_size=32).digest()
    if not hmac.compare_digest(tag, expected):
        raise ValueError("Authentication failed - wrong key or corrupted backup")
    return _xor(ciphertext, _keystream(k_enc, nonce, len(ciphertext)))

def build_encrypted_backup(db_path):
    """Consistent snapshot of db_path, encrypted and authenticated. Returns bytes."""
    return encrypt_bytes(_master_key(), _consistent_snapshot_bytes(db_path))

def encrypted_filename(db_path):
    """Suggested upload filename, e.g. 'fd.db' -> 'fd.db.enc'."""
    return os.path.basename(db_path) + ENC_SUFFIX

def available():
    """Whether a backup can be made at all — that is, whether BACKUP_KEY is
    set. What asks is the periodic job, which stays quiet on a deployment that
    has not set a key rather than reporting the same failure twice a day, and
    /backup, which says so once to the person who asked."""
    return bool(os.environ.get("BACKUP_KEY"))

def build_backup():
    """This bot's database, snapshotted and encrypted. -> bytes.

    The zero-argument form the three call sites use, so that the name of the
    file lives in one place (DB_FILE) rather than in each of them."""
    return build_encrypted_backup(DB_FILE)

def backup_filename():
    """What to call the file this bot's backup goes out as."""
    return encrypted_filename(DB_FILE)
