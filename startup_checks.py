import logging
import os
import sqlite3

import discord

logger = logging.getLogger(__name__)

REQUIRED_CHANNEL_PERMISSIONS = [
    "view_channel",
    "send_messages",
    "embed_links",
    "add_reactions",
    "read_message_history",
]


def check_filesystem(chengyu_db_path: str, xinhua_data_dir: str) -> None:
    """Verify the bot can read/write the files and databases it depends on.

    Raises RuntimeError with a clear message if something is not accessible,
    so startup fails fast instead of breaking later inside a command handler.
    """
    _check_sqlite_db(chengyu_db_path)
    _check_data_dir(xinhua_data_dir)


def _check_sqlite_db(db_path: str) -> None:
    if db_path == ":memory:":
        return

    db_dir = os.path.dirname(os.path.abspath(db_path)) or "."
    if not os.path.isdir(db_dir):
        raise RuntimeError(f"Chengyu database directory does not exist: {db_dir}")
    if not os.access(db_dir, os.W_OK):
        raise RuntimeError(f"Chengyu database directory is not writable: {db_dir}")
    if os.path.exists(db_path) and not os.access(db_path, os.R_OK | os.W_OK):
        raise RuntimeError(f"Chengyu database file is not readable/writable: {db_path}")

    try:
        conn = sqlite3.connect(db_path)
        conn.execute("SELECT 1")
        conn.close()
    except sqlite3.Error as e:
        raise RuntimeError(f"Failed to open Chengyu database at {db_path}: {e}") from e

    logger.info("Chengyu database is accessible: %s", db_path)


def _check_data_dir(data_dir: str) -> None:
    try:
        os.makedirs(data_dir, exist_ok=True)
    except OSError as e:
        raise RuntimeError(f"Failed to create Xinhua data directory {data_dir}: {e}") from e

    if not os.access(data_dir, os.W_OK):
        raise RuntimeError(f"Xinhua data directory is not writable: {data_dir}")

    logger.info("Xinhua data directory is accessible: %s", data_dir)


def check_discord_permissions(bot: discord.Client, chengyu_game) -> None:
    """Log warnings for any Discord-side permissions the bot is missing.

    Runs once the bot is connected (from on_ready), since permissions and
    guild membership are only known after login. Never raises: a
    misconfigured guild shouldn't take down the whole bot.
    """
    if not bot.intents.members:
        logger.warning("Server Members Intent is not enabled; role cleanup/assignment may miss members.")
    if not bot.intents.message_content:
        logger.warning("Message Content Intent is not enabled; Chengyu chain messages will not be readable.")

    for guild in bot.guilds:
        _check_guild_permissions(guild, chengyu_game)


def _check_guild_permissions(guild: discord.Guild, chengyu_game) -> None:
    me = guild.me
    if me is None:
        logger.warning("Bot member not found in guild '%s' (%s); skipping permission check.", guild.name, guild.id)
        return

    missing_global = [
        perm for perm in ("view_channel", "send_messages", "use_application_commands")
        if not getattr(me.guild_permissions, perm)
    ]
    if missing_global:
        logger.warning("Bot is missing guild-level permissions in '%s': %s", guild.name, ", ".join(missing_global))

    channel_id = chengyu_game.get_channel(guild.id)
    if channel_id is not None:
        channel = guild.get_channel(channel_id)
        if channel is None:
            logger.warning("Configured Chengyu channel %s not found in guild '%s'.", channel_id, guild.name)
        else:
            perms = channel.permissions_for(me)
            missing = [perm for perm in REQUIRED_CHANNEL_PERMISSIONS if not getattr(perms, perm)]
            if missing:
                logger.warning(
                    "Bot is missing channel permissions in #%s (guild '%s'): %s",
                    channel.name, guild.name, ", ".join(missing),
                )

    role_id = chengyu_game.get_role(guild.id)
    if role_id is not None:
        role = guild.get_role(role_id)
        if role is None:
            logger.warning("Configured winner role %s not found in guild '%s'.", role_id, guild.name)
        elif not me.guild_permissions.manage_roles:
            logger.warning("Bot lacks 'Manage Roles' permission in guild '%s'; cannot grant the winner role.", guild.name)
        elif not role.is_assignable():
            logger.warning(
                "Winner role '%s' in guild '%s' is not assignable by the bot (check role hierarchy).",
                role.name, guild.name,
            )
