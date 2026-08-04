import os
import tempfile
import unittest
from datetime import datetime

from karaoke_points import KaraokePoints


class CalculatePointsTests(unittest.TestCase):

    def test_solo_singer_earns_zero_points(self):
        self.assertEqual(KaraokePoints.calculate_points(0), 0)

    def test_one_listener_earns_five_points(self):
        self.assertEqual(KaraokePoints.calculate_points(1), 5)

    def test_two_listeners_use_formula(self):
        self.assertEqual(KaraokePoints.calculate_points(2), round(2 ** 1.2 * 10))

    def test_fourteen_listeners_uses_formula_at_cap_boundary(self):
        # 14 others + 1 singer = 15 total; formula naturally produces 237 here
        self.assertEqual(KaraokePoints.calculate_points(14), round(14 ** 1.2 * 10))

    def test_fifteen_listeners_triggers_max_points(self):
        # 15 others + 1 singer = 16 total, exceeds cap of 15
        self.assertEqual(KaraokePoints.calculate_points(15), 237)

    def test_large_audience_always_returns_max_points(self):
        self.assertEqual(KaraokePoints.calculate_points(100), 237)


class RecordAndLeaderboardTests(unittest.TestCase):

    def setUp(self):
        self.game = KaraokePoints(db_path=":memory:")

    def test_points_appear_on_monthly_leaderboard(self):
        self.game.record_points(1, 100, "Alice", 10)
        lb = self.game.get_leaderboard(1)
        self.assertEqual(lb[0]["user_id"], 100)
        self.assertEqual(lb[0]["points"], 10)

    def test_points_accumulate_across_multiple_songs(self):
        self.game.record_points(1, 100, "Alice", 10)
        self.game.record_points(1, 100, "Alice", 7)
        self.assertEqual(self.game.get_leaderboard(1)[0]["points"], 17)

    def test_alltime_leaderboard_tracks_separately(self):
        self.game.record_points(1, 100, "Alice", 10)
        self.assertEqual(self.game.get_alltime_leaderboard(1)[0]["points"], 10)

    def test_leaderboard_sorted_by_points_descending(self):
        self.game.record_points(1, 101, "Bob", 5)
        self.game.record_points(1, 100, "Alice", 15)
        lb = self.game.get_leaderboard(1)
        self.assertEqual(lb[0]["user_id"], 100)
        self.assertEqual(lb[1]["user_id"], 101)

    def test_zero_or_negative_points_not_recorded(self):
        self.game.record_points(1, 100, "Alice", 0)
        self.assertEqual(self.game.get_leaderboard(1), [])

    def test_guilds_are_isolated(self):
        self.game.record_points(1, 100, "Alice", 10)
        self.game.record_points(2, 100, "Alice", 5)
        self.assertEqual(self.game.get_leaderboard(1)[0]["points"], 10)
        self.assertEqual(self.game.get_leaderboard(2)[0]["points"], 5)

    def test_record_points_returns_new_monthly_total(self):
        self.game.record_points(1, 100, "Alice", 10)
        total = self.game.record_points(1, 100, "Alice", 7)
        self.assertEqual(total, 17)

    def test_winner_role_configuration_is_stored(self):
        self.game.set_role(1, 99)
        self.assertEqual(self.game.get_role(1), 99)

    def test_current_winners_are_replaced(self):
        self.game.set_current_winners(1, [100, 101, 102])
        self.assertEqual(self.game.get_current_winners(1), [100, 101, 102])

        self.game.set_current_winners(1, [200])
        self.assertEqual(self.game.get_current_winners(1), [200])

    def test_role_and_winners_survive_database_reopen(self):
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            db_path = handle.name

        try:
            first = KaraokePoints(db_path=db_path)
            first.set_role(1, 99)
            first.set_current_winners(1, [100, 101, 102])
            first.conn.close()

            reopened = KaraokePoints(db_path=db_path)
            self.assertEqual(reopened.get_role(1), 99)
            self.assertEqual(reopened.get_current_winners(1), [100, 101, 102])
            reopened.conn.close()
        finally:
            os.unlink(db_path)


class MonthlyResetTests(unittest.TestCase):

    def setUp(self):
        self.game = KaraokePoints(db_path=":memory:")

    def test_first_call_sets_baseline_and_returns_none(self):
        self.game.record_points(1, 100, "Alice", 10)
        self.assertIsNone(self.game.maybe_reset_monthly(1))
        # Scores must be untouched
        self.assertEqual(self.game.get_leaderboard(1)[0]["points"], 10)

    def test_same_month_call_is_a_noop(self):
        self.game.record_points(1, 100, "Alice", 10)
        self.game.maybe_reset_monthly(1)  # set baseline
        self.assertIsNone(self.game.maybe_reset_monthly(1))
        self.assertEqual(self.game.get_leaderboard(1)[0]["points"], 10)

    def test_reset_fires_when_checkpoint_is_in_the_past(self):
        self.game.record_points(1, 100, "Alice", 20)
        self.game.record_points(1, 101, "Bob", 10)
        self.game._set_reset_period(1, 2000, 1)

        winners = self.game.maybe_reset_monthly(1)

        self.assertIsNotNone(winners)
        self.assertEqual(winners[0]["user_id"], 100)
        self.assertEqual(self.game.get_leaderboard(1), [])

    def test_reset_updates_checkpoint_to_current_month(self):
        self.game._set_reset_period(1, 2000, 1)
        self.game.maybe_reset_monthly(1)
        now = datetime.now()
        self.assertEqual(self.game._get_reset_period(1), (now.year, now.month))

    def test_second_call_after_reset_is_a_noop(self):
        self.game._set_reset_period(1, 2000, 1)
        self.game.maybe_reset_monthly(1)
        self.assertIsNone(self.game.maybe_reset_monthly(1))

    def test_alltime_scores_survive_monthly_reset(self):
        self.game.record_points(1, 100, "Alice", 20)
        self.game._set_reset_period(1, 2000, 1)
        self.game.maybe_reset_monthly(1)

        self.assertEqual(self.game.get_leaderboard(1), [])
        self.assertEqual(self.game.get_alltime_leaderboard(1)[0]["points"], 20)

    def test_empty_guild_reset_returns_empty_list(self):
        self.game._set_reset_period(1, 2000, 1)
        winners = self.game.maybe_reset_monthly(1)
        self.assertEqual(winners, [])

    def test_reset_winners_limited_to_top_three(self):
        for i, name in enumerate(["Alice", "Bob", "Carol", "Dave"], start=100):
            self.game.record_points(1, i, name, (104 - i) * 10)
        self.game._set_reset_period(1, 2000, 1)
        winners = self.game.maybe_reset_monthly(1)
        self.assertEqual(len(winners), 3)


if __name__ == "__main__":
    unittest.main()
