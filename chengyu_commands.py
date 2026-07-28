import logging
import re

import discord
from discord import app_commands

logger = logging.getLogger(__name__)


async def apply_monthly_winner_roles(guild: discord.Guild, chengyu_game) -> None:
    """Strip the winner role from prior holders, grant it to this month's winners,
    announce the reset, and post a new idiom to restart the chain."""
    role_id = chengyu_game.get_role(guild.id)
    if role_id is None:
        return

    role = guild.get_role(role_id)
    if role is None:
        return

    for member in guild.members:
        if role in member.roles:
            await member.remove_roles(role)

    winners = chengyu_game.maybe_reset_monthly_state(guild.id)
    if not winners:
        return

    for entry in winners:
        member = guild.get_member(entry["user_id"])
        if member is not None:
            await member.add_roles(role)

    logger.info("Applied monthly chengyu winner role in guild='%s' to %d winner(s)", guild.name, len(winners))

    configured_channel_id = chengyu_game.get_channel(guild.id)
    if configured_channel_id is None:
        return

    channel = guild.get_channel(configured_channel_id)
    if channel is not None and hasattr(channel, "send"):
        await channel.send(chengyu_game.format_reset_message(winners))
        continuation = chengyu_game.get_random_unused_idiom(guild.id, channel.id)
        if continuation is not None:
            continuation_text = continuation.get("simplified") or continuation.get("traditional") or "an idiom"
            chengyu_game.mark_used_entry(guild.id, channel.id, continuation_text)
            chengyu_game.set_channel_state(guild.id, channel.id, continuation)
            await channel.send(f"🔁 Starting a new chain with: {continuation_text}")


async def _is_owner(interaction: discord.Interaction) -> bool:
    return await interaction.client.is_owner(interaction.user)


def setup(bot, chengyu_game, dictionary) -> None:
    @bot.event
    async def on_message(message: discord.Message):
        if message.author.bot or not message.guild or not isinstance(message.channel, discord.TextChannel):
            return

        configured_channel_id = chengyu_game.get_channel(message.guild.id)
        if configured_channel_id is not None and message.channel.id != configured_channel_id:
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
            await message.reply("❌ That chengyu has already been used in this chain.")
            return

        state = chengyu_game.get_channel_state(message.guild.id, message.channel.id)
        previous_entry = state.get("entry")

        if previous_entry is not None and not chengyu_game.entries_match_chain(previous_entry, entry):
            await message.reply("❌ That entry does not continue the chain.")
            return

        chengyu_game.record_score(message.guild.id, message.author.id, message.author.display_name or message.author.name)
        chengyu_game.mark_used_entry(message.guild.id, message.channel.id, entry_text)
        chengyu_game.set_channel_state(message.guild.id, message.channel.id, entry)
        await message.add_reaction("✅")
        logger.info(
            "Accepted chengyu entry '%s' from %s in guild='%s' channel=%s",
            entry_text, message.author, message.guild.name, message.channel.id,
        )

        if chengyu_game.is_dead_end(message.guild.id, message.channel.id, entry):
            continuation_entry = chengyu_game.get_random_unused_idiom(message.guild.id, message.channel.id)
            if continuation_entry is None:
                await message.channel.send(
                    f"💥 {message.author.display_name or message.author.name} has killed the game by reaching a dead end, and there are no unused idioms left. The game is over :("
                )
                logger.info("Chengyu game over in guild='%s' channel=%s: no unused idioms left", message.guild.name, message.channel.id)
                return

            continuation_entry_text = continuation_entry.get("simplified") or continuation_entry.get("traditional") or "an idiom"
            chengyu_game.mark_used_entry(message.guild.id, message.channel.id, continuation_entry_text)
            chengyu_game.set_channel_state(message.guild.id, message.channel.id, continuation_entry)
            await message.channel.send(chengyu_game.format_dead_end_message(message.author.display_name or message.author.name, continuation_entry))
            logger.info("Chengyu dead end reached in guild='%s' channel=%s, continued with '%s'", message.guild.name, message.channel.id, continuation_entry_text)

    @bot.tree.command(name="cysetup", description="Set the text channel and optional winner role for Chengyu Jielong")
    @app_commands.describe(
        channel="The text channel to use for Chengyu submissions",
        role="Optional role to grant to the top three monthly winners"
    )
    async def cysetup(interaction: discord.Interaction, channel: discord.TextChannel, role: discord.Role | None = None):
        logger.info("/cysetup triggered by %s in guild='%s': channel=%s role=%s", interaction.user, interaction.guild.name if interaction.guild else interaction.guild_id, channel.id, role.id if role else None)
        chengyu_game.set_channel(interaction.guild_id, channel.id, role.id if role else None)
        if role:
            await interaction.response.send_message(f"✅ Chengyu Jielong is set to {channel.mention} with the {role.mention} winner role.")
        else:
            await interaction.response.send_message(f"✅ Chengyu Jielong is set to {channel.mention}. No winner role configured.")
        # Clear monthly scores and used entries when reconfiguring
        try:
            chengyu_game.reset_monthly_state(interaction.guild_id)
        except Exception:
            # ignore DB hiccups for now
            pass

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

    @bot.tree.command(name="cytimer", description="Show how long until the Chengyu monthly reset")
    async def cytimer(interaction: discord.Interaction):
        logger.info("/cytimer triggered by %s in guild='%s'", interaction.user, interaction.guild.name if interaction.guild else interaction.guild_id)
        delta = chengyu_game.get_time_until_reset()
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        await interaction.response.send_message(
            f"⏰ The Chengyu leaderboard resets in {hours}h {minutes}m {seconds}s."
        )

    @bot.tree.command(name="cyscore", description="Show the current Chengyu score for a user")
    @app_commands.describe(user="Optional user to look up; defaults to you")
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

    @bot.tree.command(name="cyedit", description="Edit a user's current Chengyu score (bot owner only)")
    @app_commands.describe(
        user="The user whose score to edit (@mention or user ID)",
        action="Whether to add, deduct, or set the score",
        amount="The number of points",
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Add", value="add"),
        app_commands.Choice(name="Deduct", value="deduct"),
        app_commands.Choice(name="Set", value="set"),
    ])
    @app_commands.check(_is_owner)
    async def cyedit(interaction: discord.Interaction, user: str, action: str, amount: int):
        logger.info("/cyedit called by %s (guild=%s): action=%s amount=%d target_input='%s'", interaction.user, interaction.guild_id, action, amount, user)

        match = re.fullmatch(r"<@!?(\d+)>", user.strip())
        user_id_str = match.group(1) if match else user.strip()

        if not user_id_str.isdigit():
            logger.info("/cyedit failed: could not parse a user from input '%s' (requested by %s)", user, interaction.user)
            await interaction.response.send_message("❌ Could not parse that as a user mention or ID.", ephemeral=True)
            return

        user_id = int(user_id_str)

        if amount < 0:
            logger.info("/cyedit failed: negative amount %d given by %s", amount, interaction.user)
            await interaction.response.send_message("Amount must be a positive number.", ephemeral=True)
            return

        member = interaction.guild.get_member(user_id) if interaction.guild else None
        if member is not None:
            username = member.display_name
            mention = member.mention
        else:
            try:
                fetched_user = await interaction.client.fetch_user(user_id)
            except discord.NotFound:
                logger.info("/cyedit failed: no user found with id=%d (requested by %s)", user_id, interaction.user)
                await interaction.response.send_message(f"❌ Could not find a user with ID {user_id}.", ephemeral=True)
                return
            except discord.HTTPException as e:
                logger.error("/cyedit: failed to fetch user id=%d: %s", user_id, e)
                await interaction.response.send_message("❌ Something went wrong looking up that user.", ephemeral=True)
                return
            username = fetched_user.display_name
            mention = fetched_user.mention
            logger.info("/cyedit: target user id=%d is not a member of this guild, resolved via fetch_user", user_id)

        new_score = chengyu_game.edit_score(interaction.guild_id or 0, user_id, username, action, amount)
        logger.info("/cyedit: %s (id=%d) score is now %d after action=%s amount=%d (guild=%s, requested by %s)", username, user_id, new_score, action, amount, interaction.guild_id, interaction.user)

        action_past = {"add": "Added", "deduct": "Deducted", "set": "Set"}[action]
        await interaction.response.send_message(
            f"✅ {action_past} {amount} point(s) for {mention}. Their score is now {new_score}.",
            ephemeral=True,
        )
