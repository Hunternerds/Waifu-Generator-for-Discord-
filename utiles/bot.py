
import os
import random
import logging
import sqlite3
import time

import aiohttp
import discord

from discord.ext import commands
from dotenv import load_dotenv


# ==========================================
# CONFIGURATION
# ==========================================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

DATABASE = "image_history.db"

IMAGE_COOLDOWN = 24 * 60 * 60

MAX_ATTEMPTS_PER_PROVIDER = 5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("WaifuBot")


# ==========================================
# SFW API URLS
# ==========================================

SFW_URLS = [
    "https://nekos.best/api/v2/waifu",
    "https://api.waifu.pics/sfw/waifu",
    "https://waifu-api-eosin.vercel.app/",
    "https://waifu.marek-server.com/",
]


# ==========================================
# SFW+ API URLS
# ==========================================

SFW_PLUS_URLS = [
    "https://waifu-api-031n.onrender.com/images?IsNsfw=True",
 
]


# ==========================================
# BOT SETUP
# ==========================================

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

http_session = None


# ==========================================
# DATABASE
# ==========================================

def init_database():

    with sqlite3.connect(DATABASE) as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS used_images (
                image_url TEXT PRIMARY KEY,
                expires_at REAL NOT NULL
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_expiry
            ON used_images(expires_at)
        """)

        conn.execute("""
            DELETE FROM used_images
            WHERE expires_at <= ?
        """, (time.time(),))

        conn.commit()

    logger.info("Database initialized!")


def reserve_image(image_url):

    now = time.time()

    with sqlite3.connect(DATABASE) as conn:

        conn.execute("""
            DELETE FROM used_images
            WHERE expires_at <= ?
        """, (now,))

        cursor = conn.execute("""
            INSERT OR IGNORE INTO used_images
            (image_url, expires_at)
            VALUES (?, ?)
        """, (
            image_url,
            now + IMAGE_COOLDOWN
        ))

        conn.commit()

        return cursor.rowcount == 1


# ==========================================
# IMAGE PARSER
# ==========================================

def extract_image_url(data):

    item = None

    if isinstance(data, list):

        item = data[0] if data else None

    elif isinstance(data, dict):

        if "items" in data:

            items = data["items"]

            if isinstance(items, list):
                item = items[0] if items else None

            elif isinstance(items, dict):
                item = items

        elif "results" in data:

            results = data["results"]

            if isinstance(results, list):
                item = results[0] if results else None

        else:
            item = data

    if not isinstance(item, dict):
        return None

    image_url = (
        item.get("url")
        or item.get("image")
        or item.get("image_url")
        or item.get("display_url")
    )

    if (
        isinstance(image_url, str)
        and image_url.startswith("https://")
    ):
        return image_url

    return None


# ==========================================
# API FUNCTIONS
# ==========================================

async def fetch_image(url):

    try:

        async with http_session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=20)
        ) as response:

            if response.status != 200:

                logger.warning(
                    "API status %s: %s",
                    response.status,
                    url
                )

                return None

            data = await response.json(content_type=None)

            image_url = extract_image_url(data)

            if image_url:
                return image_url

            logger.warning(
                "No image URL found: %s | Response: %s",
                url,
                str(data)[:500]
            )

    except Exception as error:

        logger.warning(
            "API error (%s): %s",
            url,
            error
        )

    return None


async def get_random_image(url_list):

    urls = url_list.copy()
    random.shuffle(urls)

    for url in urls:

        for attempt in range(MAX_ATTEMPTS_PER_PROVIDER):

            image = await fetch_image(url)

            if not image:
                break

            if reserve_image(image):

                logger.info("New image reserved!")

                return image

            logger.info("Duplicate image skipped.")

    return None


# ==========================================
# EMBED CREATOR
# ==========================================

def make_embed(image, user, title, color):

    embed = discord.Embed(
        title=title,
        description=f"Requested by {user.mention}",
        color=color
    )

    embed.set_image(url=image)

    embed.set_footer(
        text="Anime Image Generator"
    )

    return embed


# ==========================================
# REFRESH BUTTON
# ==========================================

class ImageView(discord.ui.View):

    def __init__(
        self,
        url_list,
        owner_id,
        title,
        color
    ):

        super().__init__(timeout=120)

        self.url_list = url_list
        self.owner_id = owner_id
        self.title = title
        self.color = color

    @discord.ui.button(
        label="Another one!",
        emoji="🔄",
        style=discord.ButtonStyle.primary
    )
    async def refresh(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if interaction.user.id != self.owner_id:

            await interaction.response.send_message(
                "❌ This button belongs to another user!",
                ephemeral=True
            )

            return

        await interaction.response.defer()

        image = await get_random_image(
            self.url_list
        )

        if not image:

            await interaction.followup.send(
                "❌ No fresh images available right now.",
                ephemeral=True
            )

            return

        embed = make_embed(
            image,
            interaction.user,
            self.title,
            self.color
        )

        await interaction.message.edit(
            embed=embed,
            view=self
        )


# ==========================================
# BOT EVENTS
# ==========================================

@bot.event
async def setup_hook():

    global http_session

    init_database()

    http_session = aiohttp.ClientSession(
        headers={
            "User-Agent": "WaifuDiscordBot/1.0"
        }
    )

    await bot.tree.sync()

    logger.info("Slash commands synchronized!")
    logger.info("24-hour duplicate protection enabled!")


@bot.event
async def on_ready():

    logger.info(
        "Logged in as %s",
        bot.user
    )


# ==========================================
# /SFW COMMAND
# ==========================================

@bot.tree.command(
    name="sfw",
    description="Get a random SFW anime image"
)
async def sfw(interaction: discord.Interaction):

    await interaction.response.defer()

    image = await get_random_image(SFW_URLS)

    if not image:

        await interaction.followup.send(
            "❌ No fresh SFW images available."
        )

        return

    title = "💗 SFW Anime"

    color = discord.Color.from_rgb(
        255, 105, 180
    )

    embed = make_embed(
        image,
        interaction.user,
        title,
        color
    )

    await interaction.followup.send(
        embed=embed,
        view=ImageView(
            SFW_URLS,
            interaction.user.id,
            title,
            color
        )
    )


# ==========================================
# /SFWP COMMAND
# ==========================================

@bot.tree.command(
    name="nsfw",
    description="Get another collection of SFW anime images"
)
async def nsfw(interaction: discord.Interaction):

    await interaction.response.defer()

    image = await get_random_image(SFW_PLUS_URLS)

    if not image:

        await interaction.followup.send(
            "❌ No fresh images available."
        )

        return

    title = "✨ SFW+ Anime"

    color = discord.Color.purple()

    embed = make_embed(
        image,
        interaction.user,
        title,
        color
    )

    await interaction.followup.send(
        embed=embed,
        view=ImageView(
            SFW_PLUS_URLS,
            interaction.user.id,
            title,
            color
        )
    )


# ==========================================
# /WAIFUHELP COMMAND
# ==========================================

@bot.tree.command(
    name="waifuhelp",
    description="Show all available commands"
)
async def waifuhelp(interaction: discord.Interaction):

    embed = discord.Embed(
        title="💗 Waifu Bot Commands",
        description="Anime Image Generator",
        color=discord.Color.pink()
    )

    embed.add_field(
        name="/sfw",
        value="Get random SFW anime images.",
        inline=False
    )

    embed.add_field(
        name="/nsfw",
        value="Get images from the second SFW collection.",
        inline=False
    )

    embed.add_field(
        name="/waifuhelp",
        value="Display this help menu.",
        inline=False
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# ==========================================
# CLEANUP
# ==========================================

async def close_session():

    global http_session

    if http_session and not http_session.closed:
        await http_session.close()


# ==========================================
# START BOT
# ==========================================

if __name__ == "__main__":

    if not TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN is missing from .env"
        )

    bot.run(TOKEN)
