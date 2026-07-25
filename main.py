import os
import re

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from dictionary import ChineseDictionary
from karaoke import setup as register_karaoke_commands
import chengyu

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Setup intents
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)

dictionary = ChineseDictionary()
register_karaoke_commands(bot)
chengyu_game = chengyu.ChengyuGame(dictionary=dictionary, db_path=os.getenv("CHENGYU_DB_PATH"))


@bot.event
async def on_ready():
    dictionary.load_dictionary()
    print(f"Logged in as {bot.user.name}!")
    print("------")
    try:
        synced = await bot.tree.sync()
        print(f"Successfully synced {len(synced)} slash command(s) globally.")
    except Exception as e:
        print(f"Error syncing commands: {e}")


async def apply_monthly_winner_roles(guild: discord.Guild):
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

    configured_channel_id = chengyu_game.get_channel(guild.id)
    if configured_channel_id is None:
        return

    channel = guild.get_channel(configured_channel_id)
    if channel is not None and hasattr(channel, "send"):
        await channel.send(chengyu_game.format_reset_message(winners))


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild or not isinstance(message.channel, discord.TextChannel):
        return

    configured_channel_id = chengyu_game.get_channel(message.guild.id)
    if configured_channel_id is not None and message.channel.id != configured_channel_id:
        return

    if not message.content.strip():
        return

    cleaned_text = re.sub(r"[^\u4e00-\u9fff]", "", message.content)
    if len(cleaned_text) != 4:
        return

    entry = dictionary.search(cleaned_text)
    if not entry:
        return

    if isinstance(entry, list):
        entry = entry[0]

    if not chengyu_game.is_valid_chengyu(entry):
        return

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


@bot.tree.command(name="cysetup", description="Set the text channel and optional winner role for Chengyu Jielong")
@app_commands.describe(
    channel="The text channel to use for Chengyu submissions",
    role="Optional role to grant to the top three monthly winners"
)
async def cysetup(interaction: discord.Interaction, channel: discord.TextChannel, role: discord.Role | None = None):
    chengyu_game.set_channel(interaction.guild_id, channel.id, role.id if role else None)
    if role:
        await interaction.response.send_message(f"✅ Chengyu Jielong is set to {channel.mention} with the {role.mention} winner role.")
    else:
        await interaction.response.send_message(f"✅ Chengyu Jielong is set to {channel.mention}. No winner role configured.")


@bot.tree.command(name="ping", description="Replies with Pong and the bot's latency!")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"Pong! 🏓 ({latency}ms)")


@bot.tree.command(name="cylb", description="Show the Chengyu Jielong leaderboard for this server")
async def cylb(interaction: discord.Interaction):
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
    delta = chengyu_game.get_time_until_reset()
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    await interaction.response.send_message(
        f"⏰ The Chengyu leaderboard resets in {hours}h {minutes}m {seconds}s."
    )


@bot.tree.command(name="cyscore", description="Show the current Chengyu score for a user")
@app_commands.describe(user="Optional user to look up; defaults to you")
async def cyscore(interaction: discord.Interaction, user: discord.Member | None = None):
    target_user = user or interaction.user
    score = chengyu_game.get_score(interaction.guild_id or 0, target_user.id)

    if score is None:
        await interaction.response.send_message(f"📊 {target_user.display_name} has no Chengyu points yet.")
        return

    await interaction.response.send_message(
        f"📊 {target_user.display_name} has {score['valid_entries']} Chengyu point(s) this month."
    )


@bot.command()
@commands.is_owner()
async def sync(ctx):
    try:
        synced = await bot.tree.sync()
        await ctx.send(f"Successfully synced {len(synced)} slash command(s) globally!")
    except Exception as e:
        await ctx.send(f"Failed to sync commands: {e}")


@bot.tree.command(name="define", description="Look up a Chinese word or search in English!")
@app_commands.describe(query="Chinese characters, Pinyin, or an English word")
async def define(interaction: discord.Interaction, query: str):
    await interaction.response.defer()

    result = dictionary.search(query)

    if not result:
        await interaction.followup.send(f"❌ Sorry, I couldn't find any entries for **'{query}'**.")
        return

    if isinstance(result, list):
        embed = discord.Embed(
            title=f"🔍 English Search Results for: '{query}'",
            description="Here are the top matches I found:",
            color=discord.Color.blue(),
        )

        for i, entry in enumerate(result, 1):
            name = f"{i}. {entry['simplified']}"
            if entry['traditional'] != entry['simplified']:
                name += f" ({entry['traditional']})"
            name += f" — {entry['pinyin']}"

            defs = entry['definitions'][:2]
            defs_text = "; ".join(defs)
            if len(entry['definitions']) > 2:
                defs_text += "..."

            embed.add_field(name=name, value=defs_text, inline=False)

        embed.set_footer(text="Type /define with one of the Chinese words above for full details!")
        await interaction.followup.send(embed=embed)
        return

    title_display = f"{result['simplified']}"
    if result['traditional'] != result['simplified']:
        title_display += f" ({result['traditional']})"

    embed = discord.Embed(
        title=title_display,
        color=discord.Color.green(),
    )

    embed.add_field(
        name="Pronunciation",
        value=f"🗣️ **{result['pinyin']}** *(raw: {result['pinyin_raw']})*",
        inline=False,
    )

    definitions_formatted = "\n".join([f"{i}. {d}" for i, d in enumerate(result['definitions'], 1)])
    if not definitions_formatted:
        definitions_formatted = "*No direct translation available.*"

    embed.add_field(
        name="Definitions",
        value=definitions_formatted,
        inline=False,
    )

    if result['measure_words']:
        mw_formatted = ", ".join(result['measure_words'])
        embed.add_field(name="Measure Words (量词)", value=f"📏 {mw_formatted}", inline=False)

    if result['variants']:
        variants_formatted = "\n".join([f"• {v}" for v in result['variants']])
        embed.add_field(name="Character Variants", value=f"🔄 {variants_formatted}", inline=False)

    embed.set_footer(text="Data provided by CC-CEDICT")
    await interaction.followup.send(embed=embed)


bot.run(TOKEN)