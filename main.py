import discord
from discord.ext import commands
from discord import app_commands
import discord.ui
import json
import os
import re
import asyncio
import aiohttp
from datetime import datetime, timedelta
import random
from flask import Flask
import threading
import time
import logging
logging.basicConfig(level=logging.WARNING)


# ============================================================
# FLASK - Render port binding
# ============================================================
app = Flask(__name__)

@app.route('/')
def home():
    return 'Reddit Workers Bot online!'

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# ============================================================
# CONFIG
# ============================================================
DISCORD_TOKEN     = os.getenv('DISCORD_TOKEN')
DATA_FILE         = 'links.json'
TASKS_FILE        = 'tasks.json'
BALANCES_FILE     = 'balances.json'
CATEGORY_NAME     = 'Redditors'
LOG_CHANNEL       = 'admin-logs'
PAYPAL_THRESHOLD  = 5.00
CHECK_INTERVAL    = 7200  # 2 hours
TASK_DURATION     = 43200 # 12 hours

# ============================================================
# BOT SETUP
# ============================================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='/', intents=intents)

# ============================================================
# DATA HELPERS
# ============================================================
def load_data(file):
    try:
        with open(file, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_data(data, file):
    with open(file, 'w') as f:
        json.dump(data, f, indent=2)

links    = load_data(DATA_FILE)
tasks    = load_data(TASKS_FILE)
balances = load_data(BALANCES_FILE)

# ============================================================
# REDDIT PUBLIC API HELPERS
# ============================================================
async def get_reddit_user_info(username):
    url = f'https://www.reddit.com/user/{username}/about.json'
    headers = {'User-Agent': 'DiscordBot/1.0'}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    d = data['data']
                    karma = d.get('link_karma', 0) + d.get('comment_karma', 0)
                    created = datetime.utcfromtimestamp(d['created_utc'])
                    age_days = (datetime.utcnow() - created).days
                    age_years = age_days // 365
                    age_months = (age_days % 365) // 30
                    if age_years >= 1:
                        age_str = f'{age_years}Y'
                    else:
                        age_str = f'{age_months}M'
                    if karma >= 1000:
                        karma_str = f'{karma // 1000}K'
                    else:
                        karma_str = str(karma)
                    return {'karma': karma_str, 'age': age_str, 'valid': True}
                return {'valid': False}
    except:
        return {'valid': False}

async def check_comment_exists(comment_url):
    if '?' in comment_url:
        json_url = comment_url.split('?')[0] + '.json'
    else:
        json_url = comment_url.rstrip('/') + '.json'
    headers = {'User-Agent': 'DiscordBot/1.0'}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(json_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, list) and len(data) > 1:
                        comments = data[1]['data']['children']
                        return len(comments) > 0
                return False
    except:
        return False

# ============================================================
# ON READY
# ============================================================
@bot.event
async def on_ready():
    print(f'{bot.user} online!')
    try:
        # Only sync to your own server, way faster + no global rate limit
        guild = discord.Object(id=YOUR_GUILD_ID)  # ← put your server ID here
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        print(f'Synced {len(synced)} commands')
    except Exception as e:
        print(e)
    bot.loop.create_task(task_checker_loop())
create_task(task_checker_loop())

# ============================================================
# PAYMENT CHOICE BUTTONS
# ============================================================
class PaymentView(discord.ui.View):
    def __init__(self, username, karma_str, age_str, user_id, guild):
        super().__init__(timeout=120)
        self.username = username
        self.karma_str = karma_str
        self.age_str = age_str
        self.user_id = user_id
        self.guild = guild

    @discord.ui.button(label='💰 PayPal (paid at $5)', style=discord.ButtonStyle.primary)
    async def paypal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.finish_registration(interaction, 'paypal')

    @discord.ui.button(label='₿ Crypto (paid per task)', style=discord.ButtonStyle.success)
    async def crypto_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.finish_registration(interaction, 'crypto')

    async def finish_registration(self, interaction: discord.Interaction, pay_type: str):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        member = interaction.user
        username = self.username

        if str(member.id) in links:
            await interaction.followup.send('❌ Already linked! Use /unlink first.', ephemeral=True)
            return
        if any(v['reddit'] == username for v in links.values()):
            await interaction.followup.send('❌ Reddit username already linked to someone else.', ephemeral=True)
            return

        links[str(member.id)] = {
            'reddit': username,
            'karma': self.karma_str,
            'age': self.age_str,
            'payment': pay_type,
            'joined': datetime.utcnow().isoformat()
        }
        save_data(links, DATA_FILE)

        if str(member.id) not in balances:
            balances[str(member.id)] = {'balance': 0.0, 'total_earned': 0.0}
            save_data(balances, BALANCES_FILE)

        verified_role = discord.utils.get(guild.roles, name='Verified-Redditors')
        if not verified_role:
            verified_role = await guild.create_role(name='Verified-Redditors', color=discord.Color.green())
        await member.add_roles(verified_role)

        pay_role_name = 'PayPal-Workers' if pay_type == 'paypal' else 'Crypto-Workers'
        pay_role = discord.utils.get(guild.roles, name=pay_role_name)
        if not pay_role:
            color = discord.Color.blue() if pay_type == 'paypal' else discord.Color.gold()
            pay_role = await guild.create_role(name=pay_role_name, color=color)
        await member.add_roles(pay_role)

        nickname = f'{member.display_name[:15]} [u/{username} | K:{self.karma_str} | A:{self.age_str}]'
        try:
            await member.edit(nick=nickname[:32])
        except:
            pass

        category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
        if not category:
            category = await guild.create_category(CATEGORY_NAME)

        channel_name = f'private-{username}'
        existing = discord.utils.get(guild.text_channels, name=channel_name)
        if not existing:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                member: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            }
            for r in guild.roles:
                if r.permissions.administrator:
                    overwrites[r] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

            channel = await guild.create_text_channel(
                channel_name,
                category=category,
                overwrites=overwrites,
                topic=f'u/{username} | K:{self.karma_str} | A:{self.age_str} | {pay_role_name}'
            )
        else:
            channel = existing

        pay_info = 'Paid per task after 12h ₿' if pay_type == 'crypto' else 'Paid via PayPal when balance hits $5 💰'
        await channel.send(
            f'✅ **Welcome <@{member.id}>!**\n'
            f'Reddit: u/{username} | Karma: {self.karma_str} | Age: {self.age_str}\n'
            f'Payment: {pay_info}\n\n'
            f'Your admin will send tasks here. Good luck! 🚀'
        )

        log_ch = discord.utils.get(guild.text_channels, name=LOG_CHANNEL)
        if log_ch:
            await log_ch.send(
                f'🆕 **New Worker Registered**\n'
                f'Discord: <@{member.id}>\n'
                f'Reddit: u/{username} | K:{self.karma_str} | A:{self.age_str}\n'
                f'Payment: {pay_role_name}\n'
                f'Channel: {channel.mention}'
            )

        pay_msg = 'PayPal at $5 threshold' if pay_type == 'paypal' else 'Crypto per task'
        await interaction.followup.send(
            f'✅ **Registered!**\n'
            f'Reddit: u/{username}\n'
            f'Payment: {pay_msg}\n'
            f'Check your private channel!',
            ephemeral=True
        )
        self.stop()

# ============================================================
# /link
# ============================================================
@bot.tree.command(name='link', description='Register your Reddit account')
async def link(interaction: discord.Interaction):
    if str(interaction.user.id) in links:
        return await interaction.response.send_message('❌ Already linked! Use /unlink first.', ephemeral=True)
    modal = LinkModal()
    await interaction.response.send_modal(modal)

class LinkModal(discord.ui.Modal, title='Register Reddit Account'):
    reddit_username = discord.ui.TextInput(
        label='Your Reddit Username',
        placeholder='e.g. AyoubBoutarfa (no u/ needed)',
        required=True,
        max_length=20
    )

    async def on_submit(self, interaction: discord.Interaction):
        username = self.reddit_username.value.strip().lstrip('u/').lower()
        if not re.match(r'^[a-z0-9_-]+$', username):
            return await interaction.response.send_message('❌ Invalid username format.', ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        info = await get_reddit_user_info(username)
        if not info['valid']:
            return await interaction.followup.send('❌ Reddit account not found or suspended.', ephemeral=True)
        if any(v['reddit'] == username for v in links.values()):
            return await interaction.followup.send('❌ This Reddit account is already linked.', ephemeral=True)
        view = PaymentView(username, info['karma'], info['age'], interaction.user.id, interaction.guild)
        await interaction.followup.send(
            f'✅ **Found:** u/{username} | Karma: {info["karma"]} | Age: {info["age"]}\n\n'
            f'**Choose your payment method:**',
            view=view,
            ephemeral=True
        )

# ============================================================
# /task (admin)
# ============================================================
@bot.tree.command(name='task', description='Admin: Assign task to a worker')
@app_commands.describe(reddit_username='Worker Reddit username', amount='Pay amount e.g. 1.50', details='Task instructions')
async def task_cmd(interaction: discord.Interaction, reddit_username: str, amount: str, details: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message('👮 Admin only!', ephemeral=True)
    username = reddit_username.strip().lstrip('u/').lower()
    channel = discord.utils.get(interaction.guild.text_channels, name=f'private-{username}')
    if not channel:
        return await interaction.response.send_message(f'❌ No private channel for u/{username}', ephemeral=True)
    task_id = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=6))
    tasks[task_id] = {
        'reddit': username,
        'amount': float(amount),
        'details': details,
        'status': 'waiting_comment',
        'channel_id': channel.id,
        'created': datetime.utcnow().isoformat()
    }
    save_data(tasks, TASKS_FILE)
    await channel.send(
        f'📋 **NEW TASK** `#{task_id}`\n'
        f'━━━━━━━━━━━━━━━━━━━━\n'
        f'{details}\n'
        f'━━━━━━━━━━━━━━━━━━━━\n'
        f'💵 Pay: **${amount}**\n\n'
        f'✅ **Reply with your Reddit comment link to start the 12h timer.**'
    )
    await interaction.response.send_message(f'✅ Task `#{task_id}` sent to u/{username}', ephemeral=True)
# ============================================================
# CLAIM BUTTON VIEW
# ============================================================
class ClaimView(discord.ui.View):
    def __init__(self, task_id: str, amount: str, description: str, post_link: str):
        super().__init__(timeout=None)
        self.task_id = task_id
        self.amount = amount
        self.description = description
        self.post_link = post_link

    @discord.ui.button(label='✅ Claim Task', style=discord.ButtonStyle.success, custom_id='claim_task_btn')
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        member = interaction.user

        # Must be verified
        verified_role = discord.utils.get(guild.roles, name='Verified-Redditors')
        if not verified_role or verified_role not in member.roles:
            await interaction.followup.send('❌ You must be a verified worker to claim tasks. Use /link first.', ephemeral=True)
            return

        # Check if task already claimed
        if tasks.get(f'pub_{self.task_id}', {}).get('claimed'):
            await interaction.followup.send('❌ This task was already claimed!', ephemeral=True)
            return

        # Max 1 active task at a time
        for t in tasks.values():
            if t.get('claimer_id') == str(member.id) and t.get('status') in ('waiting_comment', 'timer_running'):
                await interaction.followup.send('❌ You already have an active task. Finish it first!', ephemeral=True)
                return

        # Mark claimed immediately (race condition protection)
        pub_key = f'pub_{self.task_id}'
        if pub_key not in tasks:
            tasks[pub_key] = {}
        if tasks[pub_key].get('claimed'):
            await interaction.followup.send('❌ This task was just claimed by someone else!', ephemeral=True)
            return
        tasks[pub_key]['claimed'] = True
        tasks[pub_key]['claimer_id'] = str(member.id)
        save_data(tasks, TASKS_FILE)

        # Disable button
        button.label = '🔒 Task Claimed'
        button.disabled = True
        button.style = discord.ButtonStyle.secondary
        await interaction.message.edit(view=self)

        # Get worker reddit username
        user_data = links.get(str(member.id))
        reddit_username = user_data['reddit'] if user_data else member.name

        # Reuse existing private channel or create one
        channel_name = f'private-{reddit_username}'
        channel = discord.utils.get(guild.text_channels, name=channel_name)
        if not channel:
            category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
            if not category:
                category = await guild.create_category(CATEGORY_NAME)
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                member: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            }
            for r in guild.roles:
                if r.permissions.administrator:
                    overwrites[r] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            channel = await guild.create_text_channel(channel_name, category=category, overwrites=overwrites)

        # Create task entry (same format as /task so checker loop works)
        task_id = self.task_id
        tasks[task_id] = {
            'reddit': reddit_username,
            'amount': float(self.amount),
            'details': self.description,
            'status': 'waiting_comment',
            'channel_id': channel.id,
            'claimer_id': str(member.id),
            'created': datetime.utcnow().isoformat()
        }
        save_data(tasks, TASKS_FILE)

        await channel.send(
            f'📋 **NEW TASK** `#{task_id}`\n'
            f'━━━━━━━━━━━━━━━━━━━━\n'
            f'{self.description}\n'
            f'🔗 Post: {self.post_link}\n'
            f'━━━━━━━━━━━━━━━━━━━━\n'
            f'💵 Pay: **${self.amount}**\n\n'
            f'✅ **Reply with your Reddit comment link to start the 12h timer.**'
        )

        await interaction.followup.send(f'✅ Task claimed! Go to {channel.mention}', ephemeral=True)

        log_ch = discord.utils.get(guild.text_channels, name=LOG_CHANNEL)
        if log_ch:
            await log_ch.send(
                f'📌 **Task Claimed** `#{task_id}`\n'
                f'Worker: <@{member.id}> (u/{reddit_username})\n'
                f'Pay: ${self.amount}\n'
                f'Channel: {channel.mention}'
            )

# ============================================================
# /publish (admin)
# ============================================================
@bot.tree.command(name='publish', description='Admin: Publish a task to jobs channel')
@app_commands.describe(
    description='What the worker needs to do',
    amount='Pay amount e.g. 1.50',
    post_link='The Reddit post link'
)
async def publish_cmd(interaction: discord.Interaction, description: str, amount: str, post_link: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message('👮 Admin only!', ephemeral=True)

    jobs_channel = discord.utils.get(interaction.guild.text_channels, name='jobs-available')
    if not jobs_channel:
        return await interaction.response.send_message('❌ #jobs-available channel not found!', ephemeral=True)

    task_id = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=6))

    embed = discord.Embed(title='🆕 New Task Available!', color=discord.Color.green(), timestamp=datetime.utcnow())
    embed.add_field(name='📝 Task', value=description, inline=False)
    embed.add_field(name='💰 Pay', value=f'${amount}', inline=True)
    embed.add_field(name='🔗 Post', value=post_link, inline=True)
    embed.add_field(name='⚡ How to Claim', value='Click below — first come first served!', inline=False)
    embed.set_footer(text='Verified workers only • Max 1 active task at a time')

    view = ClaimView(task_id=task_id, amount=amount, description=description, post_link=post_link)
    await jobs_channel.send(content='@everyone 🚨 New task available!', embed=embed, view=view)
    await interaction.response.send_message(f'✅ Task `#{task_id}` published!', ephemeral=True)

# ============================================================
# MESSAGE LISTENER
# ============================================================
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if not message.channel.name.startswith('private-'):
        await bot.process_commands(message)
        return

    reddit_url_pattern = r'https?://(www\.)?reddit\.com/r/\S+/comments/\S+'
    if not re.search(reddit_url_pattern, message.content):
        await bot.process_commands(message)
        return

    active_task = None
    task_id = None
    for tid, t in tasks.items():
        if t['channel_id'] == message.channel.id and t['status'] == 'waiting_comment':
            active_task = t
            task_id = tid
            break

    if not active_task:
        # Check if waiting for wallet
        for tid, t in tasks.items():
            if t['channel_id'] == message.channel.id and t['status'] == 'waiting_wallet':
                tasks[tid]['btc_wallet'] = message.content.strip()
                tasks[tid]['status'] = 'pending_payment'
                save_data(tasks, TASKS_FILE)
                await message.channel.send(
                    f'₿ **BTC Wallet saved!**\n'
                    f'Admin has been notified. Payment coming soon! ✅'
                )
                for g in bot.guilds:
                    log_ch = discord.utils.get(g.text_channels, name=LOG_CHANNEL)
                    if log_ch:
                        await log_ch.send(
                            f'₿ **PAY NOW** - u/{t["reddit"]}\n'
                            f'Amount: ${t["amount"]}\n'
                            f'BTC: `{message.content.strip()}`\n'
                            f'Channel: {message.channel.mention}'
                        )
                break

        # Check if waiting for PayPal
        for tid, t in tasks.items():
            if t['channel_id'] == message.channel.id and t['status'] == 'waiting_paypal':
                tasks[tid]['paypal_email'] = message.content.strip()
                tasks[tid]['status'] = 'pending_payment'
                save_data(tasks, TASKS_FILE)
                user_id = None
                for uid, data in links.items():
                    if data['reddit'] == t['reddit']:
                        user_id = uid
                        break
                bal = balances.get(user_id, {}).get('balance', 0.0) if user_id else 0.0
                await message.channel.send(
                    f'💰 **PayPal email saved!**\n'
                    f'Admin has been notified. Payment of **${bal}** coming soon! ✅'
                )
                for g in bot.guilds:
                    log_ch = discord.utils.get(g.text_channels, name=LOG_CHANNEL)
                    if log_ch:
                        await log_ch.send(
                            f'💰 **PAY NOW** - u/{t["reddit"]}\n'
                            f'Amount: ${bal}\n'
                            f'PayPal: `{message.content.strip()}`\n'
                            f'Channel: {message.channel.mention}'
                        )
                break

        await bot.process_commands(message)
        return

    await message.channel.send('🔍 Checking your comment...')
    exists = await check_comment_exists(message.content.strip())
    if not exists:
        await message.channel.send(
            '❌ **Comment not found.**\n'
            '• Make sure the link is correct\n'
            '• Comment must be public\n'
            '• Try again'
        )
        return

    tasks[task_id]['status'] = 'timer_running'
    tasks[task_id]['comment_url'] = message.content.strip()
    tasks[task_id]['timer_start'] = datetime.utcnow().isoformat()
    tasks[task_id]['timer_end'] = (datetime.utcnow() + timedelta(hours=12)).isoformat()
    save_data(tasks, TASKS_FILE)

    end_time = datetime.utcnow() + timedelta(hours=12)
    await message.channel.send(
        f'✅ **Comment verified! 12h timer started.**\n'
        f'⏰ Ends: **{end_time.strftime("%Y-%m-%d %H:%M")} UTC**\n\n'
        f'⚠️ DO NOT delete your comment!\n'
        f'Bot checks every 2h.\n'
        f'Stay 12h = **PAID** ✅ | Deleted = **DISQUALIFIED** ❌'
    )
    await bot.process_commands(message)

# ============================================================
# TASK CHECKER LOOP
# ============================================================
async def task_checker_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        now = datetime.utcnow()
        for task_id, t in list(tasks.items()):
            await asyncio.sleep(0.5)  # ← ADD HERE
            if t['status'] != 'timer_running':
                continue
            timer_end = datetime.fromisoformat(t['timer_end'])
            channel = bot.get_channel(t['channel_id'])
            if not channel:
                continue
            if now >= timer_end:
                exists = await check_comment_exists(t['comment_url'])
                if exists:
                    user_id = None
                    user_data = None
                    for uid, udata in links.items():
                        if udata['reddit'] == t['reddit']:
                            user_data = udata
                            user_id = uid
                            break
                    pay_type = user_data['payment'] if user_data else 'paypal'
                    if pay_type == 'crypto':
                        tasks[task_id]['status'] = 'waiting_wallet'
                        save_data(tasks, TASKS_FILE)
                        await channel.send(
                            f'🎉 **QUALIFIED! 12h complete!**\n'
                            f'💵 Earned: **${t["amount"]}**\n\n'
                            f'₿ **Send your BTC wallet address here to receive payment.**'
                        )
                    else:
                        if user_id and user_id in balances:
                            balances[user_id]['balance'] = round(balances[user_id]['balance'] + t['amount'], 2)
                            balances[user_id]['total_earned'] = round(balances[user_id]['total_earned'] + t['amount'], 2)
                            save_data(balances, BALANCES_FILE)
                            bal = balances[user_id]['balance']
                            if bal >= PAYPAL_THRESHOLD:
                                tasks[task_id]['status'] = 'waiting_paypal'
                                save_data(tasks, TASKS_FILE)
                                await channel.send(
                                    f'🎉 **QUALIFIED!**\n'
                                    f'Added: **${t["amount"]}** | Balance: **${bal}**\n\n'
                                    f'💰 **You reached $5! Send your PayPal email here.**'
                                )
                            else:
                                tasks[task_id]['status'] = 'complete'
                                save_data(tasks, TASKS_FILE)
                                await channel.send(
                                    f'🎉 **QUALIFIED!**\n'
                                    f'Added: **${t["amount"]}** | Balance: **${bal}/$5.00**\n'
                                    f'Keep going to reach $5! 💪'
                                )
                    for g in bot.guilds:
                        log_ch = discord.utils.get(g.text_channels, name=LOG_CHANNEL)
                        if log_ch:
                            await log_ch.send(
                                f'✅ **QUALIFIED** `#{task_id}`\n'
                                f'u/{t["reddit"]} | ${t["amount"]}\n'
                                f'Channel: {channel.mention}'
                            )
                else:
                    tasks[task_id]['status'] = 'disqualified'
                    save_data(tasks, TASKS_FILE)
                    await channel.send(
                        f'❌ **DISQUALIFIED** `#{task_id}`\n'
                        f'Comment was removed before 12h.\n'
                        f'No payment for this task.'
                    )
            else:
                timer_start = datetime.fromisoformat(t['timer_start'])
                elapsed = (now - timer_start).total_seconds()
                if 21400 <= elapsed <= 21800 and not t.get('warned_6h'):
                    tasks[task_id]['warned_6h'] = True
                    save_data(tasks, TASKS_FILE)
                    hours_left = int((timer_end - now).total_seconds() // 3600)
                    await channel.send(f'⏳ **{hours_left}h remaining!** Keep that comment up!')
        await asyncio.sleep(CHECK_INTERVAL)

# ============================================================
# /balance
# ============================================================
@bot.tree.command(name='balance', description='Check your earnings balance')
async def balance_cmd(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    if user_id not in links:
        return await interaction.response.send_message('❌ Not registered. Use /link', ephemeral=True)
    bal_data = balances.get(user_id, {'balance': 0.0, 'total_earned': 0.0})
    pay_type = links[user_id]['payment']
    if pay_type == 'paypal':
        await interaction.response.send_message(
            f'💰 Balance: **${bal_data["balance"]}** / $5.00\n'
            f'Total Earned: **${bal_data["total_earned"]}**',
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f'₿ Total Earned: **${bal_data["total_earned"]}**\n'
            f'Paid per task after 12h.',
            ephemeral=True
        )

# ============================================================
# /workers (admin)
# ============================================================
@bot.tree.command(name='workers', description='Admin: List all workers')
async def workers_cmd(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message('👮 Admin only!', ephemeral=True)
    if not links:
        return await interaction.response.send_message('No workers yet.', ephemeral=True)
    msg = '👥 **All Workers**\n━━━━━━━━━━━━━━━\n'
    for uid, data in links.items():
        bal = balances.get(uid, {}).get('balance', 0.0)
        total = balances.get(uid, {}).get('total_earned', 0.0)
        e = '💰' if data['payment'] == 'paypal' else '₿'
        msg += f'{e} u/{data["reddit"]} | K:{data["karma"]} | A:{data["age"]} | Bal:${bal} | Total:${total}\n'
    await interaction.response.send_message(msg, ephemeral=True)

# ============================================================
# /paid (admin)
# ============================================================
@bot.tree.command(name='paid', description='Admin: Confirm payment sent')
@app_commands.describe(reddit_username='Worker Reddit username')
async def paid_cmd(interaction: discord.Interaction, reddit_username: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message('👮 Admin only!', ephemeral=True)
    username = reddit_username.strip().lstrip('u/').lower()
    user_id = next((uid for uid, d in links.items() if d['reddit'] == username), None)
    if not user_id:
        return await interaction.response.send_message(f'❌ u/{username} not found', ephemeral=True)
    amount = balances.get(user_id, {}).get('balance', 0.0)
    balances[user_id]['balance'] = 0.0
    save_data(balances, BALANCES_FILE)
    channel = discord.utils.get(interaction.guild.text_channels, name=f'private-{username}')
    if channel:
        await channel.send(f'✅ **${amount} payment sent! Balance reset to $0. Keep it up! 🚀**')
    await interaction.response.send_message(f'✅ Marked ${amount} paid to u/{username}', ephemeral=True)

# ============================================================
# /unlink
# ============================================================
@bot.tree.command(name='unlink', description='Remove your Reddit link')
async def unlink_cmd(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    if user_id not in links:
        return await interaction.response.send_message('❌ Not linked.', ephemeral=True)
    data = links.pop(user_id)
    save_data(links, DATA_FILE)
    guild = interaction.guild
    member = interaction.user
    for rn in ['Verified-Redditors', 'PayPal-Workers', 'Crypto-Workers']:
        role = discord.utils.get(guild.roles, name=rn)
        if role and role in member.roles:
            await member.remove_roles(role)
    channel = discord.utils.get(guild.text_channels, name=f'private-{data["reddit"]}')
    if channel:
        await channel.delete()
    try:
        await member.edit(nick=None)
    except:
        pass
    await interaction.response.send_message('✅ Unlinked and cleaned up.', ephemeral=True)

# ============================================================
# /removeworker (admin)
# ============================================================
@bot.tree.command(name='removeworker', description='Admin: Remove a worker')
@app_commands.describe(reddit_username='Reddit username to remove')
async def removeworker_cmd(interaction: discord.Interaction, reddit_username: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message('👮 Admin only!', ephemeral=True)
    username = reddit_username.strip().lstrip('u/').lower()
    user_id = next((uid for uid, d in links.items() if d['reddit'] == username), None)
    if not user_id:
        return await interaction.response.send_message(f'❌ u/{username} not found', ephemeral=True)
    links.pop(user_id)
    save_data(links, DATA_FILE)
    guild = interaction.guild
    member = guild.get_member(int(user_id))
    if member:
        for rn in ['Verified-Redditors', 'PayPal-Workers', 'Crypto-Workers']:
            role = discord.utils.get(guild.roles, name=rn)
            if role and role in member.roles:
                await member.remove_roles(role)
        try:
            await member.edit(nick=None)
        except:
            pass
    channel = discord.utils.get(guild.text_channels, name=f'private-{username}')
    if channel:
        await channel.delete()
    await interaction.response.send_message(f'✅ Removed u/{username}', ephemeral=True)

# ============================================================
# RUN
# ============================================================
if __name__ == '__main__':
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    time.sleep(2)
    bot.run(DISCORD_TOKEN)
