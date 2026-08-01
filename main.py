import asyncio
import logging
import os
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

import chengyu
import chengyu_commands
import dictionary_commands
import general_commands
import karaoke_points as karaoke_points_module
import startup_checks
from dictionary import ChineseDictionary, XinhuaDictionary
from karaoke import karaoke_queues
from karaoke import setup as register_karaoke_commands
from logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_PATH = os.getenv("DATABASE_PATH")
CHENGYU_DB_PATH = os.path.join(DATABASE_PATH, "chengyu.db") if DATABASE_PATH else "chengyu.db"
KARAOKE_DB_PATH = os.path.join(DATABASE_PATH, "karaoke.db") if DATABASE_PATH else "karaoke.db"
XINHUA_DATA_DIR = os.getenv("XINHUA_DATA_DIR", "data")

try:
    startup_checks.check_filesystem(CHENGYU_DB_PATH, XINHUA_DATA_DIR)
except RuntimeError as e:
    logger.error("Startup filesystem check failed: %s", e)
    raise SystemExit(1) from e

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)

BOT_START_TIME = datetime.now(timezone.utc)

dictionary = ChineseDictionary()
xinhua_dictionary = XinhuaDictionary()
chengyu_game = chengyu.ChengyuGame(dictionary=dictionary, db_path=CHENGYU_DB_PATH)
karaoke_pts = karaoke_points_module.KaraokePoints(db_path=KARAOKE_DB_PATH)

register_karaoke_commands(bot, karaoke_pts)
chengyu_commands.setup(bot, chengyu_game, dictionary)
dictionary_commands.setup(bot, dictionary, xinhua_dictionary)
dictionary_commands.setup_owner_commands(bot)
general_commands.setup(bot)


def _load_dictionaries():
    dictionary.load_dictionary()
    xinhua_dictionary.load()
    for idiom in xinhua_dictionary.idioms.values():
        converted = xinhua_dictionary.to_chengyu_entry(idiom)
        if not converted:
            continue
        simplified = converted["simplified"]
        if simplified in dictionary.by_simplified:
            continue
        dictionary.by_simplified[simplified] = converted
        dictionary.by_traditional[simplified] = converted
        dictionary.by_pinyin[converted["pinyin_raw"].lower().replace(" ", "")] = converted
        dictionary.by_pinyin[converted["pinyin"].lower().replace(" ", "")] = converted
    chengyu_game.rebuild_index()




async def global_interaction_check(interaction: discord.Interaction) -> bool:
    if interaction.created_at < BOT_START_TIME:
        logger.debug("Discarding replayed interaction from before bot start (command='%s', created=%s)", interaction.command.name if interaction.command else "unknown", interaction.created_at)
        return False
    return True

bot.tree.interaction_check = global_interaction_check


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, discord.app_commands.CheckFailure):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        logger.info("Permission denied for %s on command '%s'", interaction.user, interaction.command.name if interaction.command else "unknown")
        return
    if isinstance(error, discord.app_commands.CommandInvokeError) and isinstance(error.original, discord.NotFound) and error.original.code == 10062:
        logger.debug("Interaction expired before response could be sent (command='%s')", interaction.command.name if interaction.command else "unknown")
        return
    logger.error("Unhandled app command error (command='%s'): %s", interaction.command.name if interaction.command else "unknown", error, exc_info=error)


@tasks.loop(hours=1)
async def monthly_reset_check():
    for guild in bot.guilds:
        try:
            await chengyu_commands.apply_monthly_reset(guild, chengyu_game)
        except Exception:
            logger.exception("Failed to apply monthly Chengyu reset for guild='%s'", guild.name)
        try:
            winners = karaoke_pts.maybe_reset_monthly(guild.id)
            if winners is not None:
                logger.info("Karaoke monthly reset for guild='%s', top scorers=%s", guild.name, winners)
        except Exception:
            logger.exception("Failed to apply monthly karaoke reset for guild='%s'", guild.name)


@bot.event
async def on_ready():
    queue_count = len(karaoke_queues)
    karaoke_queues.clear()
    logger.info("Cleared %d karaoke queue(s) on startup", queue_count)

    await asyncio.to_thread(_load_dictionaries)

    logger.info("Logged in as %s", bot.user.name)
    try:
        synced = await bot.tree.sync()
        logger.info("Successfully synced %d slash command(s) globally.", len(synced))
    except Exception as e:
        logger.error("Error syncing commands: %s", e)

    startup_checks.check_discord_permissions(bot, chengyu_game)

    if not monthly_reset_check.is_running():
        monthly_reset_check.start()


try:
    bot.run(TOKEN)
except discord.PrivilegedIntentsRequired as e:
    logger.error(
        "Missing privileged intents: %s. Enable 'Server Members Intent' and "
        "'Message Content Intent' for this bot in the Discord Developer Portal.",
        e,
    )
    raise SystemExit(1) from e
except discord.LoginFailure as e:
    logger.error("Failed to log in to Discord: %s. Check DISCORD_TOKEN.", e)
    raise SystemExit(1) from e
