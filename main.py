import discord
from discord.ext import commands
import json
import os
import re
from datetime import datetime
import random
from flask import Flask
import threading
import time

# Flask for Render port binding
app = Flask(__name__)

@app.route('/')
def home():
    return '🤖 Reddit Link Bot online! Slash commands: /link /status /unlink'

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DATA_FILE = 'links.json'
CODES_FILE = 'codes.json'

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)

def load_data(file):
    try:
        with open(file, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_data(data, file):
    with open(file, 'w') as f:
        json.dump(data, f, indent=2)

links = load_data(DATA_FILE)
codes = load_data(CODES_FILE)

@bot.event
async def on_ready():
    print(f'{bot.user} online!')
    try:
        synced = await bot.tree.sync()
        print(f'Synced {len(synced)} command(s)')
    except Exception as e:
        print(e)

@bot.tree.command(name='link', description='🔗 Link your Reddit username')
async def link(interaction: discord.Interaction):
    modal = LinkModal()
    await interaction.response.send_modal(modal)

class LinkModal(discord.ui.Modal, title='Link Reddit Account'):
    reddit_username = discord.ui.TextInput(
        label='Reddit Username',
        placeholder='e.g., AyoubBoutarfa',
        required=True,
        max_length=20
    )

    async def on_submit(self, interaction: discord.Interaction):
        username = self.reddit_username.value.strip().lower()
        if not re.match(r'^[a-z0-9_-]+$', username):
            await interaction.response.send_message('❌ Invalid: letters/numbers/-/_ only.', ephemeral=True)
            return

        code = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=6))
        while code in codes:
            code = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=6))

        codes[code] = {'user_id': interaction.user.id, 'username': username, 'timestamp': datetime.now().isoformat()}
        save_data(codes, CODES_FILE)

        await interaction.response.send_message(f'✅ Check Reddit DM for code `{code}`\nAdmin /verify_reddit {code}', ephemeral=True)
        print(f'Generated {code} for u/{username}')

from discord import app_commands

@bot.tree.command(name='verify_reddit', description='🔐 Admin verify Reddit code')
@app_commands.describe(code='6-char code from Reddit')
async def verify_reddit(interaction: discord.Interaction, code: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message('👮 Admin only!', ephemeral=True)

    if code in codes:
        data = codes.pop(code)
        user_id = data['user_id']
        reddit_username = data['username']
        links[str(user_id)] = reddit_username
        save_data(links, DATA_FILE)

        guild = interaction.guild
        user = guild.get_member(user_id)
        if user:
            role_name = f'Reddit_{reddit_username}'
            role = discord.utils.get(guild.roles, name=role_name)
            if not role:
                role = await guild.create_role(name=role_name)
            await user.add_roles(role)

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                role: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
            channel = await guild.create_text_channel(f'private-{reddit_username}', overwrites=overwrites)
            await channel.send(f'✅ Private channel <@{user_id}>\nReddit: u/{reddit_username}')
            await interaction.response.send_message(f'✅ Verified u/{reddit_username} → #{channel.name}', ephemeral=True)
        else:
            await interaction.response.send_message('❌ User not found', ephemeral=True)
    else:
        await interaction.response.send_message('❌ Invalid code', ephemeral=True)

@bot.tree.command(name='unlink', description='🗑️ Unlink Reddit account')
async def unlink(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    if user_id in links:
        reddit_username = links.pop(user_id)
        save_data(links, DATA_FILE)
        guild = interaction.guild
        role = discord.utils.get(guild.roles, name=f'Reddit_{reddit_username}')
        if role: await role.delete()
        channel = discord.utils.get(guild.text_channels, name=f'private-{reddit_username}')
        if channel: await channel.delete()
        await interaction.response.send_message('✅ Unlinked + cleanup done', ephemeral=True)
    else:
        await interaction.response.send_message('ℹ️ Not linked', ephemeral=True)

@bot.tree.command(name='status', description='📊 Check link status')
async def status(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    username = links.get(user_id, 'Not linked')
    await interaction.response.send_message(f'🔗 **Status:** u/{username}', ephemeral=True)

if __name__ == '__main__':
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    time.sleep(2)
    bot.run(DISCORD_TOKEN)
