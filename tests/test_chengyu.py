import os
import tempfile
import unittest

import chengyu


class ChengyuGameTests(unittest.TestCase):
    def test_chain_rule_matches_when_pinyin_matches(self):
        game = chengyu.ChengyuGame(db_path=':memory:')
        previous_entry = {"pinyin_raw": "hua4 long2 dian3 jing1"}
        current_entry = {"pinyin_raw": "jing3 jing3 you3 tiao2"}

        self.assertTrue(game.entries_match_chain(previous_entry, current_entry))

    def test_chain_rule_fails_when_pinyin_does_not_match(self):
        game = chengyu.ChengyuGame(db_path=':memory:')
        previous_entry = {"pinyin_raw": "hua4 long2 dian3 jing1"}
        current_entry = {"pinyin_raw": "ren2 shan1 ren2 hai3"}

        self.assertFalse(game.entries_match_chain(previous_entry, current_entry))

    def test_channel_setup_and_leaderboard_storage(self):
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            db_path = handle.name

        try:
            game = chengyu.ChengyuGame(db_path=db_path)
            game.set_channel(1, 42)
            self.assertEqual(game.get_channel(1), 42)

            game.record_score(1, 100, "Alice")
            game.record_score(1, 100, "Alice")
            game.record_score(1, 101, "Bob")

            leaderboard = game.get_leaderboard(1)
            self.assertEqual(leaderboard[0]["user_id"], 100)
            self.assertEqual(leaderboard[0]["valid_entries"], 2)

            game.mark_used_entry(1, 42, "画龙点睛")
            self.assertTrue(game.is_used_entry(1, 42, "画龙点睛"))
        finally:
            os.unlink(db_path)

    def test_role_config_is_stored(self):
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            db_path = handle.name

        try:
            game = chengyu.ChengyuGame(db_path=db_path)
            game.set_channel(1, 42, role_id=99)
            self.assertEqual(game.get_channel(1), 42)
            self.assertEqual(game.get_role(1), 99)
        finally:
            os.unlink(db_path)

    def test_reset_message_mentions_congratulations_and_top_scorers(self):
        game = chengyu.ChengyuGame(db_path=':memory:')
        winners = [
            {"username": "Alice", "valid_entries": 3},
            {"username": "Bob", "valid_entries": 2},
        ]

        message = game.format_reset_message(winners)

        self.assertIn("reset is happening", message.lower())
        self.assertIn("Congratulations", message)
        self.assertIn("Alice", message)
        self.assertIn("Bob", message)

    def test_reset_timer_is_positive(self):
        game = chengyu.ChengyuGame(db_path=':memory:')
        delta = game.get_time_until_reset()
        self.assertGreater(delta.total_seconds(), 0)

    def test_get_score_returns_user_points(self):
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            db_path = handle.name

        try:
            game = chengyu.ChengyuGame(db_path=db_path)
            game.record_score(1, 100, "Alice")
            score = game.get_score(1, 100)

            self.assertEqual(score["user_id"], 100)
            self.assertEqual(score["valid_entries"], 1)
        finally:
            os.unlink(db_path)

    def test_alltime_leaderboard_tracks_across_monthly_resets(self):
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            db_path = handle.name

        try:
            game = chengyu.ChengyuGame(db_path=db_path)
            game.record_score(1, 100, "Alice")
            leaderboard = game.get_alltime_leaderboard(1)

            self.assertEqual(leaderboard[0]["user_id"], 100)
            self.assertEqual(leaderboard[0]["valid_entries"], 1)
        finally:
            os.unlink(db_path)


if __name__ == "__main__":
    unittest.main()
