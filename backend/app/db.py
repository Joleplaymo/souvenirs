"""Accès SQLite (mode WAL, une connexion par thread)."""
import json
import sqlite3
import threading
from datetime import datetime, timezone

from . import config
from .pipeline import settings

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, admin_token TEXT NOT NULL,
  name TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
  type TEXT NOT NULL, tone TEXT NOT NULL, tz TEXT NOT NULL,
  created_at TEXT NOT NULL, published_at TEXT, raw_purged_at TEXT, is_demo INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS participants (
  id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL, name TEXT NOT NULL,
  token TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL, participant_id INTEGER NOT NULL,
  kind TEXT NOT NULL, text TEXT, filename TEXT, path TEXT, mime TEXT, size INTEGER DEFAULT 0,
  captured_at TEXT NOT NULL, created_at TEXT NOT NULL, source TEXT DEFAULT 'capture',
  duration REAL, width INTEGER, height INTEGER,
  transcript TEXT, transcript_text TEXT, vision TEXT,
  status TEXT DEFAULT 'ready', excluded INTEGER DEFAULT 0, client_id TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS items_event ON items(event_id, captured_at);
CREATE TABLE IF NOT EXISTS uploads (
  id TEXT PRIMARY KEY, event_id INTEGER NOT NULL, participant_id INTEGER NOT NULL,
  kind TEXT NOT NULL, filename TEXT, mime TEXT, size INTEGER NOT NULL, received INTEGER DEFAULT 0,
  captured_at TEXT NOT NULL, source TEXT DEFAULT 'capture', client_id TEXT UNIQUE, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
  event_id INTEGER PRIMARY KEY, text_md TEXT DEFAULT '', selection TEXT DEFAULT '[]',
  montage TEXT, album TEXT, video_ready INTEGER DEFAULT 0, album_ready INTEGER DEFAULT 0,
  video_duration INTEGER DEFAULT 120, ai_mode TEXT, updated_at TEXT,
  pub_text_md TEXT, pub_selection TEXT, pub_has_video INTEGER DEFAULT 0, pub_has_album INTEGER DEFAULT 0,
  pub_version INTEGER DEFAULT 0, current_version INTEGER, published_from INTEGER, video_prompt TEXT,
  video_settings TEXT, music TEXT
);
CREATE TABLE IF NOT EXISTS versions (
  id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL, label TEXT NOT NULL, tone TEXT NOT NULL, type TEXT NOT NULL,
  origin TEXT DEFAULT 'manual', created_at TEXT NOT NULL,
  text_md TEXT DEFAULT '', selection TEXT DEFAULT '[]', montage TEXT, album TEXT,
  video_duration INTEGER, ai_mode TEXT, has_video INTEGER DEFAULT 0, has_album INTEGER DEFAULT 0,
  shared INTEGER DEFAULT 0, video_prompt TEXT,
  video_settings TEXT, music TEXT
);
CREATE INDEX IF NOT EXISTS versions_event ON versions(event_id, id);
CREATE TABLE IF NOT EXISTS tracks (
  id INTEGER PRIMARY KEY, key TEXT UNIQUE, title TEXT NOT NULL, artist TEXT DEFAULT '', license TEXT DEFAULT '',
  source_url TEXT DEFAULT '', credit TEXT DEFAULT '', genres TEXT DEFAULT '', energy INTEGER DEFAULT 3,
  mood TEXT DEFAULT 'joyeux', bpm INTEGER, duration REAL, file TEXT NOT NULL,
  origin TEXT DEFAULT 'library', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL, kind TEXT NOT NULL, params TEXT DEFAULT '{}',
  status TEXT DEFAULT 'queued', step TEXT DEFAULT '', progress REAL DEFAULT 0, message TEXT DEFAULT '',
  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def conn() -> sqlite3.Connection:
    c = getattr(_local, "c", None)
    if c is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(config.DATA_DIR / "souvenirs.db", timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=30000")
        _local.c = c
    return c


# colonnes ajoutées après la première mise en service : (table, colonne, définition)
MIGRATIONS = [
    ("reports", "current_version", "INTEGER"),
    ("reports", "published_from", "INTEGER"),
    ("reports", "video_prompt", "TEXT"),
    ("versions", "shared", "INTEGER DEFAULT 0"),
    ("versions", "video_prompt", "TEXT"),
    ("reports", "video_settings", "TEXT"),
    ("reports", "music", "TEXT"),
    ("versions", "video_settings", "TEXT"),
    ("versions", "music", "TEXT"),
]


def init():
    c = conn()
    for table, col, decl in MIGRATIONS:  # avant le schéma : un index peut dépendre d'une nouvelle colonne
        cols = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
        if cols and col not in cols:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    c.executescript(SCHEMA)
    migrate_values()


def migrate_values():
    """Convertit les anciens types et tons (événements et versions) vers les nouvelles clés. Idempotent."""
    c = conn()
    for table in ("events", "versions"):
        for r in c.execute(f"SELECT id, type, tone FROM {table}").fetchall():
            typ = config.LEGACY_TYPES.get(r["type"], r["type"])
            tone = r["tone"]
            if tone in config.LEGACY_TONES:
                tone = settings.tones_csv(config.LEGACY_TONES[tone])
            if (typ, tone) != (r["type"], r["tone"]):
                c.execute(f"UPDATE {table} SET type=?, tone=? WHERE id=?", (typ, tone, r["id"]))


def q(sql, *args):
    return conn().execute(sql, args).fetchall()


def one(sql, *args):
    return conn().execute(sql, args).fetchone()


def run(sql, *args):
    return conn().execute(sql, args)


def insert(table, **vals):
    cols = ",".join(vals)
    marks = ",".join("?" * len(vals))
    return conn().execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(vals.values())).lastrowid


def update(table, id_col, id_val, **vals):
    sets = ",".join(f"{k}=?" for k in vals)
    conn().execute(f"UPDATE {table} SET {sets} WHERE {id_col}=?", (*vals.values(), id_val))


def jl(s, default=None):
    if not s:
        return default
    try:
        return json.loads(s)
    except ValueError:
        return default


def enqueue(event_id: int, kind: str, **params) -> int:
    return insert("jobs", event_id=event_id, kind=kind, params=json.dumps(params), created_at=now())


def report(event_id: int):
    r = one("SELECT * FROM reports WHERE event_id=?", event_id)
    if r is None:
        insert("reports", event_id=event_id, updated_at=now())
        r = one("SELECT * FROM reports WHERE event_id=?", event_id)
    return r
