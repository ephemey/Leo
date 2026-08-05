import logging

import discord
from discord import app_commands

logger = logging.getLogger(__name__)


def setup(bot) -> None:
    @bot.tree.command(name="ping", description="Replies with Pong and the bot's latency!")
    @app_commands.guild_only()
    async def ping(interaction: discord.Interaction):
        logger.info("/ping triggered by %s in guild=%s", interaction.user, interaction.guild_id)
        latency = round(bot.latency * 1000)
        await interaction.response.send_message(f"Pong! 🏓 ({latency}ms)")

    @bot.tree.command(name="help", description="List all available commands")
    @app_commands.guild_only()
    async def help_command(interaction: discord.Interaction):
        logger.info("/help triggered by %s in guild='%s'", interaction.user, interaction.guild.name if interaction.guild else interaction.guild_id)
        embed = discord.Embed(title="Commands", color=discord.Color.blurple())

        embed.add_field(name="General", value=(
            "`/ping` — Check the bot's latency\n"
            "`/help` — Show this message\n"
            "`/timer` — Show when all monthly leaderboards reset"
        ), inline=False)

        embed.add_field(name="Dictionary", value=(
            "`/define <query>` — Look up a Chinese word by characters, Pinyin, or English keyword"
        ), inline=False)

        embed.add_field(name="成语接龙 Chengyu Jielong", value=(
            "`/cysetup <channel> [role]` — Set the game channel and optional monthly winner role\n"
            "`/cycurrent` — Show the most recent valid entry in this channel\n"
            "`/cyscore [user]` — Show a user's score for the current month\n"
            "`/cylb` — Monthly leaderboard\n"
            "`/cylb-alltime` — All-time leaderboard"
        ), inline=False)

        embed.add_field(name="Karaoke", value=(
            "`/ksetup <role>` — Set the monthly winner role (bot owner only)\n"
            "`/kadd [song] [artist]` — Join the karaoke queue with an optional song and artist\n"
            "`/kremove [position]` — Remove yourself, or a position from the queue\n"
            "`/kbump [position]` — Move yourself or a position to the top\n"
            "`/knext` — Advance past the current singer\n"
            "`/kqueue` — Show the current queue"
        ), inline=False)

        embed.add_field(name="Bot Owner", value=(
            "`/dbedit` — Edit a stored database record"
        ), inline=False)

        await interaction.response.send_message(embed=embed)
