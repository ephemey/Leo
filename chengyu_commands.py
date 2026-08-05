import logging
import re

import discord
from discord import app_commands

from bot_policy import SERVER_ONLY_MESSAGE
from startup_checks import REQUIRED_CHANNEL_PERMISSIONS

logger = logging.getLogger(__name__)


async def _is_owner(interaction: discord.Interaction) -> bool:
    return await interaction.client.is_owner(interaction.user)

async def apply_monthly_reset(guild: discord.Guild, chengyu_game) -> None:
    """Check whether the monthly Chengyu reset is due for this guild and, if so,
    grant the winner role to the top scorers (if configured), announce the
    reset, and post a new idiom to restart the chain.

    The monthly DB is only cleared as the very last step, after all Discord
    operations have completed without error.
    """
    winners = chengyu_game.maybe_reset_monthly_state(guild.id)
    if winners is None:
        return

    logger.info("Monthly chengyu reset triggered for guild='%s': %d winner(s)", guild.name, len(winners))

    role_id = chengyu_game.get_role(guild.id)
    role = guild.get_role(role_id) if role_id is not None else None

    new_winner_ids = []
    if role is not None:
        previous_winner_ids = chengyu_game.get_current_winners(guild.id)
        logger.info("Removing chengyu winner role from %d previous winner(s) in guild='%s'", len(previous_winner_ids), guild.name)
        for user_id in previous_winner_ids:
            member = await _fetch_member(guild, user_id)
            if member is not None and role in member.roles:
                await member.remove_roles(role)
                logger.info("Removed chengyu winner role from %s in guild='%s'", member, guild.name)

        logger.info("Granting chengyu winner role to %d new winner(s) in guild='%s'", len(winners), guild.name)
        for entry in winners:
            member = await _fetch_member(guild, entry["user_id"])
            if member is not None:
                await member.add_roles(role)
                new_winner_ids.append(entry["user_id"])
                logger.info("Granted chengyu winner role to %s in guild='%s'", member, guild.name)
            else:
                logger.warning("Could not find member %s to grant chengyu winner role in guild='%s'", entry["user_id"], guild.name)

        logger.info("Applied monthly chengyu winner role in guild='%s' to %d winner(s)", guild.name, len(new_winner_ids))
    else:
        new_winner_ids = [entry["user_id"] for entry in winners]
        if role_id is None:
            logger.info("No winner role configured for guild='%s'; skipping role grants", guild.name)
        else:
            logger.warning("Winner role %s not found in guild='%s'; skipping role grants", role_id, guild.name)

    chengyu_game.set_current_winners(guild.id, new_winner_ids)
    logger.info("Registered %d chengyu winner(s) in DB for guild='%s'", len(new_winner_ids), guild.name)

    configured_channel_id = chengyu_game.get_channel(guild.id)
    if configured_channel_id is None:
        logger.info("No chengyu channel configured for guild='%s'; skipping announcement", guild.name)
    else:
        channel = guild.get_channel(configured_channel_id)
        if channel is None or not hasattr(channel, "send"):
            logger.warning("Chengyu channel %s not found or not sendable in guild='%s'", configured_channel_id, guild.name)
        else:
            await channel.send(chengyu_game.format_reset_message(winners))
            logger.info("Sent chengyu reset announcement in guild='%s' channel=%s", guild.name, configured_channel_id)
            continuation = chengyu_game.get_random_unused_idiom(guild.id, channel.id)
            if continuation is not None:
                continuation_text = continuation.get("simplified") or continuation.get("traditional") or "an idiom"
                chengyu_game.mark_used_entry(guild.id, channel.id, continuation_text)
                chengyu_game.set_channel_state(guild.id, channel.id, continuation)
                await channel.send(f"🔁 Starting a new chain with: {continuation_text}")
                logger.info("Posted chengyu chain continuation '%s' in guild='%s'", continuation_text, guild.name)

    chengyu_game.commit_monthly_reset(guild.id)
    logger.info("Monthly chengyu reset complete for guild='%s'", guild.name)


async def _fetch_member(guild: discord.Guild, user_id: int) -> discord.Member | None:
    """Look up a guild member without relying on the Members intent's cache.

    Falls back to a direct API call since the member cache is empty (or
    incomplete) without the privileged Members intent.
    """
    member = guild.get_member(user_id)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(user_id)
    except discord.NotFound:
        return None


async def _safe_send(coro, description: str, channel: discord.TextChannel) -> None:
    """Await a Discord send/reply/reaction coroutine, swallowing permission errors.

    Missing permissions are a per-guild configuration problem, not a bug — without
    this, a channel missing e.g. Send Messages or Add Reactions would throw the same
    unhandled Forbidden error on every single message in that channel.
    """
    try:
        await coro
    except discord.Forbidden:
        me = channel.guild.me
        missing = (
            [perm for perm in REQUIRED_CHANNEL_PERMISSIONS if not getattr(channel.permissions_for(me), perm)]
            if me is not None else []
        )
        if missing:
            logger.warning("Missing permissions to %s: missing %s.", description, ", ".join(missing))
        else:
            logger.warning("Missing permissions to %s.", description)
    except discord.HTTPException as e:
        logger.warning("Failed to %s: %s", description, e)


def setup(bot, chengyu_game, dictionary) -> None:
    @bot.event
    async def on_message(message: discord.Message):
        if message.author.bot:
            return

        if message.guild is None:
            try:
                await message.channel.send(SERVER_ONLY_MESSAGE)
            except discord.HTTPException as e:
                logger.warning("Failed to send server-only DM notice: %s", e)
            return

        if not isinstance(message.channel, discord.TextChannel):
            return

        configured_channel_id = chengyu_game.get_channel(message.guild.id)
        if configured_channel_id is None or message.channel.id != configured_channel_id:
            return

        if not message.content.strip():
            return

        cleaned_text = re.sub(r"[^一-鿿]", "", message.content)
        if len(cleaned_text) != 4:
            return

        entry = dictionary.search(cleaned_text)
        if not entry:
            return

        if isinstance(entry, list):
            entry = entry[0]

        if not chengyu_game.is_valid_chengyu(entry):
            return

        logger.info(
            "Chengyu submission '%s' by %s in guild='%s' channel=%s",
            cleaned_text, message.author, message.guild.name, message.channel.id,
        )

        entry_text = entry.get("simplified") or entry.get("traditional") or cleaned_text
        if chengyu_game.is_used_entry(message.guild.id, message.channel.id, entry_text):
            await _safe_send(
                message.reply("❌ That chengyu has already been used in this chain."),
                f"reply in #{message.channel.name} (guild='{message.guild.name}')",
                message.channel,
            )
            return

        state = chengyu_game.get_channel_state(message.guild.id, message.channel.id)
        previous_entry = state.get("entry")

        if previous_entry is not None and not chengyu_game.entries_match_chain(previous_entry, entry):
            await _safe_send(
                message.reply("❌ That entry does not continue the chain."),
                f"reply in #{message.channel.name} (guild='{message.guild.name}')",
                message.channel,
            )
            return

        chengyu_game.record_score(message.guild.id, message.author.id, message.author.display_name or message.author.name)
        chengyu_game.mark_used_entry(message.guild.id, message.channel.id, entry_text)
        chengyu_game.set_channel_state(message.guild.id, message.channel.id, entry)
        await _safe_send(
            message.add_reaction("✅"),
            f"add reaction in #{message.channel.name} (guild='{message.guild.name}')",
            message.channel,
        )
        logger.info(
            "Accepted chengyu entry '%s' from %s in guild='%s' channel=%s",
            entry_text, message.author, message.guild.name, message.channel.id,
        )

        if chengyu_game.is_dead_end(message.guild.id, message.channel.id, entry):
            continuation_entry = chengyu_game.get_random_unused_idiom(message.guild.id, message.channel.id)
            if continuation_entry is None:
                await _safe_send(
                    message.channel.send(
                        f"💥 {message.author.display_name or message.author.name} has killed the game by reaching a dead end, and there are no unused idioms left. The game is over :("
                    ),
                    f"send in #{message.channel.name} (guild='{message.guild.name}')",
                    message.channel,
                )
                logger.info("Chengyu game over in guild='%s' channel=%s: no unused idioms left", message.guild.name, message.channel.id)
                return

            continuation_entry_text = continuation_entry.get("simplified") or continuation_entry.get("traditional") or "an idiom"
            chengyu_game.mark_used_entry(message.guild.id, message.channel.id, continuation_entry_text)
            chengyu_game.set_channel_state(message.guild.id, message.channel.id, continuation_entry)
            await _safe_send(
                message.channel.send(chengyu_game.format_dead_end_message(message.author.display_name or message.author.name, continuation_entry)),
                f"send in #{message.channel.name} (guild='{message.guild.name}')",
                message.channel,
            )
            logger.info("Chengyu dead end reached in guild='%s' channel=%s, continued with '%s'", message.guild.name, message.channel.id, continuation_entry_text)

    @bot.tree.command(name="cysetup", description="Set the text channel and optional winner role for Chengyu Jielong")
    @app_commands.describe(
        channel="The text channel to use for Chengyu submissions",
        role="Optional role to grant to the top three monthly winners"
    )
    @app_commands.guild_only()
    @app_commands.check(_is_owner)
    async def cysetup(interaction: discord.Interaction, channel: discord.TextChannel, role: discord.Role | None = None):
        logger.info("/cysetup triggered by %s in guild='%s': channel=%s role=%s", interaction.user, interaction.guild.name if interaction.guild else interaction.guild_id, channel.id, role.id if role else None)
        chengyu_game.set_channel(interaction.guild_id, channel.id, role.id if role else None)
        if role:
            await interaction.response.send_message(f"✅ Chengyu Jielong is set to {channel.mention} with the {role.mention} winner role.")
        else:
            await interaction.response.send_message(f"✅ Chengyu Jielong is set to {channel.mention}. No winner role configured.")
        # Post a random starting idiom in the configured channel to kick off play
        try:
            starter = chengyu_game.get_random_unused_idiom(interaction.guild_id, channel.id)
            if starter:
                starter_text = starter.get("simplified") or starter.get("traditional") or "an idiom"
                chengyu_game.mark_used_entry(interaction.guild_id, channel.id, starter_text)
                chengyu_game.set_channel_state(interaction.guild_id, channel.id, starter)
                await channel.send(f"🔁 Starting a new chain with: {starter_text}")
        except Exception:
            pass

    @bot.tree.command(name="cylb", description="Show the Chengyu Jielong leaderboard for this server")
    @app_commands.guild_only()
    async def cylb(interaction: discord.Interaction):
        logger.info("/cylb triggered by %s in guild='%s'", interaction.user, interaction.guild.name if interaction.guild else interaction.guild_id)
        leaderboard = chengyu_game.get_leaderboard(interaction.guild_id or 0)
        if not leaderboard:
            await interaction.response.send_message("📊 No Chengyu entries have been recorded yet.")
            return

        lines = []
        for index, entry in enumerate(leaderboard[:10], 1):
            lines.append(f"{index}. {entry['username']} — {entry['valid_entries']} valid entries")

        embed = discord.Embed(
            title="📊 Chengyu Jielong Leaderboard",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="cylb-alltime", description="Show the all-time Chengyu Jielong leaderboard for this server")
    @app_commands.guild_only()
    async def cylb_alltime(interaction: discord.Interaction):
        logger.info("/cylb-alltime triggered by %s in guild='%s'", interaction.user, interaction.guild.name if interaction.guild else interaction.guild_id)
        leaderboard = chengyu_game.get_alltime_leaderboard(interaction.guild_id or 0)
        if not leaderboard:
            await interaction.response.send_message("📊 No all-time Chengyu entries have been recorded yet.")
            return

        lines = []
        for index, entry in enumerate(leaderboard[:10], 1):
            lines.append(f"{index}. {entry['username']} — {entry['valid_entries']} valid entries")

        embed = discord.Embed(
            title="📊 Chengyu Jielong All-Time Leaderboard",
            description="\n".join(lines),
            color=discord.Color.purple(),
        )
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="timer", description="Show how long until all monthly leaderboards reset")
    @app_commands.guild_only()
    async def timer(interaction: discord.Interaction):
        logger.info("/timer triggered by %s in guild='%s'", interaction.user, interaction.guild.name if interaction.guild else interaction.guild_id)
        delta = chengyu_game.get_time_until_reset()
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        await interaction.response.send_message(
            f"⏰ All monthly leaderboards reset in {hours}h {minutes}m {seconds}s."
        )

    @bot.tree.command(name="cyscore", description="Show the current Chengyu score for a user")
    @app_commands.describe(user="Optional user to look up; defaults to you")
    @app_commands.guild_only()
    async def cyscore(interaction: discord.Interaction, user: discord.Member | None = None):
        logger.info("/cyscore triggered by %s in guild='%s' for user=%s", interaction.user, interaction.guild.name if interaction.guild else interaction.guild_id, user.id if user else interaction.user.id)
        target_user = user or interaction.user
        score = chengyu_game.get_score(interaction.guild_id or 0, target_user.id)

        if score is None:
            await interaction.response.send_message(f"📊 {target_user.display_name} has no Chengyu points yet.")
            return

        await interaction.response.send_message(
            f"📊 {target_user.display_name} has {score['valid_entries']} Chengyu point(s) this month."
        )

    @bot.tree.command(name="cycurrent", description="Show the most recent valid Chengyu entry in this channel")
    @app_commands.guild_only()
    async def cycurrent(interaction: discord.Interaction):
        logger.info("/cycurrent triggered by %s in guild='%s' channel=%s", interaction.user, interaction.guild.name if interaction.guild else interaction.guild_id, interaction.channel_id if interaction.channel else None)
        if not interaction.guild_id or not interaction.channel:
            await interaction.response.send_message("This command must be used in a guild text channel.")
            return

        state = chengyu_game.get_channel_state(interaction.guild_id, interaction.channel.id)
        entry = state.get("entry")

        if not entry:
            await interaction.response.send_message("ℹ️ No previous valid Chengyu entry found in this channel.")
            return

        entry_text = entry.get("simplified") or entry.get("traditional") or "(unknown)"
        pinyin = entry.get("pinyin") or entry.get("pinyin_raw") or ""
        defs = entry.get("definitions") or []
        defs_text = "; ".join(defs[:3]) if defs else "(no definition available)"

        await interaction.response.send_message(
            f"📌 Previous Chengyu: {entry_text}\n🗣️ {pinyin}\n📚 {defs_text}"
        )
