"""SQLite-Persistenz für den Handball-Tracker."""
import os
import sqlite3
import threading
import time

DATA_DIR = os.environ.get("DATA_DIR", "./data")
DB_PATH = os.path.join(DATA_DIR, "handball.db")

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    short TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '#1e6fd9',
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    number TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    home_team_id INTEGER,
    away_team_id INTEGER,
    home_name TEXT NOT NULL,
    away_name TEXT NOT NULL,
    home_color TEXT NOT NULL,
    away_color TEXT NOT NULL,
    competition TEXT NOT NULL DEFAULT '',
    venue TEXT NOT NULL DEFAULT '',
    game_date TEXT NOT NULL DEFAULT '',
    half_minutes INTEGER NOT NULL DEFAULT 30,
    halves INTEGER NOT NULL DEFAULT 2,
    status TEXT NOT NULL DEFAULT 'planned',
    clock_half INTEGER NOT NULL DEFAULT 1,
    clock_running INTEGER NOT NULL DEFAULT 0,
    clock_elapsed_ms INTEGER NOT NULL DEFAULT 0,
    clock_anchor_ms INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    finished_at INTEGER
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    side TEXT,
    half INTEGER NOT NULL,
    game_ms INTEGER NOT NULL,
    player_id INTEGER,
    player_number TEXT,
    player_name TEXT,
    seven_m INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_game ON events(game_id, game_ms);
CREATE INDEX IF NOT EXISTS idx_players_team ON players(team_id);
"""


def now_ms() -> int:
    return int(time.time() * 1000)


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        os.makedirs(DATA_DIR, exist_ok=True)
        c = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.executescript(SCHEMA)
        _conn = c
    return _conn


def query(sql: str, params: tuple = ()) -> list[dict]:
    with _lock:
        return [dict(r) for r in conn().execute(sql, params).fetchall()]


def one(sql: str, params: tuple = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple = ()) -> int:
    with _lock:
        cur = conn().execute(sql, params)
        return cur.lastrowid


def transaction():
    """Kontextmanager für mehrere Statements unter einem Lock."""
    return _Tx()


class _Tx:
    def __enter__(self):
        _lock.acquire()
        conn().execute("BEGIN")
        return conn()

    def __exit__(self, exc_type, *_):
        try:
            conn().execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            _lock.release()
