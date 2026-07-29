import os
import tempfile
import unittest
from datetime import datetime

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

    def test_dead_end_is_detected_when_all_continuations_are_used(self):
        game = chengyu.ChengyuGame(db_path=':memory:')
        game.dictionary = type(
            "FakeDict",
            (),
            {
                "by_simplified": {
                    "画龙点睛": {"simplified": "画龙点睛", "pinyin_raw": "hua4 long2 dian3 jing1", "definitions": ["idiom: add the finishing touch"]},
                    "惊天动地": {"simplified": "惊天动地", "pinyin_raw": "jing1 tian1 dong4 di4", "definitions": ["idiom: earth-shattering"]},
                }
            },
        )()
        game.mark_used_entry(1, 42, "惊天动地")

        current_entry = {"simplified": "画龙点睛", "pinyin_raw": "hua4 long2 dian3 jing1", "definitions": ["idiom: add the finishing touch"]}
        self.assertTrue(game.is_dead_end(1, 42, current_entry))

    def test_get_random_unused_idiom_returns_an_unused_entry(self):
        game = chengyu.ChengyuGame(db_path=':memory:')
        game.dictionary = type(
            "FakeDict",
            (),
            {
                "by_simplified": {
                    "画龙点睛": {"simplified": "画龙点睛", "pinyin_raw": "hua4 long2 dian3 jing1", "definitions": ["idiom: add the finishing touch"]},
                    "惊天动地": {"simplified": "惊天动地", "pinyin_raw": "jing1 tian1 dong4 di4", "definitions": ["idiom: earth-shattering"]},
                    "地久天长": {"simplified": "地久天长", "pinyin_raw": "di4 jiu3 tian1 chang2", "definitions": ["idiom: everlasting"]},
                }
            },
        )()
        game.mark_used_entry(1, 42, "惊天动地")

        entry = game.get_random_unused_idiom(1, 42)
        self.assertIsNotNone(entry)
        self.assertIn(entry["simplified"], {"画龙点睛", "地久天长"})

    def test_dead_end_message_includes_username_and_idiom(self):
        game = chengyu.ChengyuGame(db_path=':memory:')
        continuation_entry = {"simplified": "惊天动地", "definitions": ["earth-shattering"]}
        message = game.format_dead_end_message("Alice", continuation_entry)

        self.assertIn("Alice", message)
        self.assertIn("惊天动地", message)

    def test_only_idiom_entries_are_valid(self):
        game = chengyu.ChengyuGame(db_path=':memory:')
        non_idiom = {"simplified": "敦煌石窟", "pinyin_raw": "dun1 huang2 shi2 ku1", "definitions": ["cave complex in Dunhuang"]}
        idiom = {"simplified": "画龙点睛", "pinyin_raw": "hua4 long2 dian3 jing1", "definitions": ["idiom: add the finishing touch"]}

        self.assertFalse(game.is_valid_chengyu(non_idiom))
        self.assertTrue(game.is_valid_chengyu(idiom))

    def test_xinhua_idiom_entries_are_valid(self):
        game = chengyu.ChengyuGame(db_path=':memory:')
        xinhua_idiom = {
            "word": "阿鼻地狱",
            "pinyin": "ā bí dì yù",
            "explanation": "阿鼻梵语的译音，意译为无间，即痛苦无有间断之意。",
        }

        self.assertTrue(game.is_valid_chengyu(xinhua_idiom))

    def test_chain_matches_across_tone_marked_pinyin(self):
        game = chengyu.ChengyuGame(db_path=':memory:')
        previous_entry = {"pinyin_raw": "jing1 tian1 dong4 di4"}
        current_entry = {"pinyin_raw": "dì jiǔ tiān cháng"}

        self.assertTrue(game.entries_match_chain(previous_entry, current_entry))

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

    def test_no_reset_within_the_same_month(self):
        game = chengyu.ChengyuGame(db_path=':memory:')
        game.record_score(1, 100, "Alice")

        # First call just adopts the current month as the baseline checkpoint.
        self.assertEqual(game.maybe_reset_monthly_state(1), [])
        # A second call in the same month must not wipe scores.
        self.assertEqual(game.maybe_reset_monthly_state(1), [])
        self.assertEqual(game.get_score(1, 100)["valid_entries"], 1)

    def test_reset_fires_once_the_stored_period_is_in_the_past(self):
        game = chengyu.ChengyuGame(db_path=':memory:')
        game.record_score(1, 100, "Alice")
        game.record_score(1, 100, "Alice")
        game.record_score(1, 101, "Bob")

        # Simulate a checkpoint from a previous month.
        game._set_reset_period(1, 2000, 1)

        winners = game.maybe_reset_monthly_state(1)

        self.assertEqual(winners[0]["user_id"], 100)
        self.assertEqual(game.get_leaderboard(1), [])

        now = datetime.now()
        self.assertEqual(game._get_reset_period(1), (now.year, now.month))

        # Calling again immediately afterward must not reset a second time.
        self.assertEqual(game.maybe_reset_monthly_state(1), [])


if __name__ == "__main__":
    unittest.main()
