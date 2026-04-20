import os
import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user} ({bot.user.id})")


async def main():
    async with bot:
        await bot.load_extension("bot.cogs.music")
        await bot.start(os.environ["DISCORD_TOKEN"])


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
