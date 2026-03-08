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

    def __init__(self, ctx):
        super().__init__()
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
        role = discord.utils.get(guild.roles, name=role_name)  # ← FIXED: Added )
        if not role:
            role = await guild.create_role(name=role_name, color=0x00FF00, hoist=True)

        await interaction.user.add_roles(role)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.get_member(guild.owner_id): discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, embed_links=True),
            bot.user: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }
        category = await guild.create_category(f"🔒 Private: u/{reddit_un.title()}")
        channel = await guild.create_text_channel(
            f"{interaction.user.display_name}-tasks",
            overwrites=overwrites,
            category=category,
            topic="Private 1:1 tasks"
        )
        await channel.send(f"**✅ Linked & Ready!**\n\n"
                          f"**Discord:** {interaction.user.mention}\n"
                          f"**Reddit:** `u/{reddit_un}`\n\n"
                          f"Chat tasks here!")

        await interaction.response.send_message("✅ Private task channel created!", ephemeral=True)

@bot.slash_command(name='link', description='Create your private task channel')
async def link(ctx: discord.ApplicationContext):
    modal = LinkModal(ctx)
    await ctx.interaction.response.send_modal(modal)

@bot.slash_command(name='unlink', description='Remove your channel')
async def unlink(ctx: discord.ApplicationContext):
    user_id = ctx.user.id
    if user_id in links:
        del links[user_id]
        save_links(links)
        await ctx.respond("🔓 Unlinked.", ephemeral=True)
    else:
        await ctx.respond("Not linked.", ephemeral=True)

@bot.slash_command(name='my_link', description='Your info')
async def my_link(ctx: discord.ApplicationContext):
    user_id = ctx.user.id
    un = links.get(user_id, 'None')
    await ctx.respond(f"**Reddit:** `u/{un}`" if un != 'None' else "No link.", ephemeral=True)

@bot.event
async def on_ready():
    print(f'{bot.user} ready! Links: {len(links)}')

bot.run(DISCORD_TOKEN)
