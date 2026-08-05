import logging

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)


def _trunc(text: str, limit: int = 1024) -> str:
    """Truncate text to Discord embed field limit."""
    if len(text) <= limit:
        return text
    return text[:limit - 3] + "..."


def format_xinhua_embed(result: tuple[str, dict]) -> discord.Embed:
    """Build a Discord embed for a chinese-xinhua lookup result."""
    kind, entry = result

    def skip(val: str) -> bool:
        return not val or val.strip() in ("无", "")

    if kind == "idiom":
        embed = discord.Embed(title=entry.get("word", ""), color=discord.Color.orange())
        pinyin = entry.get("pinyin", "")
        if pinyin:
            embed.add_field(name="拼音 Pronunciation", value=f"🗣️ {pinyin}", inline=False)
        explanation = entry.get("explanation", "")
        if not skip(explanation):
            embed.add_field(name="释义 Explanation", value=_trunc(explanation), inline=False)
        derivation = entry.get("derivation", "")
        if not skip(derivation):
            embed.add_field(name="出处 Derivation", value=_trunc(derivation), inline=False)
        example = entry.get("example", "")
        if not skip(example):
            embed.add_field(name="例句 Example", value=_trunc(example), inline=False)

    elif kind == "word":
        embed = discord.Embed(title=entry.get("word", ""), color=discord.Color.teal())
        pinyin = entry.get("pinyin", "")
        if pinyin:
            embed.add_field(name="拼音 Pronunciation", value=f"🗣️ {pinyin}", inline=True)
        radicals = entry.get("radicals", "")
        strokes = entry.get("strokes", "")
        if radicals or strokes:
            rad_strokes = f"部首: {radicals}  笔画: {strokes}".strip()
            embed.add_field(name="部首 / 笔画", value=rad_strokes, inline=True)
        explanation = entry.get("explanation", "")
        if not skip(explanation):
            embed.add_field(name="释义 Explanation", value=_trunc(explanation), inline=False)

    elif kind == "xiehouyu":
        embed = discord.Embed(title=entry.get("riddle", ""), color=discord.Color.gold())
        embed.add_field(name="答案 Answer", value=entry.get("answer", ""), inline=False)

    else:  # ci
        embed = discord.Embed(title=entry.get("ci", ""), color=discord.Color.blurple())
        explanation = entry.get("explanation", "")
        if not skip(explanation):
            embed.add_field(name="释义 Explanation", value=_trunc(explanation), inline=False)

    embed.set_footer(text="Data provided by chinese-xinhua")
    return embed


def setup(bot, dictionary, xinhua_dictionary) -> None:
    @bot.tree.command(name="define", description="Look up a Chinese word or search in English!")
    @app_commands.describe(query="Chinese characters, Pinyin, or an English word")
    @app_commands.guild_only()
    async def define(interaction: discord.Interaction, query: str):
        logger.info("/define triggered by %s in guild='%s': query='%s'", interaction.user, interaction.guild.name if interaction.guild else interaction.guild_id, query)
        await interaction.response.defer()

        result = dictionary.search(query)

        if not result:
            # Fallback to chinese-xinhua when CC-CEDICT has no match
            xinhua_result = xinhua_dictionary.search(query)
            if xinhua_result:
                embed = format_xinhua_embed(xinhua_result)
                await interaction.followup.send(embed=embed)
                logger.info("/define '%s' resolved via Xinhua fallback", query)
            else:
                await interaction.followup.send(f"❌ Sorry, I couldn't find any entries for **'{query}'**.")
                logger.info("/define '%s' found no results", query)
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
            logger.info("/define '%s' returned %d English search result(s)", query, len(result))
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
        logger.info("/define '%s' resolved via CC-CEDICT", query)


def setup_owner_commands(bot) -> None:
    @bot.command()
    @commands.is_owner()
    @commands.guild_only()
    async def sync(ctx):
        logger.info("!sync triggered by %s", ctx.author)
        try:
            synced = await bot.tree.sync()
            await ctx.send(f"Successfully synced {len(synced)} slash command(s) globally!")
            logger.info("Synced %d slash command(s) via !sync", len(synced))
        except Exception as e:
            await ctx.send(f"Failed to sync commands: {e}")
            logger.error("Failed to sync commands via !sync: %s", e)
