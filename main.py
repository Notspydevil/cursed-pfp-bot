import os
import base64
import asyncio
import threading
import re
import io

from flask import Flask

import discord
from discord import app_commands
from discord.ext import commands

from google import genai


# =========================================================
# CONFIG
# =========================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Current Gemini image-generation model
GEMINI_IMAGE_MODEL = "gemini-3.1-flash-image"

# Leave empty [] to allow every server.
ALLOWED_SERVER_IDS = []


# =========================================================
# GEMINI CLIENT
# =========================================================

if not GEMINI_API_KEY:
    print("WARNING: GEMINI_API_KEY environment variable not found.")
    gemini_client = None
else:
    gemini_client = genai.Client(
        api_key=GEMINI_API_KEY
    )


# =========================================================
# BASIC SFW FILTER
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
    for pattern in BANNED_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True

    return False


# =========================================================
# DISCORD BOT
# =========================================================

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================================================
# BOT READY
# =========================================================

@bot.event
async def on_ready():

    print(f"Logged in as {bot.user}")

    try:
        synced = await bot.tree.sync()

        print(
            f"Synced {len(synced)} command(s)"
        )

    except Exception as e:

        print(
            f"Command sync error: {repr(e)}"
        )


# =========================================================
# GENERATE PFP COMMAND
# =========================================================

@bot.tree.command(
    name="generate-pfp",
    description="Generate a high-quality AI profile picture."
)
@app_commands.describe(
    prompt="Describe the PFP you want.",
    image="Optional reference image."
)
async def generate_pfp(
    interaction: discord.Interaction,
    prompt: str,
    image: discord.Attachment = None
):

    # -----------------------------------------------------
    # SERVER CHECK
    # -----------------------------------------------------

    if (
        ALLOWED_SERVER_IDS
        and interaction.guild_id not in ALLOWED_SERVER_IDS
    ):

        await interaction.response.send_message(
            "❌ This server is not authorized to use Cursed Pfp AI.",
            ephemeral=True
        )

        return


    # -----------------------------------------------------
    # BASIC PROMPT SAFETY CHECK
    # -----------------------------------------------------

    if contains_banned_words(prompt):

        await interaction.response.send_message(
            "⚠️ I can only generate safe, SFW images. "
            "Please try a different prompt.",
            ephemeral=True
        )

        return


    # -----------------------------------------------------
    # GEMINI CHECK
    # -----------------------------------------------------

    if gemini_client is None:

        await interaction.response.send_message(
            "❌ Gemini API is not configured correctly.",
            ephemeral=True
        )

        return


    # -----------------------------------------------------
    # IMAGE CHECK
    # -----------------------------------------------------

    if image is not None:

        if not image.content_type:

            await interaction.response.send_message(
                "❌ I couldn't identify that file as an image.",
                ephemeral=True
            )

            return


        if not image.content_type.startswith("image/"):

            await interaction.response.send_message(
                "❌ Please upload a valid image file.",
                ephemeral=True
            )

            return


    # -----------------------------------------------------
    # DISCORD THINKING
    # -----------------------------------------------------

    await interaction.response.defer(
        thinking=True
    )


    try:

        # =================================================
        # SMART IMAGE PROMPT
        # =================================================

        smart_prompt = f"""
Create a high-quality, completely SFW profile picture
based on the user's request.

USER REQUEST:
{prompt}

IMAGE REQUIREMENTS:

- Understand the complete request and its context.
- Preserve the requested subject, theme, colors,
  clothing, environment, mood, pose and composition.
- Do not randomly change important details.
- Make the subject visually clear and well composed.
- Use professional lighting and strong visual contrast.
- Create a polished, high-quality gaming/profile-picture style.
- Prefer a square 1:1 composition.
- Keep the main subject clearly visible.
- Do not add unrelated people, objects or text.
- If a public gaming creator or celebrity is mentioned,
  make a respectful, non-sexual artistic depiction.
- Do not create sexual, nude, erotic or explicit imagery.
- Do not sexualize minors.
- Do not create hateful or otherwise harmful imagery.
- Follow the image model's safety requirements.

Generate the final image directly.
"""


        # =================================================
        # GEMINI INPUT
        # =================================================

        gemini_input = []


        # -------------------------------------------------
        # REFERENCE IMAGE
        # -------------------------------------------------

        if image is not None:

            image_bytes = await image.read()


            # Maximum Discord upload size for this bot
            if len(image_bytes) > 10 * 1024 * 1024:

                await interaction.followup.send(
                    "❌ Please use an image smaller than 10 MB.",
                    ephemeral=True
                )

                return


            encoded_image = base64.b64encode(
                image_bytes
            ).decode("utf-8")


            gemini_input.append(
                {
                    "type": "image",
                    "mime_type": image.content_type,
                    "data": encoded_image
                }
            )


        # -------------------------------------------------
        # TEXT PROMPT
        # -------------------------------------------------

        gemini_input.append(
            {
                "type": "text",
                "text": smart_prompt
            }
        )


        # =================================================
        # GEMINI IMAGE GENERATION
        # =================================================

        def generate_image():

            return gemini_client.interactions.create(
                model=GEMINI_IMAGE_MODEL,

                input=gemini_input,

                response_format={
                    "type": "image",
                    "mime_type": "image/jpeg",
                    "aspect_ratio": "1:1",
                    "image_size": "1K"
                }
            )


        interaction_result = await asyncio.to_thread(
            generate_image
        )


        # =================================================
        # CHECK GEMINI RESPONSE
        # =================================================

        if not interaction_result.output_image:

            await interaction.followup.send(
                "⚠️ Gemini did not return an image. "
                "Try changing your prompt.",
                ephemeral=True
            )

            return


        # =================================================
        # DECODE IMAGE
        # =================================================

        image_data = interaction_result.output_image.data

        generated_bytes = base64.b64decode(
            image_data
        )


        # =================================================
        # CREATE DISCORD FILE
        # =================================================

        generated_file = discord.File(
            fp=io.BytesIO(generated_bytes),
            filename="cursed-pfp.jpg"
        )


        # =================================================
        # DISCORD EMBED
        # =================================================

        embed = discord.Embed(
            title="✨ Your Cursed PFP is Ready!",
            description=(
                f"**Prompt:** {prompt}\n\n"
                "Generated with Gemini AI."
            ),
            color=discord.Color.purple()
        )


        if image is not None:

            embed.set_footer(
                text=(
                    "Gemini generated this using "
                    "your reference image • SFW"
                )
            )

        else:

            embed.set_footer(
                text="Generated with Gemini AI • SFW"
            )


        # -------------------------------------------------
        # ATTACHED JPEG
        # -------------------------------------------------

        embed.set_image(
            url="attachment://cursed-pfp.jpg"
        )


        # =================================================
        # SEND RESULT
        # =================================================

        await interaction.followup.send(
            embed=embed,
            file=generated_file
        )


    # =====================================================
    # ERROR HANDLING
    # =====================================================

    except Exception as e:

        print(
            "========================================"
        )

        print(
            "IMAGE GENERATION ERROR"
        )

        print(
            repr(e)
        )

        print(
            "========================================"
        )


        # Keep the Discord error useful but limited
        error_text = str(e)

        if len(error_text) > 1500:
            error_text = error_text[:1500] + "..."


        await interaction.followup.send(
            "⚠️ Image generation failed.\n"
            f"```{error_text}```",
            ephemeral=True
        )


# =========================================================
# RENDER WEB SERVER
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():

    return "Cursed Pfp AI is alive!"


def run_web():

    port = int(
        os.environ.get(
            "PORT",
            8080
        )
    )


    app.run(
        host="0.0.0.0",
        port=port
    )


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

        print(
            "ERROR: DISCORD_TOKEN environment variable not found."
        )


    elif not GEMINI_API_KEY:

        print(
            "ERROR: GEMINI_API_KEY environment variable not found."
        )


    else:

        bot.run(
            DISCORD_TOKEN
        )
