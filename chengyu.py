import os
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Optional


class ChengyuGame:
    def __init__(self, dictionary=None, db_path: Optional[str] = None):
        self.dictionary = dictionary
        self.db_path = db_path or os.getenv("CHENGYU_DB_PATH", "chengyu.db")
        self.channel_states = {}
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chengyu_config (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    role_id INTEGER
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chengyu_scores (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    valid_entries INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chengyu_used_entries (
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    entry TEXT NOT NULL,
                    PRIMARY KEY (guild_id, channel_id, entry)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chengyu_alltime_scores (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    valid_entries INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )
            conn.commit()

    def _normalize_pinyin(self, syllable: str) -> str:
        syllable = syllable.lower().replace("u:", "v")
        return re.sub(r"\d", "", syllable)

    def entries_match_chain(self, previous_entry: dict, current_entry: dict) -> bool:
        if not previous_entry or not current_entry:
            return True

        previous_parts = previous_entry.get("pinyin_raw", "").split()
        current_parts = current_entry.get("pinyin_raw", "").split()

        if not previous_parts or not current_parts:
            return False

        previous_last = self._normalize_pinyin(previous_parts[-1])
        current_first = self._normalize_pinyin(current_parts[0])
        return previous_last == current_first

    def is_valid_chengyu(self, entry: Optional[dict]) -> bool:
        if not entry:
            return False

        text = (entry.get("simplified") or "").strip()
        if not text or len(text) != 4:
            return False

        if not all("\u4e00" <= ch <= "\u9fff" for ch in text):
            return False

        if entry.get("definitions") is None:
            return False

        return bool(entry.get("definitions"))

    def set_channel(self, guild_id: int, channel_id: int, role_id: Optional[int] = None) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO chengyu_config (guild_id, channel_id, role_id) VALUES (?, ?, ?) ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id, role_id = excluded.role_id",
                (guild_id, channel_id, role_id),
            )
            conn.commit()

    def get_channel(self, guild_id: int) -> Optional[int]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT channel_id FROM chengyu_config WHERE guild_id = ?",
                (guild_id,),
            ).fetchone()
            return int(row[0]) if row else None

    def get_role(self, guild_id: int) -> Optional[int]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT role_id FROM chengyu_config WHERE guild_id = ?",
                (guild_id,),
            ).fetchone()
            return int(row[0]) if row else None

    def get_channel_state(self, guild_id: int, channel_id: int) -> dict:
        return self.channel_states.setdefault((guild_id, channel_id), {"entry": None, "used_entries": set()})

    def set_channel_state(self, guild_id: int, channel_id: int, entry: Optional[dict]) -> None:
        self.channel_states[(guild_id, channel_id)] = {"entry": entry, "used_entries": self.channel_states.get((guild_id, channel_id), {}).get("used_entries", set())}

    def mark_used_entry(self, guild_id: int, channel_id: int, entry_text: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO chengyu_used_entries (guild_id, channel_id, entry) VALUES (?, ?, ?)",
                (guild_id, channel_id, entry_text),
            )
            conn.commit()

    def is_used_entry(self, guild_id: int, channel_id: int, entry_text: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM chengyu_used_entries WHERE guild_id = ? AND channel_id = ? AND entry = ?",
                (guild_id, channel_id, entry_text),
            ).fetchone()
            return row is not None

    def _reset_if_needed(self, guild_id: int) -> None:
        now = datetime.now()
        next_reset = self.get_next_reset_time()
        if now >= next_reset:
            self.reset_monthly_state(guild_id)

    def maybe_reset_monthly_state(self, guild_id: int) -> list[dict]:
        now = datetime.now()
        next_reset = self.get_next_reset_time()
        if now < next_reset:
            return []
        return self.reset_monthly_state(guild_id)

    def reset_monthly_state(self, guild_id: int) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT user_id, username, valid_entries
                FROM chengyu_scores
                WHERE guild_id = ?
                ORDER BY valid_entries DESC, user_id ASC
                LIMIT 3
                """,
                (guild_id,),
            ).fetchall()
            conn.execute("DELETE FROM chengyu_scores WHERE guild_id = ?", (guild_id,))
            conn.execute("DELETE FROM chengyu_used_entries WHERE guild_id = ?", (guild_id,))
            conn.commit()

        return [
            {
                "user_id": user_id,
                "username": username,
                "valid_entries": valid_entries,
            }
            for user_id, username, valid_entries in rows
        ]

    def get_next_reset_time(self) -> datetime:
        now = datetime.now()
        if now.month == 12:
            return datetime(now.year + 1, 1, 1, 0, 0, 0)
        return datetime(now.year, now.month + 1, 1, 0, 0, 0)

    def get_time_until_reset(self) -> timedelta:
        return self.get_next_reset_time() - datetime.now()

    def format_reset_message(self, winners: list[dict]) -> str:
        if not winners:
            return "🔄 The Chengyu monthly reset is happening now."

        winner_lines = ", ".join(
            f"{entry['username']} ({entry['valid_entries']} points)" for entry in winners
        )
        return (
            "🔄 The Chengyu monthly reset is happening now. Congratulations to the new top scorers: "
            f"{winner_lines}."
        )

    def record_score(self, guild_id: int, user_id: int, username: str, points: int = 1) -> None:
        self._reset_if_needed(guild_id)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO chengyu_scores (guild_id, user_id, username, valid_entries)
                VALUES (?, ?, ?, 0)
                ON CONFLICT(guild_id, user_id) DO NOTHING
                """,
                (guild_id, user_id, username),
            )
            conn.execute(
                """
                UPDATE chengyu_scores
                SET username = ?, valid_entries = valid_entries + ?
                WHERE guild_id = ? AND user_id = ?
                """,
                (username, points, guild_id, user_id),
            )
            conn.execute(
                """
                INSERT INTO chengyu_alltime_scores (guild_id, user_id, username, valid_entries)
                VALUES (?, ?, ?, 0)
                ON CONFLICT(guild_id, user_id) DO NOTHING
                """,
                (guild_id, user_id, username),
            )
            conn.execute(
                """
                UPDATE chengyu_alltime_scores
                SET username = ?, valid_entries = valid_entries + ?
                WHERE guild_id = ? AND user_id = ?
                """,
                (username, points, guild_id, user_id),
            )
            conn.commit()

    def get_leaderboard(self, guild_id: int) -> list[dict]:
        self._reset_if_needed(guild_id)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT user_id, username, valid_entries
                FROM chengyu_scores
                WHERE guild_id = ?
                ORDER BY valid_entries DESC, user_id ASC
                """,
                (guild_id,),
            ).fetchall()

        return [
            {
                "user_id": user_id,
                "username": username,
                "valid_entries": valid_entries,
            }
            for user_id, username, valid_entries in rows
        ]

    def get_score(self, guild_id: int, user_id: int) -> Optional[dict]:
        self._reset_if_needed(guild_id)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT user_id, username, valid_entries
                FROM chengyu_scores
                WHERE guild_id = ? AND user_id = ?
                """,
                (guild_id, user_id),
            ).fetchone()

        if not row:
            return None

        user_id, username, valid_entries = row
        return {
            "user_id": user_id,
            "username": username,
            "valid_entries": valid_entries,
        }

    def get_alltime_leaderboard(self, guild_id: int) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT user_id, username, valid_entries
                FROM chengyu_alltime_scores
                WHERE guild_id = ?
                ORDER BY valid_entries DESC, user_id ASC
                """,
                (guild_id,),
            ).fetchall()

        return [
            {
                "user_id": user_id,
                "username": username,
                "valid_entries": valid_entries,
            }
            for user_id, username, valid_entries in rows
        ]
