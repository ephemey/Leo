import discord
from discord import app_commands


karaoke_queues = {}


def _queue_key(interaction: discord.Interaction) -> tuple[int, int]:
    return (interaction.guild_id or 0, interaction.channel_id)


def _get_queue(interaction: discord.Interaction) -> list[dict]:
    key = _queue_key(interaction)
    if key not in karaoke_queues:
        karaoke_queues[key] = []
    return karaoke_queues[key]


def _queue_display(interaction: discord.Interaction) -> str:
    queue = _get_queue(interaction)
    if not queue:
        return "🎤 The karaoke queue is empty."

    lines = [f"{i}. <@{entry['id']}>" for i, entry in enumerate(queue, 1)]
    return "🎤 Current karaoke queue:\n" + "\n".join(lines)


def setup(bot):
    @bot.tree.command(name="kadd", description="Join the karaoke queue")
    async def karaoke_join(interaction: discord.Interaction):
        queue = _get_queue(interaction)

        if any(entry["id"] == interaction.user.id for entry in queue):
            await interaction.response.send_message("You are already in the karaoke queue.", ephemeral=True)
            return

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

    @bot.tree.command(name="kbump", description="Move yourself to the top of the karaoke queue")
    async def karaoke_bump(interaction: discord.Interaction):
        queue = _get_queue(interaction)

        queue[:] = [entry for entry in queue if entry["id"] != interaction.user.id]
        queue.insert(0, {"id": interaction.user.id, "name": interaction.user.display_name or interaction.user.name})

        await interaction.response.send_message(f"⬆️ {interaction.user.mention} was bumped to the top of the karaoke queue.")

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
        await interaction.response.send_message(_queue_display(interaction))
