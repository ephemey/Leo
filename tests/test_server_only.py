import unittest
from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands

import chengyu_commands
import database_commands
import dictionary_commands
import general_commands
import karaoke
from bot_policy import SERVER_ONLY_MESSAGE


def _make_bot() -> commands.Bot:
    return commands.Bot(command_prefix="!", intents=discord.Intents.none())


class ServerOnlyCommandTests(unittest.TestCase):
    def test_every_slash_command_is_guild_only(self):
        bot = _make_bot()
        general_commands.setup(bot)
        dictionary_commands.setup(bot, MagicMock(), MagicMock())
        chengyu_commands.setup(bot, MagicMock(), MagicMock())
        karaoke.setup(bot, MagicMock())
        database_commands.setup(bot, MagicMock(), MagicMock())

        commands_by_name = {command.name: command for command in bot.tree.get_commands()}

        self.assertEqual(len(commands_by_name), 20)
        self.assertTrue(
            all(command.guild_only for command in commands_by_name.values()),
            [
                command.name
                for command in commands_by_name.values()
                if not command.guild_only
            ],
        )

    def test_owner_sync_command_is_guild_only(self):
        bot = _make_bot()
        dictionary_commands.setup_owner_commands(bot)

        command = bot.get_command("sync")

        self.assertIsNotNone(command)
        self.assertTrue(
            any(
                "guild_only" in getattr(check, "__qualname__", "")
                for check in command.checks
            )
        )


class DirectMessageTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_message_receives_server_only_notice(self):
        bot = _make_bot()
        chengyu_commands.setup(bot, MagicMock(), MagicMock())
        message = MagicMock()
        message.author.bot = False
        message.guild = None
        message.channel.send = AsyncMock()

        await bot.on_message(message)

        message.channel.send.assert_awaited_once_with(SERVER_ONLY_MESSAGE)

    async def test_bot_direct_message_is_ignored(self):
        bot = _make_bot()
        chengyu_commands.setup(bot, MagicMock(), MagicMock())
        message = MagicMock()
        message.author.bot = True
        message.guild = None
        message.channel.send = AsyncMock()

        await bot.on_message(message)

        message.channel.send.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
