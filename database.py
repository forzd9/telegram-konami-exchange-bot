# database.py
import aiosqlite
from datetime import datetime
from typing import Optional, List, Tuple

DB_PATH = "deals.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                deals_count INTEGER DEFAULT 0,
                rating_sum INTEGER DEFAULT 0,
                rating_avg REAL DEFAULT 0.0
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS deals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deal_number TEXT UNIQUE NOT NULL,
                status TEXT NOT NULL DEFAULT 'init',
                chat_id INTEGER NOT NULL,
                first_user_id INTEGER NOT NULL,
                second_user_id INTEGER NOT NULL,
                selected_first_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                frozen INTEGER DEFAULT 0
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ratings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deal_id INTEGER NOT NULL,
                from_user_id INTEGER NOT NULL,
                to_user_id INTEGER NOT NULL,
                stars INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(deal_id) REFERENCES deals(id)
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                deal_id INTEGER PRIMARY KEY,
                session_data TEXT,
                telegram_context TEXT,
                konami_context TEXT,
                FOREIGN KEY(deal_id) REFERENCES deals(id)
            );
        """)
        await db.commit()

async def add_user(user_id: int, username: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?);",
            (user_id, username)
        )
        await db.commit()

async def create_deal(deal_number: str, chat_id: int, first_user_id: int, second_user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO deals (deal_number, status, chat_id, first_user_id, second_user_id) VALUES (?, 'waiting_draw', ?, ?, ?);",
            (deal_number, chat_id, first_user_id, second_user_id)
        )
        await db.commit()
        return cursor.lastrowid

async def get_deal_by_number(deal_number: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM deals WHERE deal_number = ?;", (deal_number,))
        row = await cursor.fetchone()
        return dict(row) if row else None

async def get_deal_by_chat(chat_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM deals WHERE chat_id = ? AND status NOT IN ('completed', 'cancelled') ORDER BY id DESC LIMIT 1;", (chat_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

async def update_deal_status(deal_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE deals SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
            (status, deal_id)
        )
        await db.commit()

async def set_deal_frozen(deal_id: int, frozen: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE deals SET frozen = ? WHERE id = ?;", (int(frozen), deal_id))
        await db.commit()

async def set_selected_first(deal_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE deals SET selected_first_id = ? WHERE id = ?;", (user_id, deal_id))
        await db.commit()

async def add_rating(deal_id: int, from_user_id: int, to_user_id: int, stars: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO ratings (deal_id, from_user_id, to_user_id, stars) VALUES (?, ?, ?, ?);",
            (deal_id, from_user_id, to_user_id, stars)
        )
        # تحديث إحصائيات المستخدم
        await db.execute(
            "UPDATE users SET rating_sum = rating_sum + ?, deals_count = deals_count + 1, rating_avg = (rating_sum + ?) / (deals_count + 1.0) WHERE user_id = ?;",
            (stars, stars, to_user_id)
        )
        await db.commit()

async def get_user_stats(user_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?;", (user_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

async def save_session_data(deal_id: int, session_json: str, telegram_context: str = None, konami_context: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO sessions (deal_id, session_data, telegram_context, konami_context) VALUES (?, ?, ?, ?);",
            (deal_id, session_json, telegram_context, konami_context)
        )
        await db.commit()

async def delete_deal_sessions(deal_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM sessions WHERE deal_id = ?;", (deal_id,))
        await db.commit()

async def cleanup_old_deals(hours: int = 24):
    """حذف بيانات الصفقات المنتهية بعد ساعات"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id FROM deals WHERE status IN ('completed','cancelled') AND updated_at < datetime('now', '-{} hours');".format(hours)
        )
        old_ids = [row[0] for row in await cursor.fetchall()]
        for deal_id in old_ids:
            await db.execute("DELETE FROM sessions WHERE deal_id = ?;", (deal_id,))
        await db.commit()