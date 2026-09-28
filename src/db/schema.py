"""Every CREATE TABLE of the bot, plus the additive column migrations.

This module owns the shape of fd.db and nothing else — no queries, no
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

-- wiki_admins: the people the bot's owner has made "wiki administrators".
-- They may run the script mechanics; the bot's own administrators
-- (config.ADMINS) may do that and appoint these. platform is 'discord' or
-- 'telegram' and user_id is the numeric id on that platform, which together
-- are how a caller is recognised. wiki_user is their account name on Fandom:
-- it is what the bot checks on the wiki before every run (wiki/rights.py:
-- is_wiki_staff), and what goes into the log line saying who asked. The
-- appointment is global; the standing is the wiki's own and is re-checked
-- each time. Written by the /wikiadmin commands, read by tasks/access.py.
CREATE TABLE IF NOT EXISTS wiki_admins (
    platform TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    wiki_user TEXT NOT NULL,
    display_name TEXT,
    added_by TEXT,
    added_at INTEGER,
    PRIMARY KEY (platform, user_id)
);

-- wiki_admin_invites: a Telegram appointment made by @name that has no
-- numeric id yet. The Bot API cannot turn an @name into a person's id —
-- getChat answers for public groups and channels only — so /wikiadmin @name
-- writes the name here, lower-cased, with the Fandom account, and the first
-- message the bot receives from an account holding that @name turns the row
-- into an ordinary wiki_admins row keyed by the id; after that the @name no
-- longer matters, and whoever takes it over later gets nothing. A row lapses
-- after db/admins.py: INVITE_DAYS, because the longer it waits the likelier
-- the @name is to have changed hands. Written by the /wikiadmin command on
-- Telegram, consumed by telegram_bot/people.py.
CREATE TABLE IF NOT EXISTS wiki_admin_invites (
    username TEXT PRIMARY KEY,
    wiki_user TEXT NOT NULL,
    added_by TEXT,
    added_at INTEGER
);

-- user_langs: the language a person chose with /lang, per messenger account.
-- platform is 'discord' or 'telegram', user_id the numeric id there, lang one
-- of the six codes. A row exists only for somebody who chose a language other
-- than English: English is what everybody gets without one, and choosing it
-- deletes the row, so nothing is kept about a person who never asked for
-- anything. Written by the /lang commands, read by utils.lang_of.
CREATE TABLE IF NOT EXISTS user_langs (
    platform TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    lang TEXT NOT NULL,
    updated_at INTEGER,
    PRIMARY KEY (platform, user_id)
);

-- tasks: one run of one or more mechanics over one wiki.
-- wiki is '<family>:<lang>' as utils.wiki_key spells it. mechanics is a JSON
-- list of mechanic codes, run in that order over each page; params is a JSON
-- object with everything the dialog collected. state moves
-- pending -> running -> done | failed | stopped, and 'pending' is also where a
-- task waits for its confirmation. cursor is the seq in task_pages the run
-- has reached, which is what lets a long walk give the worker back to the
-- news between chunks and pick up where it left off after a restart.
-- requested_by_* name the person for the service log: the platform, their
-- numeric id, the name they are shown under, and their Fandom account.
-- schedule_id is the regular run that spawned this one, or NULL for a task
-- somebody asked for by hand. report holds the counters as JSON; error holds
-- the reason a failed task failed, without a traceback — the file the bot
-- sends must carry wiki content and nothing of the machine it runs on.
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wiki TEXT NOT NULL,
    mechanics TEXT NOT NULL,
    params TEXT NOT NULL DEFAULT '{}',
    state TEXT NOT NULL DEFAULT 'pending',
    dry_run INTEGER NOT NULL DEFAULT 0,
    requested_by_platform TEXT,
    requested_by_id INTEGER,
    requested_by_name TEXT,
    requested_by_wiki_user TEXT,
    reply_chat TEXT,
    schedule_id INTEGER,
    created_at INTEGER,
    started_at INTEGER,
    finished_at INTEGER,
    cursor INTEGER NOT NULL DEFAULT 0,
    checked INTEGER NOT NULL DEFAULT 0,
    edited INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    report TEXT,
    error TEXT
);

-- task_pages: the page list of one task, settled before the first edit.
-- A long run has to be interruptible — the news pass may not wait an hour
-- behind a walk of nine thousand articles — so the pages are materialised
-- here in order and the run keeps only its position in tasks.cursor. That
-- also survives a restart: the queue picks the task up at the next page
-- rather than at the first. state is 'todo', 'done', 'skip' or 'fail'; note
-- carries the reason for the last two.
CREATE TABLE IF NOT EXISTS task_pages (
    task_id INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    title TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'todo',
    note TEXT,
    PRIMARY KEY (task_id, seq)
);

-- schedules: a task that repeats. kind is 'hourly' (at the given minutes of
-- every hour), 'daily' (at hour:minute every day) or 'weekly' (at
-- hour:minute on the listed weekdays, 0 = Monday). minutes and weekdays are
-- comma-separated lists. next_run is the unix timestamp the scheduler is
-- waiting for and is recomputed after every firing, so a bot that was down
-- over the hour runs once when it comes back rather than once per missed
-- hour. enabled 0 keeps the row and stops the firing. approval is NULL for a
-- schedule that may run, and 'pending' while a bot administrator has not yet
-- said yes to it (config.SCHEDULE_APPROVAL, discord_bot/approvals.py): a
-- pending row stays disabled, and /schedule on cannot switch it on.
CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wiki TEXT NOT NULL,
    mechanics TEXT NOT NULL,
    params TEXT NOT NULL DEFAULT '{}',
    kind TEXT NOT NULL,
    minutes TEXT,
    hour INTEGER,
    minute INTEGER,
    weekdays TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_by_platform TEXT,
    created_by_id INTEGER,
    created_by_name TEXT,
    created_by_wiki_user TEXT,
    reply_chat TEXT,
    created_at INTEGER,
    last_run INTEGER,
    next_run INTEGER,
    approval TEXT
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
        "schedules": {
            "approval": "TEXT",
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
