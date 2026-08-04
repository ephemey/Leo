import unittest

import chengyu
import discord
from discord.ext import commands

import database_commands
from database_commands import DatabaseEditError, DatabaseEditor
from karaoke_points import KaraokePoints


class DatabaseEditorTests(unittest.TestCase):
    def setUp(self):
        self.chengyu = chengyu.ChengyuGame(db_path=":memory:")
        self.karaoke = KaraokePoints(db_path=":memory:")
        self.editor = DatabaseEditor(self.chengyu, self.karaoke)

    def test_lists_live_tables_and_fields(self):
        self.assertIn("chengyu_scores", self.editor.list_tables("chengyu"))
        self.assertIn("karaoke_winners", self.editor.list_tables("karaoke"))
        self.assertEqual(
            self.editor.list_fields("karaoke", "karaoke_winners"),
            ["guild_id", "user_id"],
        )

    def test_sets_chengyu_monthly_score(self):
        self.chengyu.record_score(1, 100, "Alice")
        self.chengyu.record_score(2, 100, "Alice")

        result = self.editor.edit(
            "chengyu",
            "chengyu_scores",
            "set",
            None,
            "valid_entries",
            "25",
            guild_id=1,
            user_id=100,
        )

        self.assertEqual(self.chengyu.get_score(1, 100)["valid_entries"], 25)
        self.assertEqual(self.chengyu.get_score(2, 100)["valid_entries"], 1)
        self.assertEqual(result.old_value, 1)
        self.assertEqual(result.new_value, 25)

    def test_adds_and_deducts_karaoke_score_without_going_below_zero(self):
        self.karaoke.record_points(1, 100, "Alice", 10)

        self.editor.edit(
            "karaoke",
            "karaoke_scores",
            "add",
            None,
            "points",
            "5",
            guild_id=1,
            user_id=100,
        )
        self.assertEqual(self.karaoke.get_monthly_score(1, 100), 15)

        self.editor.edit(
            "karaoke",
            "karaoke_scores",
            "deduct",
            None,
            "points",
            "100",
            guild_id=1,
            user_id=100,
        )
        self.assertEqual(self.karaoke.get_monthly_score(1, 100), 0)

    def test_edits_a_current_winner_user_id(self):
        self.chengyu.set_current_winners(1, [100])

        self.editor.edit(
            "chengyu",
            "chengyu_winners",
            "set",
            None,
            "user_id",
            "200",
            guild_id=1,
            user_id=100,
        )

        self.assertEqual(self.chengyu.get_current_winners(1), [200])

    def test_inserts_and_deletes_a_karaoke_winner(self):
        self.editor.edit(
            "karaoke",
            "karaoke_winners",
            "insert",
            guild_id=1,
            user_id=100,
        )
        self.assertEqual(self.karaoke.get_current_winners(1), [100])

        self.editor.edit(
            "karaoke",
            "karaoke_winners",
            "delete",
            guild_id=1,
            user_id=100,
        )
        self.assertEqual(self.karaoke.get_current_winners(1), [])

    def test_json_record_supports_text_containing_commas(self):
        self.editor.edit(
            "karaoke",
            "karaoke_scores",
            "insert",
            '{"points": 12}',
            guild_id=1,
            user_id=100,
            username="Alice, The Singer",
        )

        leaderboard = self.karaoke.get_leaderboard(1)
        self.assertEqual(leaderboard[0]["username"], "Alice, The Singer")
        self.assertEqual(leaderboard[0]["points"], 12)

    def test_nullable_field_can_be_cleared(self):
        self.karaoke.set_role(1, 99)

        self.editor.edit(
            "karaoke",
            "karaoke_config",
            "set",
            None,
            "role_id",
            "null",
            guild_id=1,
        )

        self.assertIsNone(self.karaoke.get_role(1))

    def test_rejects_unknown_tables_and_fields(self):
        with self.assertRaises(DatabaseEditError):
            self.editor.edit(
                "chengyu",
                "chengyu_scores; DROP TABLE chengyu_scores",
                "set",
                None,
                "valid_entries",
                "5",
                guild_id=1,
                user_id=100,
            )

        with self.assertRaises(DatabaseEditError):
            self.editor.edit(
                "chengyu",
                "chengyu_scores",
                "set",
                None,
                "not_a_field",
                "5",
                guild_id=1,
                user_id=100,
            )

    def test_rejects_selector_that_matches_multiple_records(self):
        self.chengyu.record_score(1, 100, "Alice")
        self.chengyu.record_score(1, 101, "Bob")

        with self.assertRaisesRegex(DatabaseEditError, "multiple records"):
            self.editor.edit(
                "chengyu",
                "chengyu_scores",
                "set",
                None,
                "valid_entries",
                "5",
                guild_id=1,
            )

    def test_rejects_negative_add_or_deduct_amount(self):
        self.chengyu.record_score(1, 100, "Alice")

        with self.assertRaisesRegex(DatabaseEditError, "cannot be negative"):
            self.editor.edit(
                "chengyu",
                "chengyu_scores",
                "add",
                None,
                "valid_entries",
                "-1",
                guild_id=1,
                user_id=100,
            )

    def test_rejects_explicit_or_edited_guild_id(self):
        self.chengyu.record_score(1, 100, "Alice")

        with self.assertRaisesRegex(DatabaseEditError, "selected automatically"):
            self.editor.edit(
                "chengyu",
                "chengyu_scores",
                "set",
                "guild_id=2",
                "valid_entries",
                "5",
                guild_id=1,
                user_id=100,
            )

        with self.assertRaisesRegex(DatabaseEditError, "always scoped"):
            self.editor.edit(
                "chengyu",
                "chengyu_scores",
                "set",
                None,
                "guild_id",
                "2",
                guild_id=1,
                user_id=100,
            )

    def test_rejects_user_option_for_non_user_table(self):
        self.karaoke.set_role(1, 99)

        with self.assertRaisesRegex(DatabaseEditError, "does not contain user records"):
            self.editor.edit(
                "karaoke",
                "karaoke_config",
                "set",
                None,
                "role_id",
                "100",
                guild_id=1,
                user_id=100,
            )


class DatabaseEditCommandTests(unittest.TestCase):
    def test_dbedit_is_owner_checked_and_has_schema_autocomplete(self):
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        game = chengyu.ChengyuGame(db_path=":memory:")
        karaoke = KaraokePoints(db_path=":memory:")
        database_commands.setup(bot, game, karaoke)

        command = bot.tree.get_command("dbedit")

        self.assertIsNotNone(command)
        self.assertEqual(len(command.checks), 1)
        self.assertTrue(command.guild_only)
        parameters = {parameter.name: parameter for parameter in command.parameters}
        self.assertFalse(parameters["user"].required)
        self.assertFalse(parameters["record"].required)
        autocomplete_fields = {
            parameter.name for parameter in command.parameters if parameter.autocomplete
        }
        self.assertEqual(autocomplete_fields, {"table", "field"})


if __name__ == "__main__":
    unittest.main()
