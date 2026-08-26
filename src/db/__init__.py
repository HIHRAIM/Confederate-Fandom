"""The bot's single SQLite connection and the public db API.

The split is by domain — see each submodule's docstring — but the interface
is flat: every helper is re-imported here, so call sites say
``db.save_post(...)`` and ``db.cur.execute(...)``.

Connection model: one process-wide connection in WAL mode, wrapped in
_LockingConnection. The wrapper is not decoration — the bot has two threads,
the asyncio loop that talks to Telegram and the worker thread the blocking
Pywikibot calls run in (wiki/publish.py), and either may reach the database.
``cur`` is an alias of ``conn``: the facade returns a fresh cursor from every
execute(), so chained fetches never share cursor state between threads. The
database file is opened by RELATIVE path — the process must run with
cwd = src/ (main.py and the control panel both do).

Import order at the bottom matters: submodules do ``from db import conn,
cur`` against this partially-initialized module, which works only because
conn/cur are defined above those imports. Keep new submodule imports at the
bottom, and re-export new helpers here.
"""
import sqlite3
import threading

_db_lock = threading.RLock()
_raw_conn = sqlite3.connect("tprp.db", check_same_thread=False)
_raw_conn.execute("PRAGMA journal_mode=WAL;")
_raw_conn.execute("PRAGMA synchronous=NORMAL;")
_raw_conn.row_factory = sqlite3.Row

class _LockingConnection:
    """Thread-safe facade over sqlite3.Connection.

    `execute()` returns a brand new cursor on every call, so chained
    `.fetchone()/.fetchall()/.lastrowid` always operate on a private cursor.
    All access is guarded by a re-entrant lock to make concurrent use from the
    Telegram half and the publishing thread safe.
    """

    def __init__(self, raw_conn, lock):
        """Wrap `raw_conn`; every locking method below shares `lock`."""
        self._conn = raw_conn
        self._lock = lock

    def execute(self, sql, params=()):
        """Locked sqlite3.Connection.execute — returns a fresh cursor."""
        with self._lock:
            return self._conn.execute(sql, params)

    def executescript(self, sql):
        """Locked executescript (used only by the schema DDL)."""
        with self._lock:
            return self._conn.executescript(sql)

    def commit(self):
        """Locked commit."""
        with self._lock:
            return self._conn.commit()

    def __getattr__(self, name):
        """Everything else (row_factory, backup, …) passes through unlocked —
        acceptable because nothing mutates connection state at runtime."""
        return getattr(self._conn, name)

conn = _LockingConnection(_raw_conn, _db_lock)
cur = conn

def init():
    """Bring the schema up to date (create missing tables, add missing
    columns — strictly additive, see db/schema.py). Called once from main.py
    before the bot starts."""
    from db import schema
    schema.create_all(cur, conn)

from db.posts import (
    POST_KEEP,
    cleanup_old_posts,
    count_posts,
    forget_other_channels,
    get_post,
    get_recent_posts,
    post_entities,
    save_post,
)
from db.slots import (
    get_slot,
    get_slots,
    get_state,
    set_slot,
    set_state,
)
