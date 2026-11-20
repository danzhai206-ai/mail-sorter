"""判定結果の保存（SQLite）。

SQLite は1つのファイル（data/mail_sorter.db）だけで動くデータベースです。
サーバーを別に立てる必要がないので、学習の最初に向いています。
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id           TEXT PRIMARY KEY,   -- GmailのメールID
    thread_id    TEXT,
    sender       TEXT,
    subject      TEXT,
    received_at  TEXT,
    snippet      TEXT,
    level        TEXT NOT NULL,      -- high / medium / low / junk
    source       TEXT NOT NULL,      -- rule / ai / default / manual
    reason       TEXT,
    applied      INTEGER NOT NULL,   -- Gmailにラベルを付けたか（DRY_RUNなら0）
    corrected    INTEGER NOT NULL DEFAULT 0,  -- ユーザーが手で直したか
    processed_at TEXT NOT NULL
);
"""


@contextmanager
def connect():
    conn = sqlite3.connect(config.DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def is_processed(msg_id: str) -> bool:
    with connect() as conn:
        return conn.execute("SELECT 1 FROM messages WHERE id = ?", (msg_id,)).fetchone() is not None


def save(email, decision, applied: bool) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO messages
               (id, thread_id, sender, subject, received_at, snippet, level, source, reason, applied, corrected, processed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
            (email.id, email.thread_id, email.sender, email.subject, email.date, email.snippet[:300],
             decision.level, decision.source, decision.reason, int(applied),
             datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )


def get(msg_id: str):
    with connect() as conn:
        return conn.execute("SELECT * FROM messages WHERE id = ?", (msg_id,)).fetchone()


def recent(limit: int = 100, level: str | None = None) -> list[sqlite3.Row]:
    sql = "SELECT * FROM messages"
    args: list = []
    if level:
        sql += " WHERE level = ?"
        args.append(level)
    sql += " ORDER BY processed_at DESC LIMIT ?"
    args.append(limit)
    with connect() as conn:
        return conn.execute(sql, args).fetchall()


def counts() -> dict[str, int]:
    with connect() as conn:
        rows = conn.execute("SELECT level, COUNT(*) AS n FROM messages GROUP BY level").fetchall()
    return {r["level"]: r["n"] for r in rows}


def set_level(msg_id: str, level: str, applied: bool) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE messages SET level = ?, source = 'manual', reason = '手で修正', corrected = 1, applied = ? WHERE id = ?",
            (level, int(applied), msg_id),
        )


def unapplied(limit: int = 100) -> list[sqlite3.Row]:
    """判定はしたが、まだGmailにラベルを付けていないメール（お試しモード中に判定したもの）。"""
    with connect() as conn:
        return conn.execute(
            "SELECT id, level FROM messages WHERE applied = 0 ORDER BY processed_at LIMIT ?", (limit,)
        ).fetchall()


def mark_applied(msg_id: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE messages SET applied = 1 WHERE id = ?", (msg_id,))


def recent_corrections(limit: int = 10) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT sender, subject, level FROM messages WHERE corrected = 1 ORDER BY processed_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
