"""データの保存（SQLite）。

SQLite は1つのファイル（data/mail_sorter.db）だけで動くデータベースです。
サーバーを別に立てる必要がないので、学習の最初に向いています。

テーブルは3つ:
- messages … メールごとの判定結果
- rules    … 仕分けルール（APIで追加・変更・削除できる）
- app_meta … アプリ自身のメモ（「rules.yaml を取り込み済み」など）
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config
from .rules import normalize_conditions

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

CREATE TABLE IF NOT EXISTS rules (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,  -- 番号はDBが自動で振る
    name       TEXT NOT NULL,
    level      TEXT NOT NULL CHECK (level IN ('high', 'medium', 'low', 'junk')),
    position   INTEGER NOT NULL,     -- 判定する順番（小さいほど先）
    conditions TEXT NOT NULL,        -- 条件をJSON文字列で保存 例: {"from_contains": ["boss@"]}
    enabled    INTEGER NOT NULL DEFAULT 1,  -- 0なら一時的に無効
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rules_position ON rules (position);

CREATE TABLE IF NOT EXISTS app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
    import_rules_once(config.load_rules().get("rules") or [])


# ---------- メール（messages） ----------

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
             decision.level, decision.source, decision.reason, int(applied), _now()),
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


# ---------- ルール（rules） ----------

def _rule_to_dict(row: sqlite3.Row) -> dict:
    """DBの1行を、APIや判定でそのまま使える辞書にする（JSONの条件を展開する）。"""
    rule = {"id": row["id"], "name": row["name"], "level": row["level"],
            "position": row["position"], "enabled": bool(row["enabled"])}
    rule.update(json.loads(row["conditions"]))
    return rule


def list_rules(enabled_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM rules"
    if enabled_only:
        sql += " WHERE enabled = 1"
    sql += " ORDER BY position, id"
    with connect() as conn:
        return [_rule_to_dict(r) for r in conn.execute(sql).fetchall()]


def get_rule(rule_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM rules WHERE id = ?", (rule_id,)).fetchone()
    return _rule_to_dict(row) if row else None


def _insert_rule(conn, name: str, level: str, conditions: dict, position: int | None, enabled: bool) -> int:
    if position is None:
        # 順番の指定が無ければ一番最後に追加する
        position = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM rules").fetchone()[0]
    now = _now()
    cur = conn.execute(
        """INSERT INTO rules (name, level, position, conditions, enabled, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (name, level, position, json.dumps(conditions, ensure_ascii=False), int(enabled), now, now),
    )
    return cur.lastrowid  # DBが振った新しい番号


def create_rule(name: str, level: str, conditions: dict, position: int | None = None, enabled: bool = True) -> dict:
    with connect() as conn:
        rule_id = _insert_rule(conn, name, level, conditions, position, enabled)
    return get_rule(rule_id)


def update_rule(rule_id: int, name: str, level: str, conditions: dict,
                position: int | None = None, enabled: bool = True) -> dict | None:
    """ルールを丸ごと置き換える。見つからなければ None。position を省略すると今の順番のまま。"""
    with connect() as conn:
        cur = conn.execute(
            """UPDATE rules SET name = ?, level = ?, position = COALESCE(?, position),
                                conditions = ?, enabled = ?, updated_at = ?
               WHERE id = ?""",
            (name, level, position, json.dumps(conditions, ensure_ascii=False), int(enabled), _now(), rule_id),
        )
        if cur.rowcount == 0:  # 更新された行が0 ＝ その番号のルールが無い
            return None
    return get_rule(rule_id)


def delete_rule(rule_id: int) -> bool:
    with connect() as conn:
        return conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,)).rowcount > 0


def import_rules_once(rules: list[dict]) -> int:
    """rules.yaml のルールを、最初の1回だけDBに取り込む。取り込んだ件数を返す。

    「取り込み済み」の印を app_meta に残すので、あとでAPIからルールを全部消しても
    勝手に復活しない。1回の接続（トランザクション）でまとめて行うので、途中で失敗したら全部取り消される。
    """
    with connect() as conn:
        if conn.execute("SELECT 1 FROM app_meta WHERE key = 'rules_imported'").fetchone():
            return 0
        count = 0
        for rule in rules:
            conditions = normalize_conditions(rule)
            if rule.get("level") not in ("high", "medium", "low", "junk") or not conditions:
                continue  # 重要度が不正・条件なしのルールは取り込まない
            _insert_rule(conn, rule.get("name") or "名前なし", rule["level"], conditions, None, True)
            count += 1
        conn.execute("INSERT INTO app_meta (key, value) VALUES ('rules_imported', ?)", (_now(),))
    return count
