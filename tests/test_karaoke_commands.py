import unittest
from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands

import karaoke
from karaoke import apply_monthly_reset
from karaoke_points import KaraokePoints


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


def _make_guild(role=None, members=None):
    guild = MagicMock()
    guild.id = 1
    guild.name = "Test Guild"
    guild.get_role = MagicMock(return_value=role)
    guild.get_member = MagicMock(side_effect=lambda uid: (members or {}).get(uid))

    async def _fetch_member(uid):
        member = (members or {}).get(uid)
        if member is None:
            raise discord.NotFound(MagicMock(), "member not found")
        return member

    guild.fetch_member = AsyncMock(side_effect=_fetch_member)
    return guild


class ApplyMonthlyKaraokeResetTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.points = KaraokePoints(db_path=":memory:")
        self.points._set_reset_period(1, 2000, 1)

    async def test_top_three_receive_role_and_are_stored(self):
        self.points.set_role(1, 99)
        self.points.record_points(1, 100, "Alice", 30)
        self.points.record_points(1, 101, "Bob", 20)
        self.points.record_points(1, 102, "Carol", 10)
        self.points.record_points(1, 103, "Dave", 5)

        role = _make_role()
        members = {user_id: _make_member(user_id) for user_id in (100, 101, 102, 103)}
        guild = _make_guild(role=role, members=members)

        await apply_monthly_reset(guild, self.points)

        for user_id in (100, 101, 102):
            members[user_id].add_roles.assert_awaited_once_with(role)
        members[103].add_roles.assert_not_awaited()
        self.assertEqual(self.points.get_current_winners(1), [100, 101, 102])

    async def test_previous_winners_lose_role_before_new_winners_receive_it(self):
        self.points.set_role(1, 99)
        self.points.set_current_winners(1, [200])
        self.points.record_points(1, 100, "Alice", 30)

        role = _make_role()
        old_winner = _make_member(200, roles=[role])
        new_winner = _make_member(100)
        guild = _make_guild(role=role, members={200: old_winner, 100: new_winner})

        await apply_monthly_reset(guild, self.points)

        old_winner.remove_roles.assert_awaited_once_with(role)
        new_winner.add_roles.assert_awaited_once_with(role)
        self.assertEqual(self.points.get_current_winners(1), [100])

    async def test_no_configured_role_still_stores_top_three(self):
        self.points.record_points(1, 100, "Alice", 30)
        self.points.record_points(1, 101, "Bob", 20)
        guild = _make_guild()

        await apply_monthly_reset(guild, self.points)

        guild.get_role.assert_not_called()
        self.assertEqual(self.points.get_current_winners(1), [100, 101])


class KaraokeSetupCommandTests(unittest.TestCase):
    def test_ksetup_is_owner_checked_and_guild_only(self):
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        karaoke.setup(bot, KaraokePoints(db_path=":memory:"))

        command = bot.tree.get_command("ksetup")

        self.assertIsNotNone(command)
        self.assertEqual(len(command.checks), 1)
        self.assertTrue(command.guild_only)
        self.assertTrue(command.parameters[0].required)


if __name__ == "__main__":
    unittest.main()
