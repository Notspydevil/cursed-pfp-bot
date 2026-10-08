import os
import base64
import asyncio
import threading
import re

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

GEMINI_IMAGE_MODEL = "gemini-3.1-flash-image"

ALLOWED_SERVER_IDS = []


# =========================================================
# GEMINI CLIENT
# =========================================================

if not GEMINI_API_KEY:
    print("WARNING: GEMINI_API_KEY environment variable not found.")
    gemini_client = None
else:
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)


# =========================================================
# BASIC SAFETY FILTER
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
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Command sync error: {e}")


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
            "❌ Gemini API is not configured correctly. "
            "Please contact the bot owner.",
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


    await interaction.response.defer(thinking=True)


    try:

        # -------------------------------------------------
        # BUILD SMART IMAGE PROMPT
        # -------------------------------------------------

        smart_prompt = f"""
Create a high-quality SFW profile picture based on the user's request below.

USER REQUEST:
{prompt}

IMPORTANT INSTRUCTIONS:

- Understand the user's complete request instead of blindly copying keywords.
- Preserve the important identity, theme, character, colors, clothing,
  environment, mood, pose and composition requested by the user.
- If the user mentions a public gaming creator or celebrity, create a
  respectful, non-sexual artistic depiction suitable for a profile picture.
- Make the result visually polished and detailed.
- Use professional lighting, strong composition and clear subject separation.
- Make the image suitable for a Discord profile picture.
- Prefer a square 1:1 composition.
- Do not add random characters or unrelated objects.
- Do not create sexual, nude, erotic or explicit content.
- Do not sexualize minors.
- Do not create hateful or otherwise harmful imagery.
- If the request conflicts with safety requirements, refuse the unsafe
  portion and produce no unsafe imagery.

Create the final image directly.
"""


        # -------------------------------------------------
        # PREPARE GEMINI INPUT
        # -------------------------------------------------

        gemini_input = []


        if image is not None:

            image_bytes = await image.read()

            if len(image_bytes) > 10 * 1024 * 1024:
                await interaction.followup.send(
                    "❌ Please use an image smaller than 10 MB."
                )
                return

            encoded_image = base64.b64encode(
                image_bytes
            ).decode("utf-8")

            gemini_input.append(
                {
                    "type": "image",
                    "data": encoded_image,
                    "mime_type": image.content_type
                }
            )


        gemini_input.append(
            {
                "type": "text",
                "text": smart_prompt
            }
        )


        # -------------------------------------------------
        # GENERATE IMAGE
        # -------------------------------------------------

        def generate_image():

            return gemini_client.interactions.create(
                model=GEMINI_IMAGE_MODEL,
                input=gemini_input,
                response_format={
                    "type": "image",
                    "mime_type": "image/png",
                    "aspect_ratio": "1:1",
                    "image_size": "1K"
                }
            )


        interaction_result = await asyncio.to_thread(
            generate_image
        )


        # -------------------------------------------------
        # GET GENERATED IMAGE
        # -------------------------------------------------

        if not interaction_result.output_image:
            await interaction.followup.send(
                "⚠️ Gemini did not return an image. "
                "Try changing your prompt."
            )
            return


        image_data = interaction_result.output_image.data

        generated_bytes = base64.b64decode(image_data)


        # -------------------------------------------------
        # SEND IMAGE TO DISCORD
        # -------------------------------------------------

        generated_file = discord.File(
            fp=__import__("io").BytesIO(generated_bytes),
            filename="cursed-pfp.png"
        )


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
                text="Gemini generated this using your reference image."
            )
        else:
            embed.set_footer(
                text="Generated with Gemini AI • SFW"
            )


        embed.set_image(
            url="attachment://cursed-pfp.png"
        )


        await interaction.followup.send(
            embed=embed,
            file=generated_file
        )


    # =====================================================
    # ERROR HANDLING
    # =====================================================

    except Exception as e:

        print("========================================")
        print("IMAGE GENERATION ERROR")
        print(repr(e))
        print("========================================")

        await interaction.followup.send(
            f"⚠️ Image generation failed.\n```{str(e)[:1500]}```",
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
        os.environ.get("PORT", 8080)
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

        bot.run(DISCORD_TOKEN)
