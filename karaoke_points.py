import logging
import os
import sqlite3
import threading
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

MAX_POINTS = 237
POINTS_CAP_TOTAL = 15  # total people in channel (including singer) where cap kicks in


class KaraokePoints:
    def __init__(self, db_path: Optional[str] = None):
        database_path = os.getenv("DATABASE_PATH")
        default_db_path = os.path.join(database_path, "karaoke.db") if database_path else "karaoke.db"
        self.db_path = db_path or default_db_path
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS karaoke_scores (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    points INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS karaoke_alltime_scores (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    points INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS karaoke_reset_state (
                    guild_id INTEGER PRIMARY KEY,
                    year INTEGER NOT NULL,
                    month INTEGER NOT NULL
                )
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS karaoke_config (
                    guild_id INTEGER PRIMARY KEY,
                    role_id INTEGER
                )
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS karaoke_winners (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            self.conn.commit()
        logger.info("karaoke: DB initialised at %s", self.db_path)

    def set_role(self, guild_id: int, role_id: Optional[int]) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO karaoke_config (guild_id, role_id) VALUES (?, ?) "
                "ON CONFLICT(guild_id) DO UPDATE SET role_id = excluded.role_id",
                (guild_id, role_id),
            )
            self.conn.commit()
        logger.info("Karaoke winner role set for guild=%s to role=%s", guild_id, role_id)

    def get_role(self, guild_id: int) -> Optional[int]:
        row = self.conn.execute(
            "SELECT role_id FROM karaoke_config WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()
        return int(row[0]) if (row and row[0] is not None) else None

    def get_current_winners(self, guild_id: int) -> list[int]:
        rows = self.conn.execute(
            "SELECT user_id FROM karaoke_winners WHERE guild_id = ?",
            (guild_id,),
        ).fetchall()
        return [row[0] for row in rows]

    def set_current_winners(self, guild_id: int, user_ids: list[int]) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM karaoke_winners WHERE guild_id = ?", (guild_id,))
            self.conn.executemany(
                "INSERT INTO karaoke_winners (guild_id, user_id) VALUES (?, ?)",
                [(guild_id, user_id) for user_id in user_ids],
            )
            self.conn.commit()
        logger.info("Set current karaoke winners for guild=%s to %s", guild_id, user_ids)

    @staticmethod
    def calculate_points(audience_count: int) -> int:
        """Points awarded to a singer based on how many others are in the voice channel.

        audience_count = VC members excluding the singer.
          0        → 0 pts (singing solo)
          1        → 5 pts (special case)
          2–14     → round(audience_count ** 1.2 * 10)
          15+ (total > POINTS_CAP_TOTAL) → MAX_POINTS (237)
        """
        if audience_count <= 0:
            return 0
        if audience_count == 1:
            return 5
        if audience_count + 1 > POINTS_CAP_TOTAL:  # +1 for the singer
            return MAX_POINTS
        return round(audience_count ** 1.2 * 10)

    def record_points(self, guild_id: int, user_id: int, username: str, points: int) -> int:
        """Add points to both monthly and all-time tables. Returns new monthly total."""
        if points <= 0:
            return self.get_monthly_score(guild_id, user_id)
        with self._lock:
            for table in ("karaoke_scores", "karaoke_alltime_scores"):
                self.conn.execute(
                    f"INSERT INTO {table} (guild_id, user_id, username, points) VALUES (?, ?, ?, 0) "
                    "ON CONFLICT(guild_id, user_id) DO NOTHING",
                    (guild_id, user_id, username),
                )
                self.conn.execute(
                    f"UPDATE {table} SET username = ?, points = points + ? WHERE guild_id = ? AND user_id = ?",
                    (username, points, guild_id, user_id),
                )
            self.conn.commit()
            row = self.conn.execute(
                "SELECT points FROM karaoke_scores WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchone()
        total = row[0] if row else 0
        logger.info(
            "Awarded %d karaoke point(s) to %s (user_id=%s guild=%s), monthly total=%d",
            points, username, user_id, guild_id, total,
        )
        return total

    def get_monthly_score(self, guild_id: int, user_id: int) -> int:
        row = self.conn.execute(
            "SELECT points FROM karaoke_scores WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        return row[0] if row else 0

    def get_alltime_score(self, guild_id: int, user_id: int) -> int:
        row = self.conn.execute(
            "SELECT points FROM karaoke_alltime_scores WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        return row[0] if row else 0

    def get_leaderboard(self, guild_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT user_id, username, points FROM karaoke_scores "
            "WHERE guild_id = ? ORDER BY points DESC, user_id ASC",
            (guild_id,),
        ).fetchall()
        return [{"user_id": r[0], "username": r[1], "points": r[2]} for r in rows]

    def get_alltime_leaderboard(self, guild_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT user_id, username, points FROM karaoke_alltime_scores "
            "WHERE guild_id = ? ORDER BY points DESC, user_id ASC",
            (guild_id,),
        ).fetchall()
        return [{"user_id": r[0], "username": r[1], "points": r[2]} for r in rows]

    def _get_reset_period(self, guild_id: int) -> Optional[tuple[int, int]]:
        row = self.conn.execute(
            "SELECT year, month FROM karaoke_reset_state WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()
        return (row[0], row[1]) if row else None

    def _set_reset_period(self, guild_id: int, year: int, month: int) -> None:
        self.conn.execute(
            "INSERT INTO karaoke_reset_state (guild_id, year, month) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET year = excluded.year, month = excluded.month",
            (guild_id, year, month),
        )
        self.conn.commit()

    def maybe_reset_monthly(self, guild_id: int) -> Optional[list[dict]]:
        """Reset monthly scores if the calendar month has rolled over.

        Returns None when no reset was due, or a (possibly empty) list of top scorers
        when the reset actually fired.
        """
        now = datetime.now()
        current_period = (now.year, now.month)
        stored_period = self._get_reset_period(guild_id)

        if stored_period is None:
            self._set_reset_period(guild_id, *current_period)
            logger.info("karaoke: set reset baseline for guild=%s to %s-%02d", guild_id, current_period[0], current_period[1])
            return None

        if current_period <= stored_period:
            return None

        with self._lock:
            rows = self.conn.execute(
                "SELECT user_id, username, points FROM karaoke_scores "
                "WHERE guild_id = ? ORDER BY points DESC, user_id ASC LIMIT 3",
                (guild_id,),
            ).fetchall()
            self.conn.execute("DELETE FROM karaoke_scores WHERE guild_id = ?", (guild_id,))
            self.conn.commit()

        self._set_reset_period(guild_id, *current_period)
        winners = [{"user_id": r[0], "username": r[1], "points": r[2]} for r in rows]
        logger.info("Reset monthly karaoke scores for guild=%s, top scorers=%s", guild_id, winners)
        return winners
