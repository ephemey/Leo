import discord
from discord import app_commands


karaoke_queues = {}


def _queue_key(interaction: discord.Interaction) -> tuple[int, int]:
    return (interaction.guild_id or 0, interaction.channel_id)


def _move_entry_to_top(queue: list[dict], position: int | None = None, user_id: int | None = None, name: str | None = None) -> dict:
    if position is None:
        if user_id is None:
            raise ValueError("user_id is required when no position is provided")
        queue[:] = [entry for entry in queue if entry["id"] != user_id]
        entry = {"id": user_id, "name": name or str(user_id)}
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

    lines = [f"{i}. <@{entry['id']}>" for i, entry in enumerate(queue, 1)]
    embed.description = "\n".join(lines)
    embed.set_footer(text=f"{len(queue)} entr{'y' if len(queue) == 1 else 'ies'} in the queue")
    return embed


def setup(bot):
    @bot.tree.command(name="kadd", description="Join the karaoke queue")
    async def karaoke_join(interaction: discord.Interaction):
        queue = _get_queue(interaction)

        queue.append({"id": interaction.user.id, "name": interaction.user.display_name or interaction.user.name})
        await interaction.response.send_message(f"🎤 {interaction.user.mention} joined the karaoke queue.")

    @bot.tree.command(name="kremove", description="Remove a user from the karaoke queue by their queue position")
    @app_commands.describe(position="The 1-based queue position to remove")
    async def karaoke_remove(interaction: discord.Interaction, position: int | None = None):
        queue = _get_queue(interaction)

        if position is not None:
            if position < 1 or position > len(queue):
                await interaction.response.send_message("That queue position is invalid.", ephemeral=True)
                return

            removed_entry = queue.pop(position - 1)
            await interaction.response.send_message(
                f"🗑️ Removed <@{removed_entry['id']}> from the karaoke queue."
            )
            return

        if not any(entry["id"] == interaction.user.id for entry in queue):
            await interaction.response.send_message("You are not currently in the karaoke queue.", ephemeral=True)
            return

        queue[:] = [entry for entry in queue if entry["id"] != interaction.user.id]
        await interaction.response.send_message(f"🗑️ Removed {interaction.user.mention} from the karaoke queue.")

    @bot.tree.command(name="kbump", description="Move yourself or a queued entry to the top of the karaoke queue")
    @app_commands.describe(position="The 1-based queue position to bump to the top")
    async def karaoke_bump(interaction: discord.Interaction, position: int | None = None):
        queue = _get_queue(interaction)

        try:
            if position is None:
                moved_entry = _move_entry_to_top(
                    queue,
                    position=None,
                    user_id=interaction.user.id,
                    name=interaction.user.display_name or interaction.user.name,
                )
                await interaction.response.send_message(
                    f"⬆️ {interaction.user.mention} was bumped to the top of the karaoke queue."
                )
                return

            moved_entry = _move_entry_to_top(queue, position=position)
        except IndexError:
            await interaction.response.send_message("That queue position is invalid.", ephemeral=True)
            return

        await interaction.response.send_message(
            f"⬆️ Moved <@{moved_entry['id']}> to the top of the karaoke queue."
        )

    @bot.tree.command(name="knext", description="Move to the next person in the karaoke queue")
    async def karaoke_next(interaction: discord.Interaction):
        queue = _get_queue(interaction)

        if not queue:
            await interaction.response.send_message("🎤 The karaoke queue is already empty.")
            return

        current = queue.pop(0)
        if queue:
            next_up = queue[0]
            await interaction.response.send_message(f"➡️ {current['name']} is done. Next up: <@{next_up['id']}>.")
        else:
            await interaction.response.send_message(f"➡️ {current['name']} is done. The queue is now empty.")

    @bot.tree.command(name="kqueue", description="Show the current karaoke queue")
    async def karaoke_queue_view(interaction: discord.Interaction):
        await interaction.response.send_message(embed=_queue_display(interaction))
