import os
import discord
from discord.ext import commands
from dotenv import load_load

# Load environment variables from .env file (local) or system (Railway)
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}!")

@bot.command()
async def define(ctx, word: str):
    # Placeholder for your dictionary logic
    await ctx.send(f"You want to define: {word}. Logic coming soon!")

bot.run(TOKEN)