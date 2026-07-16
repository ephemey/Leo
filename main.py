import os
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Setup intents
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}!")
    print("------")

# ==========================================
# 1. THE SLASH COMMAND
# ==========================================
@bot.tree.command(name="ping", description="Replies with Pong and the bot's latency!")
async def ping(interaction: discord.Interaction):
    # Calculate latency in milliseconds
    latency = round(bot.latency * 1000)
    # Slash commands use interaction.response.send_message instead of ctx.send
    await interaction.response.send_message(f"Pong! 🏓 ({latency}ms)")

# ==========================================
# 2. THE SYNC COMMAND (Prefix-based)
# ==========================================
# Discord requires us to manually "sync" slash commands. 
# This standard !sync command lets you do it easily from your server.
@bot.command()
@commands.is_owner() # Only you (the bot creator) can run this
async def sync(ctx):
    try:
        synced = await bot.tree.sync()
        await ctx.send(f"Successfully synced {len(synced)} slash command(s) globally!")
    except Exception as e:
        await ctx.send(f"Failed to sync commands: {e}")

bot.run(TOKEN)