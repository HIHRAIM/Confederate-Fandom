"""Every CREATE TABLE of the bot, plus the additive column migrations.

This module owns the shape of tprp.db and nothing else — no queries, no
business logic. `db.init()` calls `create_all()` once at start-up.

The migration policy is strict because the database is live data: new tables
only via CREATE TABLE IF NOT EXISTS, new columns only via a PRAGMA table_info
check followed by ALTER TABLE ADD COLUMN. Never DROP, never rebuild a table,
never an ALTER that can lose data. Table documentation lives in `--` comments
inside the SQL string: python-level `#` comments would be stripped by the
parent folder's clean_code.py, SQL comments inside a string literal survive.
"""

SCHEMA_SQL = """
-- channel_posts: one row per message the bot saw in the source channel.
-- Written by telegram_bot/channel.py from channel_post and
-- edited_channel_post, read by news.py when it picks the three newest news.
-- date is the Telegram timestamp (unix, UTC) and is what "newest" means;
-- message_id breaks ties inside one second. text is the message text or the
-- caption of its photo, '' when the message carries neither.
-- media_group_id is Telegram's album id: several rows sharing it are one
-- post to a reader and are treated as one news. photo_file_id addresses the
-- largest size of the photo for downloading; photo_unique_id is stable for
-- the same image and is what tells the publisher that a slot already holds
-- this picture. Rows are dropped by cleanup_old_posts once they are far
-- enough behind the newest to never become news again.
-- entities is the post's formatting as a JSON list of
-- {"type", "offset", "length", "url"} — bold, italics, links and the rest,
-- with offsets counted in characters rather than in the UTF-16 units the Bot
-- API uses (richtext.py converts them once, on the way in). NULL means plain
-- text. source says where the row came from: 'api' for a post the bot heard
-- itself, 'preview' for one recovered from the channel's public web preview,
-- which is what tells the automatic sync whose copy it may overwrite.
-- forward_type and forward_name describe a repost: 'chat' with the title of
-- the channel it came from, or 'user' with the name of the person, and NULL
-- in both when the post is the channel's own. The card writes them out after
-- the date (news.py: render_forward).
CREATE TABLE IF NOT EXISTS channel_posts (
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    date INTEGER NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    entities TEXT,
    source TEXT NOT NULL DEFAULT 'api',
    forward_type TEXT,
    forward_name TEXT,
    media_group_id TEXT,
    photo_file_id TEXT,
    photo_unique_id TEXT,
    edited_at INTEGER,
    PRIMARY KEY (chat_id, message_id)
);

-- wiki_slots: what each news slot currently holds, on each wiki the news are
-- published to. One row per (wiki, slot) — wiki is '<family>:<lang>' as
-- config.WIKIS names it, slot 1 is the newest news — written by publisher.py
-- after the wiki accepted the change, read at the next pass to decide what may
-- be skipped. Every wiki keeps its own row for the same slot, because the same
-- news can be up to date on one wiki and still failing on another.
-- message_id names the post the slot came from; image_key is the
-- photo_unique_id of the picture uploaded into the slot's file, or '' when the
-- news had no photo, in which case the card is published without an image
-- block and the slot's file keeps whatever it held.
-- A slot whose image_key already matches is not downloaded and not
-- re-uploaded; the template page is compared with what it should say on every
-- pass regardless, so an edit made by hand on the wiki is undone at the next
-- one.
-- An older database may still carry the single-wiki predecessor of this table,
-- `news_slots`. Nothing reads it any more and nothing here creates it: the
-- migration policy is additive only, so it is left where it is rather than
-- dropped or rewritten.
CREATE TABLE IF NOT EXISTS wiki_slots (
    wiki TEXT NOT NULL,
    slot INTEGER NOT NULL,
    chat_id INTEGER,
    message_id INTEGER,
    image_key TEXT,
    published_at INTEGER,
    PRIMARY KEY (wiki, slot)
);

-- state: the bot's own bookkeeping, one key per line. Holds the numeric id
-- and the @name the source channel resolved to (so the bot filters updates
-- and builds post links without asking Telegram every time), the timestamp
-- and outcome of the last publishing pass, and the last error it saw.
-- Written by main.py and telegram_bot/, read by /status.
CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

def create_all(cur, conn):
    """Create every missing table and add every missing column. Safe to run on
    a live database and safe to run twice."""
    cur.executescript(SCHEMA_SQL)
    conn.commit()
    _add_missing_columns(cur, conn)

def _add_missing_columns(cur, conn):
    """The additive half of the migration: a column is added only when PRAGMA
    table_info says it is not there yet. Nothing here may drop or rewrite."""
    wanted = {
        "channel_posts": {
            "entities": "TEXT",
            "source": "TEXT NOT NULL DEFAULT 'api'",
            "forward_type": "TEXT",
            "forward_name": "TEXT",
            "media_group_id": "TEXT",
            "photo_file_id": "TEXT",
            "photo_unique_id": "TEXT",
            "edited_at": "INTEGER",
        },
        "wiki_slots": {
            "image_key": "TEXT",
            "published_at": "INTEGER",
        },
    }
    for table, columns in wanted.items():
        existing = {row["name"] for row in cur.execute(f"PRAGMA table_info({table})").fetchall()}
        if not existing:
            continue
        for name, decl in columns.items():
            if name not in existing:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    conn.commit()
