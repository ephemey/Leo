import os
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from dictionary import ChineseDictionary
from karaoke import setup as register_karaoke_commands

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Setup intents
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)

dictionary = ChineseDictionary()
register_karaoke_commands(bot)


@bot.event
async def on_ready():
    dictionary.load_dictionary()
    print(f"Logged in as {bot.user.name}!")
    print("------")
    # Automatically sync slash commands globally on startup
    try:
        synced = await bot.tree.sync()
        print(f"Successfully synced {len(synced)} slash command(s) globally.")
    except Exception as e:
        print(f"Error syncing commands: {e}")

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


# ==========================================
# ADVANCED DICTIONARY SLASH COMMAND
# ==========================================
@bot.tree.command(name="define", description="Look up a Chinese word or search in English!")
@app_commands.describe(query="Chinese characters, Pinyin, or an English word")
async def define(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    
    result = dictionary.search(query)
    
    if not result:
        await interaction.followup.send(f"❌ Sorry, I couldn't find any entries for **'{query}'**.")
        return
        
    # Scenario A: The search returned multiple English results (a list)
    if isinstance(result, list):
        embed = discord.Embed(
            title=f"🔍 English Search Results for: '{query}'",
            description="Here are the top matches I found:",
            color=discord.Color.blue()
        )
        
        for i, entry in enumerate(result, 1):
            # Format: "1. 你好 (nǐ hǎo)"
            name = f"{i}. {entry['simplified']}"
            if entry['traditional'] != entry['simplified']:
                name += f" ({entry['traditional']})"
            name += f" — {entry['pinyin']}"
            
            # Show the first 2 definitions to keep the embed clean
            defs = entry['definitions'][:2]
            defs_text = "; ".join(defs)
            if len(entry['definitions']) > 2:
                defs_text += "..."
                
            embed.add_field(name=name, value=defs_text, inline=False)
            
        embed.set_footer(text="Type /define with one of the Chinese words above for full details!")
        await interaction.followup.send(embed=embed)
        return

    # Scenario B: Single direct result (Simplified, Traditional, Pinyin, or single English match)
    title_display = f"{result['simplified']}"
    if result['traditional'] != result['simplified']:
        title_display += f" ({result['traditional']})"

    embed = discord.Embed(
        title=title_display,
        color=discord.Color.green()
    )
    
    embed.add_field(
        name="Pronunciation", 
        value=f"🗣️ **{result['pinyin']}** *(raw: {result['pinyin_raw']})*", 
        inline=False
    )
    
    definitions_formatted = "\n".join([f"{i}. {d}" for i, d in enumerate(result['definitions'], 1)])
    if not definitions_formatted:
        definitions_formatted = "*No direct translation available.*"
        
    embed.add_field(
        name="Definitions", 
        value=definitions_formatted, 
        inline=False
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