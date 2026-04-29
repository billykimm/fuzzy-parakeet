import discord
from discord.ext import commands, tasks
import time
from datetime import timedelta
import sqlite3
import shutil
import os
import random
import aiohttp
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ==========================================
# ⚙️ SYSTEM SETTINGS (FILL THESE IN!)
# ==========================================
VERIFY_CHANNEL_ID = 1498675283107250257  # Make sure this is a NUMBER, not a string
VERIFIED_ROLE_ID = 1483501648360771768

# Google Drive Settings
DRIVE_FOLDER_ID = 'YOUR_DRIVE_FOLDER_ID_HERE' # The string of letters/numbers in your Google Drive folder URL
SERVICE_ACCOUNT_FILE = 'service_account.json' # The file you get from Google Cloud

# Game Settings
SPAM_LIMIT = 5          
SPAM_TIMEFRAME = 5.0    
TIMEOUT_MINUTES = 5     
XP_PER_MESSAGE = 15     
BASE_XP = 100           
XP_MULTIPLIER = 1.5     

# Roblox Filter-Safe Words
SAFE_WORDS = ["apple", "brave", "cheese", "dragon", "eagle", "flame", "ghost", "happy", "island", "jungle", "knight", "lemon", "magic", "ninja", "ocean", "panda", "quantum", "robot", "secret", "tiger", "unicorn", "velvet", "waffle", "yellow", "zebra", "pizza", "water", "music"]

# --- MEMORY STORAGE ---
spam_tracker = {}  
pending_roblox_verifications = {} 

# Setup bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ==========================================
# 🗄️ DATABASE & GOOGLE DRIVE BACKUP
# ==========================================
conn = sqlite3.connect('levels.db')
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, xp INTEGER, level INTEGER)''')
conn.commit()

if not os.path.exists("backups"):
    os.makedirs("backups")

def get_user_data(user_id):
    cursor.execute('SELECT xp, level FROM users WHERE user_id = ?', (user_id,))
    return cursor.fetchone()

def update_user_data(user_id, xp, level):
    cursor.execute('''INSERT INTO users (user_id, xp, level) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET xp=excluded.xp, level=excluded.level''', (user_id, xp, level))
    conn.commit()

@tasks.loop(hours=12)
async def backup_database():
    """Backs up locally, then uploads to Google Drive."""
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    backup_file = f"backups/levels_backup_{timestamp}.db"
    shutil.copyfile("levels.db", backup_file)
    print(f"💾 [LOCAL BACKUP] Saved to {backup_file}")

    # Google Drive Upload
    try:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=['https://www.googleapis.com/auth/drive.file'])
        service = build('drive', 'v3', credentials=creds)
        
        file_metadata = {'name': f'levels_backup_{timestamp}.db', 'parents': [DRIVE_FOLDER_ID]}
        media = MediaFileUpload(backup_file, mimetype='application/x-sqlite3')
        
        service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        print("☁️ [DRIVE BACKUP] Successfully uploaded to Google Drive!")
    except Exception as e:
        print(f"⚠️ [DRIVE BACKUP FAILED] {e}. Ensure service_account.json is correct.")

# ==========================================
# 🎮 ROBLOX API & UI CLASSES
# ==========================================
async def get_roblox_user_id(username):
    async with aiohttp.ClientSession() as session:
        async with session.post("https://users.roblox.com/v1/usernames/users", json={"usernames": [username], "excludeBannedUsers": True}) as r:
            if r.status == 200:
                data = await r.json()
                if data["data"]: return data["data"][0]["id"]
            return None

async def get_roblox_description(user_id):
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://users.roblox.com/v1/users/{user_id}") as r:
            if r.status == 200:
                data = await r.json()
                return data.get("description", "")
            return None

class RobloxConfirmView(discord.ui.View):
    def __init__(self, discord_id):
        super().__init__(timeout=300) 
        self.discord_id = discord_id

    @discord.ui.button(label="I put the code in my bio! Verify Me.", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True) 
        user_data = pending_roblox_verifications.get(self.discord_id)
        if not user_data:
            return await interaction.followup.send("❌ Session expired. Start over.", ephemeral=True)

        roblox_id = await get_roblox_user_id(user_data["username"])
        if not roblox_id:
            return await interaction.followup.send(f"❌ No account named **{user_data['username']}**.", ephemeral=True)

        description = await get_roblox_description(roblox_id)
        if description is None:
            return await interaction.followup.send("❌ Roblox API is down. Try later.", ephemeral=True)

        if user_data["code"] in description:
            role = interaction.guild.get_role(VERIFIED_ROLE_ID)
            await interaction.user.add_roles(role)
            await interaction.followup.send("🎉 **Verification Complete!** You have been granted access.", ephemeral=True)
            del pending_roblox_verifications[self.discord_id] 
        else:
            await interaction.followup.send(f"❌ Didn't find the code. Make sure you hit save! Expected: `{user_data['code']}`", ephemeral=True)

class RobloxUsernameModal(discord.ui.Modal, title='Roblox Account Link'):
    username_input = discord.ui.TextInput(label='Enter exact Roblox Username:', required=True, max_length=50)

    async def on_submit(self, interaction: discord.Interaction):
        roblox_username = self.username_input.value.strip()
        secret_code = " ".join(random.choices(SAFE_WORDS, k=4)).title() 
        pending_roblox_verifications[interaction.user.id] = {"username": roblox_username, "code": secret_code}

        embed = discord.Embed(title="⏳ Almost there!", description=f"Paste this exact phrase in your Roblox **About** section:\n\n`{secret_code}`\n\n*Click the green button below once saved.*", color=discord.Color.orange())
        await interaction.response.send_message(embed=embed, view=RobloxConfirmView(interaction.user.id), ephemeral=True)

class MainVerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) 
    
    @discord.ui.button(label="Verify with Roblox", style=discord.ButtonStyle.primary, custom_id="roblox_btn", emoji="🟥")
    async def roblox_verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RobloxUsernameModal())

    @discord.ui.button(label="I don't play Roblox", style=discord.ButtonStyle.secondary, custom_id="discord_btn", emoji="💬")
    async def discord_verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        
        if (discord.utils.utcnow() - user.created_at) < timedelta(days=21):
            return await interaction.response.send_message("❌ Account must be 3+ weeks old.", ephemeral=True)
        if user.avatar is None:
            return await interaction.response.send_message("❌ Suspicious account (No PFP). Use Roblox method.", ephemeral=True)

        user_data = get_user_data(user.id)
        current_level = user_data[1] if user_data else 0
        
        if current_level >= 5:
            await user.add_roles(interaction.guild.get_role(VERIFIED_ROLE_ID))
            await interaction.response.send_message("✅ You reached Level 5! You are verified.", ephemeral=True)
        else:
            await interaction.response.send_message(f"✅ **Account Checks Passed.** Chat until **Level 5** to verify. (Current Level: {current_level}).", ephemeral=True)

# ==========================================
# 🛡️ CORE EVENTS & MODERATION
# ==========================================
@bot.event
async def on_ready():
    bot.add_view(MainVerifyView())
    backup_database.start()
    print(f'✅ Logged in as {bot.user} - UI loaded, DB secured.')

@bot.event
async def on_message(message):
    if message.author.bot: return
    user_id = message.author.id
    current_time = time.time()

    # AUTOMOD: Anti-Spam
    if user_id not in spam_tracker: spam_tracker[user_id] = []
    spam_tracker[user_id].append(current_time)
    spam_tracker[user_id] = [t for t in spam_tracker[user_id] if current_time - t <= SPAM_TIMEFRAME]

    if len(spam_tracker[user_id]) > SPAM_LIMIT:
        try:
            await message.author.timeout(timedelta(minutes=TIMEOUT_MINUTES), reason="Spamming")
            await message.channel.send(f"⚠️ **{message.author.mention}** timed out for {TIMEOUT_MINUTES}m (Spam).")
            spam_tracker[user_id] = [] 
            return 
        except discord.Forbidden: pass

    # LEVELING SYSTEM
    user_data = get_user_data(user_id)
    if user_data is None:
        update_user_data(user_id, 0, 1)
        try: await message.author.send("🎉 Welcome! You just hit **Level 1**!")
        except discord.Forbidden: pass
    else:
        new_xp = user_data[0] + XP_PER_MESSAGE
        current_level = user_data[1]
        xp_needed = int(BASE_XP * (XP_MULTIPLIER ** current_level))

        if new_xp >= xp_needed:
            current_level += 1
            new_xp -= xp_needed
            try: await message.author.send(f"📈 Awesome job! You leveled up to **Level {current_level}**!")
            except discord.Forbidden: await message.channel.send(f"🎉 **{message.author.mention}** leveled up to **Level {current_level}**!")

            if current_level == 5:
                role = message.guild.get_role(VERIFIED_ROLE_ID)
                if role and role not in message.author.roles:
                    await message.author.add_roles(role)
                    await message.channel.send(embed=discord.Embed(description=f"🛡️ **{message.author.mention} hit Level 5 and was officially verified!**", color=discord.Color.green()))

        update_user_data(user_id, new_xp, current_level)

    await bot.process_commands(message)

# ==========================================
# 🛠️ OWNER / ADMIN COMMANDS
# ==========================================
@bot.command(name="setup")
@commands.has_permissions(administrator=True)
async def setup(ctx):
    channel = bot.get_channel(VERIFY_CHANNEL_ID)
    if not channel: return await ctx.send("❌ Channel not found. Check VERIFY_CHANNEL_ID.")
    
    embed = discord.Embed(title="🔒 Security Gateway", description="**Option A: Roblox Verification (Fastest)**\nLink your account automatically.\n\n**Option B: Discord Activity (Slower)**\nAccount must be 3+ weeks old with a PFP. Chat to reach Level 5.", color=discord.Color.dark_theme())
    await channel.send(embed=embed, view=MainVerifyView())
    await ctx.send("✅ System deployed.")

@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
async def kick_user(ctx, member: discord.Member, *, reason="No reason provided"):
    await member.kick(reason=reason)
    await ctx.send(f"👢 **{member.name}** kicked. Reason: *{reason}*")

@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban_user(ctx, member: discord.Member, *, reason="No reason provided"):
    await member.ban(reason=reason)
    await ctx.send(f"🔨 **{member.name}** banned. Reason: *{reason}*")

@bot.command(name="add_xp")
@commands.has_permissions(administrator=True)
async def add_xp(ctx, member: discord.Member, amount: int):
    user_data = get_user_data(member.id)
    if not user_data: return await ctx.send("❌ User not in database yet.")
    update_user_data(member.id, user_data[0] + amount, user_data[1])
    await ctx.send(f"✅ Added **{amount} XP** to {member.mention}.")

@bot.command(name="add_level")
@commands.has_permissions(administrator=True)
async def add_level(ctx, member: discord.Member, amount: int):
    user_data = get_user_data(member.id)
    if not user_data: return await ctx.send("❌ User not in database yet.")
    update_user_data(member.id, user_data[0], user_data[1] + amount)
    await ctx.send(f"✅ Added **{amount} Levels** to {member.mention}.")

bot.run(os.getenv('DISCORD_TOKEN'))
