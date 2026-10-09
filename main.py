
import os
import io
import re
import base64
import asyncio
import logging
from flask import Flask
from threading import Thread

import discord
from discord import app_commands
from google import genai

# ---------------- CONFIG ----------------

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

MODEL_NAME = "gemini-3.1-flash-image"
REQUEST_TIMEOUT_MS = 180_000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    force=True,
)
log = logging.getLogger("cursed-pfp")

app = Flask(__name__)

@app.get("/")
def home():
    return "Cursed Pfp AI is running!", 200


def run_web_server():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))


if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN environment variable is missing.")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY environment variable is missing.")

# Set a real HTTP timeout in the Google SDK.
gemini_client = genai.Client(
    api_key=GEMINI_API_KEY,
    http_options={"timeout": REQUEST_TIMEOUT_MS},
)

# ---------------- SAFETY ----------------

BLOCKED_PATTERNS = [
    r"\bnude\b",
    r"\bnudity\b",
    r"\btopless\b",
    r"\bexplicit\s+sex\b",
    r"\bsexual\s+act\b",
    r"\bporn(?:ography)?\b",
    r"\bhentai\b",
    r"\bgenitals?\b",
    r"\bnsfw\b",
    r"\bsexually\s+explicit\b",
]

def is_blocked_prompt(prompt: str) -> bool:
    return any(
        re.search(pattern, prompt, flags=re.IGNORECASE)
        for pattern in BLOCKED_PATTERNS
    )


def make_prompt(user_prompt: str) -> str:
    return (
        "Create one polished, square 1:1 profile picture. "
        "The result must be safe for work and appropriate for a general audience. "
        "No nudity, sexual content, suggestive posing, or explicit imagery. "
        "Make the composition striking and readable at small avatar size. "
        "Follow the user's creative idea while keeping the image non-explicit. "
        "Do not add random text, watermarks, or logos unless specifically requested. "
        f"User's image idea: {user_prompt}"
    )


# ---------------- GEMINI IMAGE GENERATION ----------------

def generate_image(prompt: str, reference_bytes=None, reference_mime=None):
    log.info("Gemini image request started. Model=%s", MODEL_NAME)

    if reference_bytes:
        image_input = [
            {
                "type": "image",
                "mime_type": reference_mime or "image/png",
                "data": base64.b64encode(reference_bytes).decode("utf-8"),
            },
            {
                "type": "text",
                "text": (
                    make_prompt(prompt)
                    + " Use the supplied image only as a visual reference. "
                    "Do not copy any inappropriate content."
                ),
            },
        ]
    else:
        image_input = make_prompt(prompt)

    result = gemini_client.interactions.create(
        model=MODEL_NAME,
        input=image_input,
        response_format={
            "type": "image",
            "mime_type": "image/jpeg",
            "aspect_ratio": "1:1",
            "image_size": "1K",
        },
        timeout=REQUEST_TIMEOUT_MS / 1000,
    )

    output_image = getattr(result, "output_image", None)
    if not output_image or not getattr(output_image, "data", None):
        raise RuntimeError(
            "Gemini returned no image. Check model access and API response."
        )

    image_bytes = base64.b64decode(output_image.data)
    if not image_bytes:
        raise RuntimeError("Gemini returned empty image data.")

    log.info("Gemini returned image successfully (%d bytes).", len(image_bytes))
    return image_bytes


# ---------------- DISCORD BOT ----------------

intents = discord.Intents.default()
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

generation_lock = asyncio.Lock()


@bot.event
async def on_ready():
    log.info("Discord bot logged in as %s", bot.user)
    try:
        synced = await tree.sync()
        log.info("Slash commands synced: %d", len(synced))
    except Exception:
        log.exception("Slash command sync failed")


@tree.command(
    name="generate-pfp",
    description="Generate a safe-for-work AI profile picture",
)
@app_commands.describe(
    prompt="Describe the profile picture you want",
    reference="Optional image to use as a visual reference",
)
async def generate_pfp(
    interaction: discord.Interaction,
    prompt: str,
    reference: discord.Attachment = None,
):
    log.info(
        "Slash command received: user_id=%s prompt_length=%d",
        interaction.user.id,
        len(prompt),
    )

    if is_blocked_prompt(prompt):
        await interaction.response.send_message(
            "❌ This prompt isn't allowed. Please use a non-explicit, "
            "safe-for-work image idea.",
            ephemeral=True,
        )
        return

    if len(prompt) > 700:
        await interaction.response.send_message(
            "Please keep your prompt under 700 characters.",
            ephemeral=True,
        )
        return

    reference_bytes = None
    reference_mime = None

    if reference:
        if not (reference.content_type or "").startswith("image/"):
            await interaction.response.send_message(
                "Please attach an image file as the reference.",
                ephemeral=True,
            )
            return

        if reference.size > 8 * 1024 * 1024:
            await interaction.response.send_message(
                "Reference image must be smaller than 8 MB.",
                ephemeral=True,
            )
            return

    await interaction.response.defer(thinking=True)

    if generation_lock.locked():
        await interaction.followup.send(
            "⏳ Another image is being generated. Please try again shortly.",
            ephemeral=True,
        )
        return

    async with generation_lock:
        try:
            if reference:
                log.info("Downloading reference image.")
                reference_bytes = await reference.read()
                reference_mime = reference.content_type

            log.info("Calling Gemini API now.")

            # SDK-level timeout is configured above. This outer timeout
            # prevents the Discord command from waiting indefinitely.
            image_bytes = await asyncio.wait_for(
                asyncio.to_thread(
                    generate_image,
                    prompt,
                    reference_bytes,
                    reference_mime,
                ),
                timeout=200,
            )

            file = discord.File(
                io.BytesIO(image_bytes),
                filename="cursed-pfp.jpg",
            )

            embed = discord.Embed(
                title="✨ Your AI Profile Picture",
                description=f"**Prompt:** {prompt[:900]}",
                color=discord.Color.dark_red(),
            )
            embed.set_image(url="attachment://cursed-pfp.jpg")
            embed.set_footer(text="Cursed Pfp AI • SFW generation")

            await interaction.followup.send(embed=embed, file=file)
            log.info("Image delivered to Discord successfully.")

        except asyncio.TimeoutError:
            log.error("Image generation exceeded the 200-second limit.")
            await interaction.followup.send(
                "⏱️ Gemini took too long to respond. Check Render logs "
                "for the API request result and try again later."
            )

        except Exception as exc:
            log.exception("IMAGE GENERATION FAILED")
            error_text = f"{type(exc).__name__}: {str(exc)}"
            if len(error_text) > 1200:
                error_text = error_text[:1200] + "..."

            await interaction.followup.send(
                "⚠️ Image generation failed.\n```text\n"
                + error_text
                + "\n```"
            )


# ---------------- STARTUP ----------------

if __name__ == "__main__":
    Thread(target=run_web_server, daemon=True).start()
    log.info("Starting Discord bot.")
    bot.run(DISCORD_TOKEN)
    
