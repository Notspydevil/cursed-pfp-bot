import os
from flask import Flask
import threading
import re
import urllib.parse
import discord
from discord import app_commands
from discord.ext import commands

ALLOWED_SERVER_IDS = []

BANNED_WORDS = [
    r"\bnsfw\b", r"\bnude\b", r"\bnaked\b", r"\bsex\b", r"\bporn\b",
    r"\bblood\b", r"\bgore\b", r"\bkill\b", r"\babuse\b"
]

def contains_banned_words(text: str) -> bool:
    for pattern in BANNED_WORDS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Error syncing commands: {e}")

@bot.tree.command(name="generate-pfp", description="Generate or edit an aesthetic AI profile picture!")
@app_commands.describe(
    prompt="Describe the PFP you want (e.g., 'cyberpunk anime boy with purple hair')",
    image="Optional: Upload an image to make edits or generate similar PFP"
)
async def generate_pfp(
    interaction: discord.Interaction, 
    prompt: str, 
    image: discord.Attachment = None
):
    if ALLOWED_SERVER_IDS and interaction.guild_id not in ALLOWED_SERVER_IDS:
        await interaction.response.send_message(
            "❌ This server is not authorized to use Cursed Pfp AI. Contact the owner for access!", 
            ephemeral=True
        )
        return

    if contains_banned_words(prompt):
        await interaction.response.send_message(
            "⚠️ Your prompt contains prohibited terms. Please keep prompts safe and SFW!", 
            ephemeral=True
        )
        return

    await interaction.response.defer(thinking=True)

    encoded_prompt = urllib.parse.quote(prompt)
    
    if image and image.content_type and image.content_type.startswith("image/"):
        image_url = urllib.parse.quote(image.url)
        final_image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?image={image_url}&nologo=true"
    else:
        final_image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?nologo=true"

    embed = discord.Embed(
        title="✨ Your Cursed PFP is Ready!",
        description=f"**Prompt:** {prompt}",
        color=discord.Color.purple()
    )
    if image:
        embed.set_footer(text="Generated with image reference edit/variation.")
    else:
        embed.set_footer(text="Generated with Cursed Pfp AI")
        
    embed.set_image(url=final_image_url)

    await interaction.followup.send(embed=embed)

TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
else:
    print("Error: DISCORD_TOKEN environment variable not set!")
  
