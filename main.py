
import os
import re
import io
import base64
import asyncio
import threading

import discord
from discord import app_commands
from discord.ext import commands
from flask import Flask
from google import genai


# =========================================================
# CONFIG
# =========================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

GEMINI_IMAGE_MODEL = "gemini-3.1-flash-image"

# Empty list means all servers where the bot is installed.
ALLOWED_SERVER_IDS = []

# Maximum time to wait for image generation.
GENERATION_TIMEOUT = 120

# Allow only one image-generation request at a time.
generation_lock = asyncio.Lock()


# =========================================================
# GEMINI CLIENT
# =========================================================

if GEMINI_API_KEY:
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    print("Gemini API key loaded.")
else:
    gemini_client = None
    print("WARNING: GEMINI_API_KEY environment variable not found.")


# =========================================================
# BASIC PROMPT FILTER
# Note: This is only a basic filter, not complete moderation.
# =========================================================

BANNED_PATTERNS = [
    r"\bnsfw\b",
    r"\bnude\b",
    r"\bnudes\b",
    r"\bnaked\b",
    r"\bporn\b",
    r"\bpornography\b",
    r"\bsex\b",
    r"\bsexual\b",
    r"\berotic\b",
    r"\bexplicit\b",
    r"\bxxx\b",
]


def contains_banned_words(text: str) -> bool:
    return any(
        re.search(pattern, text, re.IGNORECASE)
        for pattern in BANNED_PATTERNS
    )


# =========================================================
# DISCORD BOT
# =========================================================

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as exc:
        print(f"Command sync error: {exc!r}")


# =========================================================
# IMAGE GENERATION COMMAND
# =========================================================

@bot.tree.command(
    name="generate-pfp",
    description="Generate a high-quality AI profile picture."
)
@app_commands.describe(
    prompt="Describe the profile picture you want.",
    image="Optional reference image."
)
async def generate_pfp(
    interaction: discord.Interaction,
    prompt: str,
    image: discord.Attachment = None
):
    # Server restriction
    if (
        ALLOWED_SERVER_IDS
        and interaction.guild_id not in ALLOWED_SERVER_IDS
    ):
        await interaction.response.send_message(
            "This server is not authorized to use this bot.",
            ephemeral=True
        )
        return

    # Basic text filter
    if contains_banned_words(prompt):
        await interaction.response.send_message(
            "Please use a safe, SFW image prompt.",
            ephemeral=True
        )
        return

    if gemini_client is None:
        await interaction.response.send_message(
            "Gemini API is not configured. Contact the bot owner.",
            ephemeral=True
        )
        return

    # Avoid piling up multiple generation requests
    if generation_lock.locked():
        await interaction.response.send_message(
            "Another image is being generated. Please try again later.",
            ephemeral=True
        )
        return

    await generation_lock.acquire()

    try:
        # Validate optional reference image
        if image is not None:
            if (
                not image.content_type
                or not image.content_type.startswith("image/")
            ):
                await interaction.response.send_message(
                    "Please upload a valid image file.",
                    ephemeral=True
                )
                return

            if image.size > 10 * 1024 * 1024:
                await interaction.response.send_message(
                    "Please use an image smaller than 10 MB.",
                    ephemeral=True
                )
                return

        await interaction.response.defer(thinking=True)

        smart_prompt = f"""
Create a high-quality, completely SFW Discord profile picture.

USER REQUEST:
{prompt}

INSTRUCTIONS:
- Understand the full request and its context.
- Preserve the requested subject, colors, clothing, theme,
  pose, mood, environment and composition.
- Make the image polished, detailed and visually clear.
- Use professional lighting and strong composition.
- Prefer a square 1:1 profile-picture layout.
- Avoid unrelated objects and random characters.
- If a public gaming creator is mentioned, create a respectful,
  non-sexual artistic depiction.
- Do not create nudity, sexual imagery or explicit content.
- Do not sexualize minors.
- Follow all applicable image safety requirements.

Generate the final image.
"""

        gemini_input = []

        # Include the reference image when provided
        if image is not None:
            image_bytes = await image.read()

            if len(image_bytes) > 10 * 1024 * 1024:
                await interaction.followup.send(
                    "Please use an image smaller than 10 MB.",
                    ephemeral=True
                )
                return

            gemini_input.append({
                "type": "image",
                "mime_type": image.content_type,
                "data": base64.b64encode(
                    image_bytes
                ).decode("utf-8")
            })

        gemini_input.append({
            "type": "text",
            "text": smart_prompt
        })

        # Synchronous SDK call runs outside Discord's event loop.
        def generate_image():
            return gemini_client.interactions.create(
                model=GEMINI_IMAGE_MODEL,
                input=gemini_input,
                response_format={
                    "type": "image",
                    "mime_type": "image/jpeg",
                    "aspect_ratio": "1:1",
                    "image_size": "1K"
                },
                generation_config={
                    "thinking_level": "minimal"
                }
            )

        print("Starting Gemini image generation...")

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(generate_image),
                timeout=GENERATION_TIMEOUT
            )
        except asyncio.TimeoutError:
            print("IMAGE GENERATION TIMED OUT")
            await interaction.followup.send(
                "Gemini took too long to respond. "
                "Please try again later.",
                ephemeral=True
            )
            return

        # Extract generated image
        output_image = getattr(result, "output_image", None)

        if not output_image or not output_image.data:
            print("Gemini returned no output image.")
            await interaction.followup.send(
                "Gemini did not return an image. "
                "Try a different prompt.",
                ephemeral=True
            )
            return

        generated_bytes = base64.b64decode(output_image.data)

        generated_file = discord.File(
            fp=io.BytesIO(generated_bytes),
            filename="cursed-pfp.jpg"
        )

        embed = discord.Embed(
            title="Your Cursed PFP is Ready!",
            description=f"**Prompt:** {prompt}",
            color=discord.Color.purple()
        )

        embed.set_footer(
            text="Generated with Gemini AI • SFW"
        )
        embed.set_image(url="attachment://cursed-pfp.jpg")

        await interaction.followup.send(
            embed=embed,
            file=generated_file
        )

        print("Image generation completed successfully.")

    except Exception as exc:
        # Print technical details in Render logs.
        print("=" * 50)
        print("IMAGE GENERATION ERROR")
        print(repr(exc))
        print("=" * 50)

        # Show a limited error message in Discord.
        error_text = str(exc)
        error_text = error_text.replace("`", "'")[:1000]

        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Image generation failed:\n```{error_text}```",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"Image generation failed:\n```{error_text}```",
                    ephemeral=True
                )
        except Exception as send_exc:
            print(f"Could not send error to Discord: {send_exc!r}")

    finally:
        generation_lock.release()


# =========================================================
# RENDER WEB SERVER
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Cursed Pfp AI is alive!"


def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


def keep_alive():
    thread = threading.Thread(
        target=run_web,
        daemon=True
    )
    thread.start()


# =========================================================
# START BOT
# =========================================================

if __name__ == "__main__":
    keep_alive()

    if not DISCORD_TOKEN:
        print("ERROR: DISCORD_TOKEN environment variable not found.")
    elif not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY environment variable not found.")
    else:
        bot.run(DISCORD_TOKEN)
    
