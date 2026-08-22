"""
طبقة قاعدة البيانات.

تستخدم sqlite3 (المكتبة القياسية) لكن كل عملية تُنفَّذ داخل thread منفصل
عبر asyncio.to_thread، بحيث لا تتجمد حلقة الأحداث (event loop) الخاصة
بالبوت أبدًا أثناء القراءة أو الكتابة، وتستطيع عدة مجموعات (chats) العمل
في الوقت نفسه دون أن تتعارض قراءاتها وكتاباتها.

يفتح كل استدعاء اتصالاً قصير العمر خاصًا به (بدل اتصال مشترك بين threads)
مع busy_timeout لتفادي أخطاء "database is locked" عند التزامن العالي.
"""

import asyncio
import sqlite3
from contextlib import contextmanager
from typing import List, Optional, Tuple

from config import DATABASE_PATH


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(DATABASE_PATH, timeout=30)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA busy_timeout=30000;")
    con.execute("PRAGMA foreign_keys=ON;")
    return con


@contextmanager
def _cursor():
    con = _connect()
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


_db_lock = asyncio.Lock()


def _run(fn):
    """يغلّف fn (دالة متزامنة تستقبل con فقط عبر closure) بحيث تُنفَّذ في thread
    منفصل عند استدعائها، دون تجميد حلقة الأحداث. الاستخدام: await _run(op)()

    كل عمليات قاعدة البيانات تمر عبر قفل واحد (asyncio.Lock) لتفادي تعارض
    الكتابة المتزامنة في SQLite بين عدة مجموعات (وما قد ينتج عنه من انتظار
    طويل بسبب busy_timeout). القفل لا يجمّد بقية البوت؛ أي مهمة أخرى (مجموعة
    أخرى، أمر آخر) تستمر بالعمل بينما تنتظر مهمة واحدة دورها في الوصول لقاعدة
    البيانات لجزء من الثانية عادة."""

    def wrapper(*args, **kwargs):
        async def call():
            def sync_call():
                with _cursor() as con:
                    return fn(con, *args, **kwargs)

            async with _db_lock:
                return await asyncio.to_thread(sync_call)

        return call()

    return wrapper


# ---------------------------------------------------------------- SCHEMA ---

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    chat_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'waiting',   -- waiting | running | finished
    round_number INTEGER NOT NULL DEFAULT 0,
    total_rounds INTEGER NOT NULL DEFAULT 0,
    phase TEXT NOT NULL DEFAULT 'waiting',
    scenario_id TEXT,
    scenario_title TEXT,
    admin_id INTEGER,
    started_at TEXT,
    ended_at TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS players (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    full_name TEXT NOT NULL,
    username TEXT,
    role_name TEXT,
    joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    question TEXT,
    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
    ended_at TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    full_name TEXT,
    text TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_messages_chat_round ON messages(chat_id, round_number);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    kind TEXT NOT NULL,                 -- short | long
    content TEXT NOT NULL,
    importance INTEGER NOT NULL DEFAULT 1,
    round_number INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_memories_chat_kind ON memories(chat_id, kind);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    round_number INTEGER,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    round_number INTEGER,
    content TEXT NOT NULL,
    reliability TEXT NOT NULL DEFAULT 'uncertain',  -- solid | partial | uncertain | misleading
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    round_number INTEGER,
    decision_type TEXT NOT NULL,
    prompt TEXT,
    outcome TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS secrets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    revealed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS game_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    scenario_title TEXT,
    ending_type TEXT,
    summary TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS used_content (
    chat_id INTEGER NOT NULL,
    content_type TEXT NOT NULL,
    key TEXT NOT NULL,
    used_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, content_type, key)
);

CREATE TABLE IF NOT EXISTS ability_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    round_number INTEGER,
    user_id INTEGER NOT NULL,
    role_id TEXT NOT NULL,
    ability_type TEXT NOT NULL,
    target_id INTEGER,
    result_summary TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS protections (
    chat_id INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    protected_by INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, round_number, user_id)
);

CREATE TABLE IF NOT EXISTS confrontations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    round_number INTEGER,
    accuser_id INTEGER NOT NULL,
    accuser_name TEXT,
    accused_id INTEGER NOT NULL,
    accused_name TEXT,
    accusation TEXT,
    defense TEXT,
    accuser_reply TEXT,
    defense_reply TEXT,
    verdict TEXT,                 -- convincing | unconvincing | unclear
    convinced_votes INTEGER NOT NULL DEFAULT 0,
    unconvinced_votes INTEGER NOT NULL DEFAULT 0,
    unsure_votes INTEGER NOT NULL DEFAULT 0,
    outcome_note TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_confrontations_chat ON confrontations(chat_id);
"""

# أعمدة أُضيفت بعد الإصدار الأول من المخطط. تُضاف فقط إن كانت غائبة، حتى
# تعمل الترحيلات (migrations) بأمان على قواعد بيانات قديمة موجودة فعلًا
# دون كسرها أو تكرار الإضافة.
_MIGRATIONS = {
    "players": [
        ("role_id", "TEXT"),
        ("ability_uses_left", "INTEGER NOT NULL DEFAULT 0"),
        ("last_ability_round", "INTEGER NOT NULL DEFAULT 0"),
    ],
    "games": [
        ("difficulty", "TEXT NOT NULL DEFAULT 'medium'"),
    ],
}


def _run_migrations_sync(con: sqlite3.Connection):
    for table, columns in _MIGRATIONS.items():
        existing = {row[1] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
        for col_name, col_def in columns:
            if col_name not in existing:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")


def _init_db_sync(con: sqlite3.Connection):
    con.executescript(SCHEMA)
    _run_migrations_sync(con)


async def init_db():
    with _cursor() as con:
        _init_db_sync(con)


# --------------------------------------------------------------- GAMES -----

def _upsert_game_sync(con, chat_id, **fields):
    existing = con.execute("SELECT chat_id FROM games WHERE chat_id=?", (chat_id,)).fetchone()
    if existing:
        set_clause = ", ".join(f"{k}=?" for k in fields)
        con.execute(
            f"UPDATE games SET {set_clause}, updated_at=CURRENT_TIMESTAMP WHERE chat_id=?",
            (*fields.values(), chat_id),
        )
    else:
        cols = ["chat_id", *fields.keys()]
        placeholders = ", ".join("?" for _ in cols)
        con.execute(
            f"INSERT INTO games({', '.join(cols)}) VALUES({placeholders})",
            (chat_id, *fields.values()),
        )


async def upsert_game(chat_id: int, **fields):
    def op(con):
        _upsert_game_sync(con, chat_id, **fields)

    await _run(op)()


async def get_game(chat_id: int) -> Optional[sqlite3.Row]:
    def op(con):
        con.row_factory = sqlite3.Row
        cur = con.execute("SELECT * FROM games WHERE chat_id=?", (chat_id,))
        return cur.fetchone()

    return await _run(op)()


async def get_chat_ids_by_status(status: str) -> List[int]:
    def op(con):
        rows = con.execute("SELECT chat_id FROM games WHERE status=?", (status,)).fetchall()
        return [r[0] for r in rows]

    return await _run(op)()


# -------------------------------------------------------------- PLAYERS ----

async def add_player(chat_id: int, user_id: int, full_name: str, username: Optional[str]):
    def op(con):
        con.execute(
            "INSERT OR IGNORE INTO players(chat_id,user_id,full_name,username) VALUES(?,?,?,?)",
            (chat_id, user_id, full_name, username),
        )

    await _run(op)()


async def get_players(chat_id: int) -> List[Tuple[int, str, Optional[str]]]:
    def op(con):
        return con.execute(
            "SELECT user_id, full_name, username FROM players WHERE chat_id=? ORDER BY joined_at",
            (chat_id,),
        ).fetchall()

    return await _run(op)()


async def set_role_name(chat_id: int, user_id: int, role_name: str):
    def op(con):
        con.execute(
            "UPDATE players SET role_name=? WHERE chat_id=? AND user_id=?",
            (role_name, chat_id, user_id),
        )

    await _run(op)()


async def set_role(chat_id: int, user_id: int, role_id: str, role_name: str, ability_uses: int):
    def op(con):
        con.execute(
            "UPDATE players SET role_id=?, role_name=?, ability_uses_left=?, last_ability_round=0 "
            "WHERE chat_id=? AND user_id=?",
            (role_id, role_name, ability_uses, chat_id, user_id),
        )

    await _run(op)()


async def get_player_row(chat_id: int, user_id: int) -> Optional[sqlite3.Row]:
    def op(con):
        con.row_factory = sqlite3.Row
        return con.execute(
            "SELECT * FROM players WHERE chat_id=? AND user_id=?", (chat_id, user_id)
        ).fetchone()

    return await _run(op)()


async def consume_ability_use(chat_id: int, user_id: int, round_number: int) -> bool:
    """ينقص عدد استخدامات القدرة بواحد إن كان متبقٍّ منها شيء، ويسجّل آخر
    جولة استُخدمت فيها. يعيد True عند النجاح فقط (منع الاستخدام بعد النفاد)."""

    def op(con):
        row = con.execute(
            "SELECT ability_uses_left FROM players WHERE chat_id=? AND user_id=?",
            (chat_id, user_id),
        ).fetchone()
        if not row or row[0] <= 0:
            return False
        con.execute(
            "UPDATE players SET ability_uses_left=ability_uses_left-1, last_ability_round=? "
            "WHERE chat_id=? AND user_id=?",
            (round_number, chat_id, user_id),
        )
        return True

    return await _run(op)()


async def add_ability_log(chat_id, round_number, user_id, role_id, ability_type, target_id, result_summary):
    def op(con):
        con.execute(
            "INSERT INTO ability_log(chat_id, round_number, user_id, role_id, ability_type, target_id, "
            "result_summary) VALUES(?,?,?,?,?,?,?)",
            (chat_id, round_number, user_id, role_id, ability_type, target_id, result_summary),
        )

    await _run(op)()


async def get_ability_log(chat_id: int, limit: int = 30) -> List[sqlite3.Row]:
    def op(con):
        con.row_factory = sqlite3.Row
        return con.execute(
            "SELECT * FROM ability_log WHERE chat_id=? ORDER BY id DESC LIMIT ?", (chat_id, limit)
        ).fetchall()

    rows = await _run(op)()
    return list(reversed(rows))


async def add_protection(chat_id: int, round_number: int, user_id: int, protected_by: int):
    def op(con):
        con.execute(
            "INSERT OR REPLACE INTO protections(chat_id, round_number, user_id, protected_by) VALUES(?,?,?,?)",
            (chat_id, round_number, user_id, protected_by),
        )

    await _run(op)()


async def is_protected(chat_id: int, round_number: int, user_id: int) -> bool:
    def op(con):
        row = con.execute(
            "SELECT 1 FROM protections WHERE chat_id=? AND round_number=? AND user_id=?",
            (chat_id, round_number, user_id),
        ).fetchone()
        return bool(row)

    return await _run(op)()


async def get_active_game_chat_ids_for_user(user_id: int) -> List[int]:
    """يعيد قائمة المجموعات (chat_id) التي للاعب فيها جولة تعمل حاليًا (status='running')
    ودور مسند له. تُستخدم لربط أوامر الخاص (مثل /ability و/myrole) بجولته الصحيحة
    حتى لو كان مشاركًا في أكثر من مجموعة."""

    def op(con):
        rows = con.execute(
            "SELECT p.chat_id FROM players p JOIN games g ON g.chat_id = p.chat_id "
            "WHERE p.user_id=? AND p.role_id IS NOT NULL AND g.status='running'",
            (user_id,),
        ).fetchall()
        return [r[0] for r in rows]

    return await _run(op)()


async def set_difficulty(chat_id: int, difficulty: str):
    await upsert_game(chat_id, difficulty=difficulty)


async def get_difficulty(chat_id: int) -> str:
    row = await get_game(chat_id)
    if row is None:
        return "medium"
    try:
        return row["difficulty"] or "medium"
    except (IndexError, KeyError):
        return "medium"


async def clear_players(chat_id: int):
    def op(con):
        con.execute("DELETE FROM players WHERE chat_id=?", (chat_id,))

    await _run(op)()


async def remove_player(chat_id: int, user_id: int) -> bool:
    def op(con):
        cur = con.execute("DELETE FROM players WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        return cur.rowcount > 0

    return await _run(op)()


# --------------------------------------------------------------- ROUNDS ----

async def create_round(chat_id: int, round_number: int, question: str) -> int:
    def op(con):
        cur = con.execute(
            "INSERT INTO rounds(chat_id, round_number, question) VALUES(?,?,?)",
            (chat_id, round_number, question),
        )
        return cur.lastrowid

    return await _run(op)()


async def close_round(chat_id: int, round_number: int):
    def op(con):
        con.execute(
            "UPDATE rounds SET ended_at=CURRENT_TIMESTAMP WHERE chat_id=? AND round_number=?",
            (chat_id, round_number),
        )

    await _run(op)()


# -------------------------------------------------------------- MESSAGES ---

async def save_message(chat_id: int, round_number: int, user_id: int, full_name: str, text: str):
    def op(con):
        con.execute(
            "INSERT INTO messages(chat_id, round_number, user_id, full_name, text) VALUES(?,?,?,?,?)",
            (chat_id, round_number, user_id, full_name, text),
        )

    await _run(op)()


async def recent_messages(chat_id: int, round_number: int, limit: int = 50) -> List[Tuple[str, str]]:
    def op(con):
        rows = con.execute(
            "SELECT full_name, text FROM messages WHERE chat_id=? AND round_number=? "
            "ORDER BY created_at DESC LIMIT ?",
            (chat_id, round_number, limit),
        ).fetchall()
        return list(reversed(rows))

    return await _run(op)()


async def count_recent_messages(chat_id: int, round_number: int) -> int:
    def op(con):
        row = con.execute(
            "SELECT COUNT(*) FROM messages WHERE chat_id=? AND round_number=?",
            (chat_id, round_number),
        ).fetchone()
        return row[0] if row else 0

    return await _run(op)()


# -------------------------------------------------------------- MEMORIES ---

async def add_memory(chat_id: int, kind: str, content: str, importance: int = 1, round_number: Optional[int] = None):
    def op(con):
        con.execute(
            "INSERT INTO memories(chat_id, kind, content, importance, round_number) VALUES(?,?,?,?,?)",
            (chat_id, kind, content, importance, round_number),
        )

    await _run(op)()


async def get_memories(chat_id: int, kind: str, limit: int = 25) -> List[Tuple[str, int, Optional[int]]]:
    def op(con):
        return con.execute(
            "SELECT content, importance, round_number FROM memories WHERE chat_id=? AND kind=? "
            "ORDER BY id DESC LIMIT ?",
            (chat_id, kind, limit),
        ).fetchall()

    rows = await _run(op)()
    return list(reversed(rows))


async def clear_memory_kind(chat_id: int, kind: str):
    def op(con):
        con.execute("DELETE FROM memories WHERE chat_id=? AND kind=?", (chat_id, kind))

    await _run(op)()


async def clear_all_memory(chat_id: int):
    def op(con):
        con.execute("DELETE FROM memories WHERE chat_id=?", (chat_id,))

    await _run(op)()


# ---------------------------------------------------------------- EVENTS ---

async def add_event(chat_id: int, round_number: Optional[int], content: str):
    def op(con):
        con.execute(
            "INSERT INTO events(chat_id, round_number, content) VALUES(?,?,?)",
            (chat_id, round_number, content),
        )

    await _run(op)()


async def get_events(chat_id: int, limit: int = 20) -> List[str]:
    def op(con):
        rows = con.execute(
            "SELECT content FROM events WHERE chat_id=? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
        return [r[0] for r in rows]

    rows = await _run(op)()
    return list(reversed(rows))


# -------------------------------------------------------------- EVIDENCE ---

async def add_evidence(chat_id: int, round_number: Optional[int], content: str, reliability: str = "uncertain"):
    def op(con):
        con.execute(
            "INSERT INTO evidence(chat_id, round_number, content, reliability) VALUES(?,?,?,?)",
            (chat_id, round_number, content, reliability),
        )

    await _run(op)()


async def get_evidence(chat_id: int, limit: int = 20) -> List[Tuple[str, str]]:
    def op(con):
        rows = con.execute(
            "SELECT content, reliability FROM evidence WHERE chat_id=? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
        return rows

    rows = await _run(op)()
    return list(reversed(rows))


# ------------------------------------------------------------- DECISIONS ---

async def add_decision(chat_id: int, round_number: Optional[int], decision_type: str, prompt: str, outcome: str = ""):
    def op(con):
        con.execute(
            "INSERT INTO decisions(chat_id, round_number, decision_type, prompt, outcome) VALUES(?,?,?,?,?)",
            (chat_id, round_number, decision_type, prompt, outcome),
        )

    await _run(op)()


async def get_decisions(chat_id: int, limit: int = 20) -> List[Tuple[str, str, str]]:
    def op(con):
        return con.execute(
            "SELECT decision_type, prompt, outcome FROM decisions WHERE chat_id=? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()

    rows = await _run(op)()
    return list(reversed(rows))


# ---------------------------------------------------------- CONFRONTATIONS -

async def add_confrontation(
    chat_id: int,
    round_number: Optional[int],
    accuser_id: int,
    accuser_name: str,
    accused_id: int,
    accused_name: str,
    accusation: str,
    defense: str,
    accuser_reply: str,
    defense_reply: str,
    verdict: str,
    convinced_votes: int,
    unconvinced_votes: int,
    unsure_votes: int,
    outcome_note: str = "",
):
    def op(con):
        con.execute(
            """INSERT INTO confrontations(
                chat_id, round_number, accuser_id, accuser_name, accused_id, accused_name,
                accusation, defense, accuser_reply, defense_reply, verdict,
                convinced_votes, unconvinced_votes, unsure_votes, outcome_note
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                chat_id, round_number, accuser_id, accuser_name, accused_id, accused_name,
                accusation, defense, accuser_reply, defense_reply, verdict,
                convinced_votes, unconvinced_votes, unsure_votes, outcome_note,
            ),
        )

    await _run(op)()


async def get_confrontations(chat_id: int, limit: int = 20) -> List[Tuple]:
    def op(con):
        return con.execute(
            """SELECT accuser_name, accused_name, verdict, outcome_note
               FROM confrontations WHERE chat_id=? ORDER BY id DESC LIMIT ?""",
            (chat_id, limit),
        ).fetchall()

    rows = await _run(op)()
    return list(reversed(rows))


async def count_confrontations_against(chat_id: int, accused_id: int) -> int:
    def op(con):
        row = con.execute(
            "SELECT COUNT(*) FROM confrontations WHERE chat_id=? AND accused_id=?",
            (chat_id, accused_id),
        ).fetchone()
        return row[0] if row else 0

    return await _run(op)()


# ---------------------------------------------------------------- SECRETS --

async def add_secret(chat_id: int, user_id: int, content: str):
    def op(con):
        con.execute(
            "INSERT INTO secrets(chat_id, user_id, content) VALUES(?,?,?)",
            (chat_id, user_id, content),
        )

    await _run(op)()


async def get_secret(chat_id: int, user_id: int) -> Optional[str]:
    def op(con):
        row = con.execute(
            "SELECT content FROM secrets WHERE chat_id=? AND user_id=? ORDER BY id DESC LIMIT 1",
            (chat_id, user_id),
        ).fetchone()
        return row[0] if row else None

    return await _run(op)()


async def clear_secrets(chat_id: int):
    def op(con):
        con.execute("DELETE FROM secrets WHERE chat_id=?", (chat_id,))

    await _run(op)()


# ----------------------------------------------------------- GAME HISTORY --

async def add_game_history(chat_id: int, scenario_title: str, ending_type: str, summary: str):
    def op(con):
        con.execute(
            "INSERT INTO game_history(chat_id, scenario_title, ending_type, summary) VALUES(?,?,?,?)",
            (chat_id, scenario_title, ending_type, summary),
        )

    await _run(op)()


# ------------------------------------------------------------ USED CONTENT -

async def get_recently_used(chat_id: int, content_type: str, limit: int = 10) -> List[str]:
    def op(con):
        rows = con.execute(
            "SELECT key FROM used_content WHERE chat_id=? AND content_type=? ORDER BY used_at DESC LIMIT ?",
            (chat_id, content_type, limit),
        ).fetchall()
        return [r[0] for r in rows]

    return await _run(op)()


async def mark_used(chat_id: int, content_type: str, key: str):
    def op(con):
        con.execute(
            "INSERT OR REPLACE INTO used_content(chat_id, content_type, key, used_at) "
            "VALUES(?,?,?,CURRENT_TIMESTAMP)",
            (chat_id, content_type, key[:120]),
        )

    await _run(op)()


async def reset_game_data(chat_id: int):
    """ينظّف بيانات الجولة الحالية (لا يمس game_history) عند بدء لعبة جديدة."""

    def op(con):
        con.execute("DELETE FROM messages WHERE chat_id=?", (chat_id,))
        con.execute("DELETE FROM events WHERE chat_id=?", (chat_id,))
        con.execute("DELETE FROM evidence WHERE chat_id=?", (chat_id,))
        con.execute("DELETE FROM decisions WHERE chat_id=?", (chat_id,))
        con.execute("DELETE FROM secrets WHERE chat_id=?", (chat_id,))
        con.execute("DELETE FROM rounds WHERE chat_id=?", (chat_id,))
        con.execute("DELETE FROM memories WHERE chat_id=?", (chat_id,))
        con.execute("DELETE FROM ability_log WHERE chat_id=?", (chat_id,))
        con.execute("DELETE FROM protections WHERE chat_id=?", (chat_id,))
        con.execute("DELETE FROM players WHERE chat_id=?", (chat_id,))

    await _run(op)()
