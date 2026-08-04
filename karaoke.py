import logging
import time
from typing import Optional

import discord
from discord import app_commands

logger = logging.getLogger(__name__)

karaoke_queues = {}
karaoke_notice = {}
karaoke_notice_cooldowns = {}  # (guild_id, user_id) -> monotonic timestamp of last notice

_NOTICE_COOLDOWN = 60.0  # seconds


def _queue_key(interaction: discord.Interaction) -> tuple[int, int]:
    return (interaction.guild_id or 0, interaction.channel_id)


def _song_label(entry: dict) -> str:
    song = entry.get("song")
    artist = entry.get("artist")
    if song and artist:
        return f' — "{song}" by {artist}'
    if song:
        return f' — "{song}"'
    if artist:
        return f' — by {artist}'
    return ""


def _move_entry_to_top(queue: list[dict], position: int | None = None, user_id: int | None = None, name: str | None = None) -> dict:
    if position is None:
        if user_id is None:
            raise ValueError("user_id is required when no position is provided")
        existing = next((e for e in queue if e["id"] == user_id), None)
        queue[:] = [entry for entry in queue if entry["id"] != user_id]
        entry = existing if existing is not None else {"id": user_id, "name": name or str(user_id)}
        queue.insert(0, entry)
        return entry

    if position < 1 or position > len(queue):
        raise IndexError("That queue position is invalid.")

    entry = queue.pop(position - 1)
    queue.insert(0, entry)
    return entry


def _get_queue(interaction: discord.Interaction) -> list[dict]:
    key = _queue_key(interaction)
    if key not in karaoke_queues:
        karaoke_queues[key] = []
    return karaoke_queues[key]


def _queue_display(interaction: discord.Interaction) -> discord.Embed:
    queue = _get_queue(interaction)
    embed = discord.Embed(
        title="🎤 Karaoke Queue",
        color=discord.Color.purple(),
    )

    if not queue:
        embed.description = "The queue is empty right now."
        return embed

    lines = [f"{i}. <@{entry['id']}>{_song_label(entry)}" for i, entry in enumerate(queue, 1)]
    embed.description = "\n".join(lines)
    embed.set_footer(text=f"{len(queue)} entr{'y' if len(queue) == 1 else 'ies'} in the queue")
    return embed


def _leaderboard_embed(title: str, entries: list[dict]) -> discord.Embed:
    embed = discord.Embed(title=title, color=discord.Color.gold())
    if not entries:
        embed.description = "No scores yet."
        return embed
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, entry in enumerate(entries[:10]):
        prefix = medals[i] if i < 3 else f"{i + 1}."
        lines.append(f"{prefix} <@{entry['user_id']}> — {entry['points']} pts")
    embed.description = "\n".join(lines)
    return embed


async def _fetch_member(guild: discord.Guild, user_id: int) -> discord.Member | None:
    member = guild.get_member(user_id)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(user_id)
    except discord.NotFound:
        return None


async def _is_owner(interaction: discord.Interaction) -> bool:
    return await interaction.client.is_owner(interaction.user)


async def apply_monthly_reset(guild: discord.Guild, karaoke_points) -> None:
    """Reset monthly karaoke scores and rotate the configured winner role."""
    winners = karaoke_points.maybe_reset_monthly(guild.id)
    if winners is None:
        return

    role_id = karaoke_points.get_role(guild.id)
    role = guild.get_role(role_id) if role_id is not None else None

    new_winner_ids = []
    if role is not None:
        previous_winner_ids = karaoke_points.get_current_winners(guild.id)
        for user_id in previous_winner_ids:
            member = await _fetch_member(guild, user_id)
            if member is not None and role in member.roles:
                await member.remove_roles(role)

        for entry in winners:
            member = await _fetch_member(guild, entry["user_id"])
            if member is not None:
                await member.add_roles(role)
                new_winner_ids.append(entry["user_id"])

        logger.info(
            "Applied monthly karaoke winner role in guild='%s' to %d winner(s)",
            guild.name,
            len(new_winner_ids),
        )
    else:
        new_winner_ids = [entry["user_id"] for entry in winners]
        if role_id is None:
            logger.info("No karaoke winner role configured for guild='%s'; skipping role grants", guild.name)
        else:
            logger.warning(
                "Karaoke winner role %s not found in guild='%s'; skipping role grants",
                role_id,
                guild.name,
            )

    karaoke_points.set_current_winners(guild.id, new_winner_ids)
    logger.info("Registered %d karaoke winner(s) in DB for guild='%s'", len(new_winner_ids), guild.name)


def setup(bot, karaoke_points=None):
    @bot.tree.command(name="ksetup", description="Set the monthly karaoke winner role (bot owner only)")
    @app_commands.describe(role="Role to grant to the top three monthly karaoke scorers")
    @app_commands.guild_only()
    @app_commands.check(_is_owner)
    async def karaoke_setup(interaction: discord.Interaction, role: discord.Role):
        logger.info(
            "/ksetup called by %s (guild=%s): role=%s",
            interaction.user,
            interaction.guild_id,
            role.id,
        )
        if karaoke_points is None:
            await interaction.response.send_message("Karaoke points are not enabled.", ephemeral=True)
            return
        karaoke_points.set_role(interaction.guild_id, role.id)
        await interaction.response.send_message(
            f"✅ The {role.mention} role will be awarded to the top three monthly karaoke scorers.",
            ephemeral=True,
        )

    @bot.tree.command(name="kadd", description="Join the karaoke queue")
    @app_commands.describe(song="Song title (optional)", artist="Artist name (optional)")
    async def karaoke_join(interaction: discord.Interaction, song: str | None = None, artist: str | None = None):
        logger.info("/kadd called by %s (guild=%s)", interaction.user, interaction.guild_id)

        if interaction.user.voice is None or interaction.user.voice.channel is None:
            logger.info("/kadd: %s is not in a voice channel", interaction.user)
            await interaction.response.send_message("❌ You must be in a voice channel to join the karaoke queue.", ephemeral=True)
            return

        queue = _get_queue(interaction)
        entry = {
            "id": interaction.user.id,
            "name": interaction.user.display_name or interaction.user.name,
            "song": song,
            "artist": artist,
        }
        queue.append(entry)
        label = _song_label(entry)
        logger.info("/kadd: added %s to queue%s (queue size=%d)", interaction.user, label, len(queue))
        await interaction.response.send_message(f"🎤 {interaction.user.mention} joined the karaoke queue{label}.")

    @bot.tree.command(name="kremove", description="Remove a user from the karaoke queue by their queue position")
    @app_commands.describe(position="The 1-based queue position to remove")
    async def karaoke_remove(interaction: discord.Interaction, position: int | None = None):
        logger.info("/kremove called by %s (guild=%s, position=%s)", interaction.user, interaction.guild_id, position)
        queue = _get_queue(interaction)

        if position is not None:
            if position < 1 or position > len(queue):
                logger.info("/kremove: invalid position %s (queue size=%d)", position, len(queue))
                await interaction.response.send_message("That queue position is invalid.", ephemeral=True)
                return

            removed_entry = queue.pop(position - 1)
            logger.info("/kremove: removed %s at position %s", removed_entry["id"], position)
            await interaction.response.send_message(
                f"🗑️ Removed <@{removed_entry['id']}> from the karaoke queue."
            )
            return

        if not any(entry["id"] == interaction.user.id for entry in queue):
            logger.info("/kremove: %s not in queue", interaction.user)
            await interaction.response.send_message("You are not currently in the karaoke queue.", ephemeral=True)
            return

        queue[:] = [entry for entry in queue if entry["id"] != interaction.user.id]
        logger.info("/kremove: removed %s from queue (queue size=%d)", interaction.user, len(queue))
        await interaction.response.send_message(f"🗑️ Removed {interaction.user.mention} from the karaoke queue.")

    @bot.tree.command(name="kbump", description="Move yourself or a queued entry to the top of the karaoke queue")
    @app_commands.describe(position="The 1-based queue position to bump to the top")
    async def karaoke_bump(interaction: discord.Interaction, position: int | None = None):
        logger.info("/kbump called by %s (guild=%s, position=%s)", interaction.user, interaction.guild_id, position)
        queue = _get_queue(interaction)

        try:
            if position is None:
                moved_entry = _move_entry_to_top(
                    queue,
                    position=None,
                    user_id=interaction.user.id,
                    name=interaction.user.display_name or interaction.user.name,
                )
                logger.info("/kbump: bumped %s to top", interaction.user)
                await interaction.response.send_message(
                    f"⬆️ {interaction.user.mention} was bumped to the top of the karaoke queue."
                )
                return

            moved_entry = _move_entry_to_top(queue, position=position)
        except IndexError:
            logger.info("/kbump: invalid position %s (queue size=%d)", position, len(queue))
            await interaction.response.send_message("That queue position is invalid.", ephemeral=True)
            return

        logger.info("/kbump: moved %s from position %s to top", moved_entry["id"], position)
        await interaction.response.send_message(
            f"⬆️ Moved <@{moved_entry['id']}> to the top of the karaoke queue."
        )

    @bot.tree.command(name="knext", description="Move to the next person in the karaoke queue")
    async def karaoke_next(interaction: discord.Interaction):
        logger.info("/knext called by %s (guild=%s)", interaction.user, interaction.guild_id)
        queue = _get_queue(interaction)

        if not queue:
            logger.info("/knext: queue is empty")
            await interaction.response.send_message("🎤 The karaoke queue is already empty.")
            return

        current = queue.pop(0)

        # Award points silently
        if karaoke_points is not None and interaction.guild is not None:
            singer = interaction.guild.get_member(current["id"])
            if singer is None:
                try:
                    singer = await interaction.guild.fetch_member(current["id"])
                except discord.NotFound:
                    singer = None
            if singer is None:
                logger.info("/knext: singer %s not found in guild=%s, skipping points", current["id"], interaction.guild_id)
            elif singer.voice is None or singer.voice.channel is None:
                logger.info("/knext: singer %s is not in a voice channel (guild=%s), skipping points", current["id"], interaction.guild_id)
            else:
                vc = singer.voice.channel
                audience_count = len(vc.members) - 1
                pts = karaoke_points.calculate_points(audience_count)
                if pts > 0:
                    karaoke_points.record_points(interaction.guild_id, current["id"], current["name"], pts)
                    logger.info("/knext: awarded %d point(s) to %s (audience=%d, guild=%s)", pts, current["id"], audience_count, interaction.guild_id)
                else:
                    logger.info("/knext: no points for %s — singing alone in VC (guild=%s)", current["id"], interaction.guild_id)
        elif karaoke_points is not None:
            logger.info("/knext: guild not available for interaction, skipping points for %s", current["id"])

        if queue:
            next_up = queue[0]
            logger.info("/knext: advanced past %s, next is %s (queue size=%d)", current["id"], next_up["id"], len(queue))
            await interaction.response.send_message(
                f"➡️ Thanks {current['name']}! Next up: <@{next_up['id']}>{_song_label(next_up)}."
            )
        else:
            logger.info("/knext: advanced past %s, queue now empty", current["id"])
            await interaction.response.send_message(
                f"➡️ {current['name']} is done. The queue is now empty."
            )

    @bot.tree.command(name="kqueue", description="Show the current karaoke queue")
    async def karaoke_queue_view(interaction: discord.Interaction):
        logger.info("/kqueue called by %s (guild=%s, queue size=%d)", interaction.user, interaction.guild_id, len(_get_queue(interaction)))
        await interaction.response.send_message(embed=_queue_display(interaction))

    @bot.tree.command(name="klb", description="Show the monthly karaoke leaderboard")
    async def karaoke_leaderboard(interaction: discord.Interaction):
        logger.info("/klb called by %s (guild=%s)", interaction.user, interaction.guild_id)
        if karaoke_points is None:
            await interaction.response.send_message("Karaoke points are not enabled.", ephemeral=True)
            return
        entries = karaoke_points.get_leaderboard(interaction.guild_id)
        await interaction.response.send_message(embed=_leaderboard_embed("🎤 Karaoke — Monthly Leaderboard", entries))

    @bot.tree.command(name="klb-alltime", description="Show the all-time karaoke leaderboard")
    async def karaoke_leaderboard_alltime(interaction: discord.Interaction):
        logger.info("/klb-alltime called by %s (guild=%s)", interaction.user, interaction.guild_id)
        if karaoke_points is None:
            await interaction.response.send_message("Karaoke points are not enabled.", ephemeral=True)
            return
        entries = karaoke_points.get_alltime_leaderboard(interaction.guild_id)
        await interaction.response.send_message(embed=_leaderboard_embed("🎤 Karaoke — All-Time Leaderboard", entries))

    @bot.tree.command(name="kscore", description="Check a user's karaoke points")
    @app_commands.describe(user="The user to look up (defaults to yourself)")
    async def karaoke_score(interaction: discord.Interaction, user: discord.Member | None = None):
        target = user or interaction.user
        logger.info("/kscore called by %s for %s (guild=%s)", interaction.user, target, interaction.guild_id)
        if karaoke_points is None:
            await interaction.response.send_message("Karaoke points are not enabled.", ephemeral=True)
            return
        monthly = karaoke_points.get_monthly_score(interaction.guild_id, target.id)
        alltime = karaoke_points.get_alltime_score(interaction.guild_id, target.id)
        logger.info("/kscore: %s has %d monthly pts, %d alltime pts (guild=%s)", target, monthly, alltime, interaction.guild_id)
        await interaction.response.send_message(
            f"🎤 {target.mention} — {monthly} pts this month, {alltime} pts all-time.",
            ephemeral=True,
        )

    @bot.tree.command(name="knotice", description="Toggle the karaoke welcome notice for users joining a voice channel")
    @app_commands.describe(state="on or off (omit to toggle)")
    @app_commands.choices(state=[
        app_commands.Choice(name="on", value="on"),
        app_commands.Choice(name="off", value="off"),
    ])
    async def karaoke_notice_cmd(interaction: discord.Interaction, state: Optional[str] = None):
        logger.info("/knotice called by %s (guild=%s, state=%s)", interaction.user, interaction.guild_id, state)
        guild_id = interaction.guild_id
        current = karaoke_notice.get(guild_id, False)
        if state is None:
            new_state = not current
        else:
            new_state = state == "on"
        karaoke_notice[guild_id] = new_state
        status = "enabled" if new_state else "disabled"
        logger.info("/knotice: notice %s for guild=%s", status, guild_id)
        await interaction.response.send_message(f"🔔 Karaoke welcome notice {status}.", ephemeral=True)

    @bot.listen("on_voice_state_update")
    async def karaoke_vc_notice(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        if after.channel is None or before.channel == after.channel:
            return
        guild_id = member.guild.id
        if not karaoke_notice.get(guild_id, False):
            return
        active_queues = [(key, q) for key, q in karaoke_queues.items() if key[0] == guild_id and q]
        if not active_queues:
            return
        cooldown_key = (guild_id, member.id)
        now = time.monotonic()
        if now - karaoke_notice_cooldowns.get(cooldown_key, 0.0) < _NOTICE_COOLDOWN:
            return
        karaoke_notice_cooldowns[cooldown_key] = now
        msg = f"{member.mention} Welcome to the karaoke channel! Please keep your mic muted when someone else is singing 👍"
        for (_, channel_id), _ in active_queues:
            channel = bot.get_channel(channel_id)
            if channel is not None:
                await channel.send(msg)
                logger.info("Karaoke VC notice sent for %s in guild=%s (text_channel=%s)", member, guild_id, channel_id)

    @bot.listen("on_guild_channel_delete")
    async def karaoke_channel_cleanup(channel: discord.abc.GuildChannel):
        key = (channel.guild.id, channel.id)
        if key in karaoke_queues:
            del karaoke_queues[key]
            logger.info("Removed karaoke queue for deleted channel=%s in guild=%s", channel.id, channel.guild.id)
