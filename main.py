import discord
from discord.ext import commands
import json
import os
import re
from datetime import datetime
import random

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

@bot.tree.command(name='link', description='Link your Reddit username')
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
            await interaction.response.send_message('❌ Invalid username. Letters/numbers/-/_ only.', ephemeral=True)
            return

        code = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=6))
        while code in codes:
            code = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=6))

        codes[code] = {
            'user_id': interaction.user.id, 
            'username': username, 
            'timestamp': datetime.now().isoformat()
        }
        save_data(codes, CODES_FILE)

        await interaction.response.send_message(
            f'✅ **Check Reddit DMs** for code `{code}`\\n'
            f'Reply to bot with code → Admin verifies → Private channel created!',
            ephemeral=True
        )
        print(f'Code {code} for u/{username}')

from discord import app_commands

@bot.tree.command(name='verify_reddit', description='🔐 Admin: Verify Reddit code')
@app_commands.describe(code='6-char code from Reddit DM reply')
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
        if not user:
            return await interaction.response.send_message('❌ User not found', ephemeral=True)

        # Unique role
        role_name = f'Reddit_{reddit_username}'
        role = discord.utils.get(guild.roles, name=role_name)
        if not role:
            role = await guild.create_role(name=role_name)

        await user.add_roles(role)

        # Private channel
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            role: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        channel = await guild.create_text_channel(
            f'private-{reddit_username}',
            overwrites=overwrites,
            topic=f'🔒 Reddit: u/{reddit_username} | Discord: <@{user_id}>'
        )

        await channel.send(f'''
✅ **Welcome to your private channel!** <@{user_id}>
**Reddit:** u/{reddit_username}
**For:** Task assignments & private chat
        ''')

        await interaction.response.send_message(f'✅ Verified u/{reddit_username} → Channel: #{channel.name}', ephemeral=True)
    else:
        await interaction.response.send_message('❌ Invalid/expired code', ephemeral=True)

@bot.tree.command(name='unlink', description='🗑️ Remove your Reddit link')
async def unlink(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    if user_id in links:
        reddit_username = links.pop(user_id)
        save_data(links, DATA_FILE)

        # Cleanup
        guild = interaction.guild
        role_name = f'Reddit_{reddit_username}'
        role = discord.utils.get(guild.roles, name=role_name)
        if role:
            await role.delete()

        channel_name = f'private-{reddit_username}'
        channel = discord.utils.get(guild.text_channels, name=channel_name)
        if channel:
            await channel.delete()

        await interaction.response.send_message('✅ Unlinked + cleaned up!', ephemeral=True)
    else:
        await interaction.response.send_message('ℹ️ Not linked.', ephemeral=True)

@bot.tree.command(name='status', description='📊 Check your link status')
async def status(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    if user_id in links:
        username = links[user_id]
        await interaction.response.send_message(f'✅ Linked: u/{username}', ephemeral=True)
    else:
        await interaction.response.send_message('❌ Not linked. Use /link', ephemeral=True)

bot.run(DISCORD_TOKEN)
