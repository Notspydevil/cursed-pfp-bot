import os
from flask import Flask
import threading
import re
import urllib.parse
import discord
from discord import app_commands
from discord.ext import commands
import google.generativeai as genai

# Render Environment Variable se API Key load karein (Safe & Secure)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    gemini_model = genai.GenerativeModel('gemini-1.5-flash')
else:
    gemini_model = None

ALLOWED_SERVER_IDS = []

BANNED_WORDS = [
    r"nsfw\b", r"nude\b", r"naked\b", r"sex\b", r"porn\b",
    r"bkl\b", r"chut\b", r"bhosd\b"
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
        print(f'Synced {len(synced)} command(s)')
    except Exception as e:
        print(f'Error syncing commands: {e}')

@bot.tree.command(name="generate-pfp", description="Generate or edit an aesthetic AI profile picture with Gemini intelligence!")
@app_commands.describe(
    prompt="Describe the PFP you want (e.g., Techno Gamerz, cyber punk anime boy).",
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

    try:
        optimized_prompt = prompt
        
        # Gemini AI prompt enhancer ko aur strong banate hain
        if gemini_model:
            safety_prompt = (
                f"You are a master AI art prompt engineer. Expand the user's short prompt into a rich, highly detailed, "
                f"visually stunning image generation prompt in English. If the user specifies a known personality or gamer like 'Techno Gamerz', "
                f"describe a cool gaming setup, stylish gamer character with headphones and glowing RGB lighting fitting that theme. "
                f"Keep it completely safe for work (SFW). "
                f"User prompt: '{prompt}'. "
                f"Give me ONLY the final detailed descriptive prompt text, nothing else."
            )
            response = gemini_model.generate_content(safety_prompt)
            if response and hasattr(response, 'text') and response.text:
                optimized_prompt = response.text.strip()

        encoded_prompt = urllib.parse.quote(optimized_prompt)

        if image and image.content_type and image.content_type.startswith("image/"):
            image_url = urllib.parse.quote(image.url)
            final_image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?image={image_url}&nologo=true"
        else:
            final_image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?nologo=true"

        embed = discord.Embed(
            title="✨ Your Smart & Safe PFP is Ready!",
            description=f"**Original:** {prompt}\n**Gemini Optimized:** {optimized_prompt[:200]}...",
            color=discord.Color.purple()
        )
        if image:
            embed.set_footer(text="Generated with image reference edit/variation.")
        else:
            embed.set_footer(text="Generated with Gemini AI intelligence.")
        
        embed.set_image(url=final_image_url)
        await interaction.followup.send(embed=embed)

    except Exception as e:
        print(f"Error in generate-pfp: {e}")
        await interaction.followup.send(f"⚠️ Error aa gaya bhai: {str(e)}", ephemeral=True)

# Flask keep alive server for Render
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive and running!"

def run():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

def keep_alive():
    t = threading.Thread(target=run)
    t.start()

if __name__ == '__main__':
    keep_alive()
    TOKEN = os.getenv("DISCORD_TOKEN")
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("Error: DISCORD_TOKEN environment variable not found.")
            
