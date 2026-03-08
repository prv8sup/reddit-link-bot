import discord
from discord.ext import commands
import json
import os

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DATA_FILE = 'links.json'

intents = discord.Intents.default()
bot = commands.Bot(command_prefix='/', intents=intents)

def load_links():
    try:
        with open(DATA_FILE, 'r') as f:
            return {int(k): v for k, v in json.load(f).items()}
    except FileNotFoundError:
        return {}

def save_links(links):
    with open(DATA_FILE, 'w') as f:
        json.dump({str(k): v for k, v in links.items()}, f)

links = load_links()

class LinkModal(discord.ui.Modal, title='Enter Reddit Username'):
    reddit_username = discord.ui.TextInput(
        label='Username', placeholder='AyoubBoutarfa (no u/)',
        style=discord.TextStyle.short, max_length=20
    )

    def _init_(self, ctx):
        super()._init_()
        self.ctx = ctx

    async def on_submit(self, interaction: discord.Interaction):
        reddit_un = self.reddit_username.value.strip().lower()
        user_id = interaction.user.id

        if user_id in links:
            await interaction.response.send_message("❌ Already linked!", ephemeral=True)
            return

        links[user_id] = reddit_un
        save_links(links)

        guild = self.ctx.guild
        role_name = f"Reddit-{reddit_un[:10]}"
        role = discord.utils.get(guild.roles
