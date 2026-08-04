import logging
import os
import random
import re
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class ChengyuGame:
    def __init__(self, dictionary=None, db_path: Optional[str] = None):
        self.dictionary = dictionary
        database_path = os.getenv("DATABASE_PATH")
        default_db_path = os.path.join(database_path, "chengyu.db") if database_path else "chengyu.db"
        self.db_path = db_path or default_db_path
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self.channel_states = {}
        self._valid_entries: list[dict] = []
        self._entries_by_first_syllable: dict[str, list[dict]] = {}
        self._init_db()

    def _init_db(self) -> None:
        conn = self.conn
        with self._lock:
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chengyu_winners (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chengyu_reset_state (
                    guild_id INTEGER PRIMARY KEY,
                    year INTEGER NOT NULL,
                    month INTEGER NOT NULL
                )
                """
            )
            conn.commit()

    def _normalize_pinyin(self, syllable: str) -> str:
        syllable = syllable.lower().replace("u:", "v")
        accent_map = str.maketrans({
            "ā": "a",
            "á": "a",
            "ǎ": "a",
            "à": "a",
            "ē": "e",
            "é": "e",
            "ě": "e",
            "è": "e",
            "ī": "i",
            "í": "i",
            "ǐ": "i",
            "ì": "i",
            "ō": "o",
            "ó": "o",
            "ǒ": "o",
            "ò": "o",
            "ū": "u",
            "ú": "u",
            "ǔ": "u",
            "ù": "u",
            "ǖ": "v",
            "ǘ": "v",
            "ǚ": "v",
            "ǜ": "v",
            "ü": "v",
        })
        syllable = syllable.translate(accent_map)
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

    def _split_pinyin(self, raw_pinyin: str) -> list[str]:
        return [self._normalize_pinyin(part) for part in raw_pinyin.split() if part]

    def get_first_syllable(self, entry: dict) -> Optional[str]:
        raw = entry.get("pinyin_raw", "")
        parts = self._split_pinyin(raw)
        return parts[0] if parts else None

    def get_last_syllable(self, entry: dict) -> Optional[str]:
        raw = entry.get("pinyin_raw", "")
        parts = self._split_pinyin(raw)
        return parts[-1] if parts else None

    def rebuild_index(self) -> None:
        """Precompute the valid-chengyu set and a first-syllable index.

        Call this once after the dictionary has finished loading (and after any
        merging of extra sources, e.g. Xinhua idioms, into it). Without this the
        game falls back to scanning ``self.dictionary.by_simplified`` directly.
        """
        if not self.dictionary:
            self._valid_entries = []
            self._entries_by_first_syllable = {}
            return

        valid_entries = []
        by_first_syllable: dict[str, list[dict]] = {}
        for entry in self.dictionary.by_simplified.values():
            if not self.is_valid_chengyu(entry):
                continue
            valid_entries.append(entry)
            first_syllable = self.get_first_syllable(entry)
            if first_syllable:
                by_first_syllable.setdefault(first_syllable, []).append(entry)

        self._valid_entries = valid_entries
        self._entries_by_first_syllable = by_first_syllable
        logger.info("Chengyu index rebuilt: %d valid entries, %d distinct first syllables", len(valid_entries), len(by_first_syllable))

    def _get_valid_entries(self) -> list[dict]:
        if not self._valid_entries and self.dictionary:
            self.rebuild_index()
        return self._valid_entries

    def _get_entries_by_first_syllable(self, syllable: str) -> list[dict]:
        if not self._entries_by_first_syllable and self.dictionary:
            self.rebuild_index()
        return self._entries_by_first_syllable.get(syllable, [])

    def get_used_entries(self, guild_id: int, channel_id: int) -> set[str]:
        conn = self.conn
        rows = conn.execute(
            "SELECT entry FROM chengyu_used_entries WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        ).fetchall()
        return {row[0] for row in rows}

    def is_dead_end(self, guild_id: int, channel_id: int, current_entry: dict) -> bool:
        last_syllable = self.get_last_syllable(current_entry)
        if not last_syllable or not self.dictionary:
            return False

        candidates = self._get_entries_by_first_syllable(last_syllable)
        if not candidates:
            return True

        used_entries = self.get_used_entries(guild_id, channel_id)
        for entry in candidates:
            entry_text = entry.get("simplified") or entry.get("traditional")
            if entry_text not in used_entries:
                return False

        return True

    def get_random_unused_idiom(self, guild_id: int, channel_id: int) -> Optional[dict]:
        if not self.dictionary:
            return None

        valid_entries = self._get_valid_entries()
        if not valid_entries:
            return None

        used_entries = self.get_used_entries(guild_id, channel_id)
        unused = [
            entry for entry in valid_entries
            if (entry.get("simplified") or entry.get("traditional")) not in used_entries
        ]

        if not unused:
            return None

        return random.choice(unused)

    def format_dead_end_message(self, username: str, continuation_entry: dict) -> str:
        entry_text = continuation_entry.get("simplified") or continuation_entry.get("traditional") or "an idiom"
        return (
            f"💥 {username} has killed the game by reaching a dead end! "
            f"Here’s a random unused idiom to continue from: {entry_text}"
        )

    def is_valid_chengyu(self, entry: Optional[dict]) -> bool:
        if not entry:
            return False

        text = (entry.get("simplified") or entry.get("traditional") or entry.get("word") or "").strip()
        if not text or len(text) != 4:
            return False

        if not all("\u4e00" <= ch <= "\u9fff" for ch in text):
            return False

        return True

    def set_channel(self, guild_id: int, channel_id: int, role_id: Optional[int] = None) -> None:
        conn = self.conn
        conn.execute(
            "INSERT INTO chengyu_config (guild_id, channel_id, role_id) VALUES (?, ?, ?) ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id, role_id = excluded.role_id",
            (guild_id, channel_id, role_id),
        )
        conn.commit()
        logger.info("Chengyu channel set for guild=%s to channel=%s role=%s", guild_id, channel_id, role_id)

    def get_channel(self, guild_id: int) -> Optional[int]:
        conn = self.conn
        row = conn.execute(
            "SELECT channel_id FROM chengyu_config WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()
        return int(row[0]) if row else None

    def get_role(self, guild_id: int) -> Optional[int]:
        conn = self.conn
        row = conn.execute(
            "SELECT role_id FROM chengyu_config WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()
        return int(row[0]) if (row and row[0] is not None) else None

    def get_channel_state(self, guild_id: int, channel_id: int) -> dict:
        return self.channel_states.setdefault((guild_id, channel_id), {"entry": None, "used_entries": set()})

    def set_channel_state(self, guild_id: int, channel_id: int, entry: Optional[dict]) -> None:
        self.channel_states[(guild_id, channel_id)] = {"entry": entry, "used_entries": self.channel_states.get((guild_id, channel_id), {}).get("used_entries", set())}

    def mark_used_entry(self, guild_id: int, channel_id: int, entry_text: str) -> None:
        conn = self.conn
        conn.execute(
            "INSERT OR IGNORE INTO chengyu_used_entries (guild_id, channel_id, entry) VALUES (?, ?, ?)",
            (guild_id, channel_id, entry_text),
        )
        conn.commit()
        logger.info("Marked chengyu entry '%s' as used (guild=%s channel=%s)", entry_text, guild_id, channel_id)

    def is_used_entry(self, guild_id: int, channel_id: int, entry_text: str) -> bool:
        conn = self.conn
        row = conn.execute(
            "SELECT 1 FROM chengyu_used_entries WHERE guild_id = ? AND channel_id = ? AND entry = ?",
            (guild_id, channel_id, entry_text),
        ).fetchone()
        return row is not None

    def get_current_winners(self, guild_id: int) -> list[int]:
        conn = self.conn
        rows = conn.execute(
            "SELECT user_id FROM chengyu_winners WHERE guild_id = ?",
            (guild_id,),
        ).fetchall()
        return [row[0] for row in rows]

    def set_current_winners(self, guild_id: int, user_ids: list[int]) -> None:
        conn = self.conn
        with self._lock:
            conn.execute("DELETE FROM chengyu_winners WHERE guild_id = ?", (guild_id,))
            conn.executemany(
                "INSERT INTO chengyu_winners (guild_id, user_id) VALUES (?, ?)",
                [(guild_id, user_id) for user_id in user_ids],
            )
            conn.commit()
        logger.info("Set current chengyu winners for guild=%s to %s", guild_id, user_ids)

    def _get_reset_period(self, guild_id: int) -> Optional[tuple[int, int]]:
        conn = self.conn
        row = conn.execute(
            "SELECT year, month FROM chengyu_reset_state WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()
        return (row[0], row[1]) if row else None

    def _set_reset_period(self, guild_id: int, year: int, month: int) -> None:
        conn = self.conn
        conn.execute(
            "INSERT INTO chengyu_reset_state (guild_id, year, month) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET year = excluded.year, month = excluded.month",
            (guild_id, year, month),
        )
        conn.commit()

    def maybe_reset_monthly_state(self, guild_id: int) -> Optional[list[dict]]:
        now = datetime.now()
        current_period = (now.year, now.month)
        stored_period = self._get_reset_period(guild_id)

        if stored_period is None:
            # First time tracking this guild's reset checkpoint: adopt the
            # current month as the baseline rather than wiping scores that
            # may have been accumulating before this checkpoint existed.
            self._set_reset_period(guild_id, *current_period)
            return None

        if current_period <= stored_period:
            return None

        winners = self.reset_monthly_state(guild_id)
        self._set_reset_period(guild_id, *current_period)
        return winners

    def reset_monthly_state(self, guild_id: int) -> list[dict]:
        conn = self.conn
        with self._lock:
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

        winners = [
            {
                "user_id": user_id,
                "username": username,
                "valid_entries": valid_entries,
            }
            for user_id, username, valid_entries in rows
        ]
        logger.info("Reset monthly chengyu state for guild=%s, winners=%s", guild_id, winners)
        return winners

    def get_next_reset_time(self) -> datetime:
        now = datetime.now()
        if now.month == 12:
            return datetime(now.year + 1, 1, 1, 0, 0, 0)
        return datetime(now.year, now.month + 1, 1, 0, 0, 0)

    def get_time_until_reset(self) -> timedelta:
        return self.get_next_reset_time() - datetime.now()

    def format_reset_message(self, winners: list[dict]) -> str:
        if not winners:
            return "🔄 The Chengyu monthly leaderboard has been reset!"

        winner_lines = ", ".join(
            f"{entry['username']} ({entry['valid_entries']} points)" for entry in winners
        )
        return (
            "🔄 The Chengyu monthly leaderboard has been reset! Congratulations to the new top scorers: "
            f"{winner_lines}."
        )

    def record_score(self, guild_id: int, user_id: int, username: str, points: int = 1) -> None:
        conn = self.conn
        with self._lock:
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
        logger.info("Recorded %d point(s) for %s (user_id=%s guild=%s)", points, username, user_id, guild_id)

    def get_leaderboard(self, guild_id: int) -> list[dict]:
        conn = self.conn
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
        conn = self.conn
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
        conn = self.conn
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
