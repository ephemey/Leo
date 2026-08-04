import unittest
from unittest.mock import AsyncMock, MagicMock

import chengyu
import chengyu_commands
import discord
from discord.ext import commands
from chengyu_commands import apply_monthly_reset


def _make_game(with_past_checkpoint=True):
    game = chengyu.ChengyuGame(db_path=":memory:")
    if with_past_checkpoint:
        game._set_reset_period(1, 2000, 1)
    return game


def _make_role(role_id=99):
    role = MagicMock()
    role.id = role_id
    return role


def _make_member(user_id, roles=None):
    member = MagicMock()
    member.id = user_id
    member.roles = list(roles or [])
    member.add_roles = AsyncMock()
    member.remove_roles = AsyncMock()
    return member


def _make_channel(channel_id=42):
    channel = MagicMock()
    channel.id = channel_id
    channel.send = AsyncMock()
    return channel


def _make_guild(guild_id=1, role=None, members=None, channel=None):
    import discord

    guild = MagicMock()
    guild.id = guild_id
    guild.name = "Test Guild"
    guild.get_role = MagicMock(return_value=role)
    guild.get_member = MagicMock(side_effect=lambda uid: (members or {}).get(uid))

    async def _fetch_member(uid):
        member = (members or {}).get(uid)
        if member is None:
            raise discord.NotFound(MagicMock(), "member not found")
        return member

    guild.fetch_member = AsyncMock(side_effect=_fetch_member)
    guild.get_channel = MagicMock(return_value=channel)
    return guild


class ApplyMonthlyResetTests(unittest.IsolatedAsyncioTestCase):

    async def test_noop_when_no_reset_due(self):
        game = _make_game(with_past_checkpoint=False)
        # First call sets baseline (no reset); second call is same month (no reset).
        guild = _make_guild()
        await apply_monthly_reset(guild, game)
        await apply_monthly_reset(guild, game)
        guild.get_role.assert_not_called()
        guild.get_channel.assert_not_called()

    async def test_winners_get_role_and_are_announced(self):
        game = _make_game()
        game.set_channel(1, 42, role_id=99)
        game.record_score(1, 100, "Alice")
        game.record_score(1, 101, "Bob")

        role = _make_role(99)
        alice = _make_member(100)
        bob = _make_member(101)
        channel = _make_channel()
        guild = _make_guild(role=role, members={100: alice, 101: bob}, channel=channel)

        with self.assertLogs("chengyu_commands", level="INFO") as cm:
            await apply_monthly_reset(guild, game)

        alice.add_roles.assert_awaited_once_with(role)
        bob.add_roles.assert_awaited_once_with(role)
        self.assertIn(100, game.get_current_winners(1))
        self.assertIn(101, game.get_current_winners(1))
        channel.send.assert_awaited()
        self.assertTrue(any("Applied monthly" in line for line in cm.output))
        self.assertTrue(any("Registered" in line for line in cm.output))

    async def test_previous_winners_lose_role_on_new_reset(self):
        game = _make_game()
        game.set_channel(1, 42, role_id=99)

        role = _make_role(99)
        old_winner = _make_member(200, roles=[role])
        game.set_current_winners(1, [200])

        game.record_score(1, 100, "Alice")
        new_winner = _make_member(100)
        channel = _make_channel()
        guild = _make_guild(role=role, members={200: old_winner, 100: new_winner}, channel=channel)

        await apply_monthly_reset(guild, game)

        old_winner.remove_roles.assert_awaited_once_with(role)
        new_winner.add_roles.assert_awaited_once_with(role)

    async def test_no_role_configured_still_registers_winners_and_announces(self):
        game = _make_game()
        game.set_channel(1, 42)  # no role_id
        game.record_score(1, 100, "Alice")

        channel = _make_channel()
        guild = _make_guild(channel=channel)

        with self.assertLogs("chengyu_commands", level="INFO") as cm:
            await apply_monthly_reset(guild, game)

        guild.get_role.assert_not_called()
        self.assertIn(100, game.get_current_winners(1))
        channel.send.assert_awaited()
        self.assertTrue(any("No winner role configured" in line for line in cm.output))

    async def test_role_not_found_in_guild_logs_warning_and_still_announces(self):
        game = _make_game()
        game.set_channel(1, 42, role_id=99)
        game.record_score(1, 100, "Alice")

        channel = _make_channel()
        # guild.get_role returns None even though role_id=99 is stored
        guild = _make_guild(role=None, members={100: _make_member(100)}, channel=channel)

        with self.assertLogs("chengyu_commands", level="WARNING") as cm:
            await apply_monthly_reset(guild, game)

        self.assertTrue(any("not found" in line for line in cm.output))
        self.assertIn(100, game.get_current_winners(1))
        channel.send.assert_awaited()

    async def test_no_channel_configured_skips_announcement(self):
        game = _make_game()
        # No set_channel call — get_channel returns None
        game.record_score(1, 100, "Alice")

        guild = _make_guild()

        await apply_monthly_reset(guild, game)

        guild.get_channel.assert_not_called()

    async def test_reset_with_no_scorers_still_announces(self):
        game = _make_game()
        game.set_channel(1, 42)  # no role

        channel = _make_channel()
        guild = _make_guild(channel=channel)

        await apply_monthly_reset(guild, game)

        channel.send.assert_awaited()
        msg = channel.send.call_args_list[0][0][0]
        self.assertIn("reset", msg.lower())

    async def test_member_who_left_guild_is_skipped_gracefully(self):
        game = _make_game()
        game.set_channel(1, 42, role_id=99)
        game.record_score(1, 100, "Alice")

        role = _make_role(99)
        channel = _make_channel()
        # get_member returns None for everyone (all left the server)
        guild = _make_guild(role=role, members={}, channel=channel)

        # Should not raise; channel announcement still goes out
        await apply_monthly_reset(guild, game)
        channel.send.assert_awaited()

    async def test_previous_winner_without_role_is_not_remove_called(self):
        """remove_roles should only be called when the member still has the role."""
        game = _make_game()
        game.set_channel(1, 42, role_id=99)

        role = _make_role(99)
        # Previous winner exists but no longer has the role
        old_winner = _make_member(200, roles=[])
        game.set_current_winners(1, [200])

        game.record_score(1, 100, "Alice")
        new_winner = _make_member(100)
        channel = _make_channel()
        guild = _make_guild(role=role, members={200: old_winner, 100: new_winner}, channel=channel)

        await apply_monthly_reset(guild, game)

        old_winner.remove_roles.assert_not_awaited()
        new_winner.add_roles.assert_awaited_once_with(role)


class TimerCommandTests(unittest.TestCase):
    def test_timer_replaces_cytimer(self):
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        game = chengyu.ChengyuGame(db_path=":memory:")
        chengyu_commands.setup(bot, game, MagicMock())

        self.assertIsNotNone(bot.tree.get_command("timer"))
        self.assertIsNone(bot.tree.get_command("cytimer"))
        self.assertIsNone(bot.tree.get_command("cyedit"))


if __name__ == "__main__":
    unittest.main()
