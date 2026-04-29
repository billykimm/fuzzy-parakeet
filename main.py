import discord
from discord.ext import commands, tasks
import os
import time
import random
import aiohttp
from datetime import timedelta
from pymongo import MongoClient

# ==========================================
# ⚙️ SYSTEM SETTINGS
# ==========================================
# We use os.getenv to pull from GitHub Secrets (Security First!)
BOT_TOKEN = os.getenv('DISCORD_TOKEN')
MONGO_URI = os.getenv('MONGO_URI') 
VERIFY_CHANNEL_ID = 1498675283107250257
VERIFIED_ROLE_ID = 1483501648360771768

# Game Settings
SPAM_LIMIT = 5          
SPAM_TIMEFRAME = 5.0    
TIMEOUT_MINUTES = 5     
XP_PER_MESSAGE = 15     
BASE_XP = 100           
XP_MULTIPLIER = 1.5     

SAFE_WORDS = ["apple", "brave", "cheese", "dragon", "eagle", "flame", "ghost", "happy", "island", "jungle", "knight", "lemon", "magic", "ninja", "ocean", "panda", "quantum", "robot", "secret", "tiger", "unicorn", "velvet", "waffle", "yellow", "zebra", "pizza", "water", "music"]

# --- MEMORY STORAGE ---
spam_tracker = {}  
pending_roblox_verifications = {} 

# ==========================================
# 🗄️ DATABASE SETUP (MONGODB)
# ==========================================
cluster = MongoClient(MONGO_URI)
db = cluster["bot_database"]
collection = db["user_levels"]

def get_user_data(user_id):
    # Finds user in MongoDB or returns None
    return collection.find_one({"_id": user_id})

def update_user_data(user_id, xp, level):
    # "Upsert" logic: updates if exists, creates if not
    collection.update_one(
        {"_id": user_id},
        {"$set": {"xp": xp, "level": level}},
        upsert=True
    )

# Setup bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

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
            return await interaction.followup.send("❌ Roblox API is down.", ephemeral=True)

        if user_data["code"] in description:
            role = interaction.guild.get_role(VERIFIED_ROLE_ID)
            if role:
                await interaction.user.add_roles(role)
                await interaction.followup.send("🎉 **Verification Complete!**", ephemeral=True)
                del pending_roblox_verifications[self.discord_id] 
        else:
            await interaction.followup.send(f"❌ Code not found. Expected: `{user_data['code']}`", ephemeral=True)

class RobloxUsernameModal(discord.ui.Modal, title='Roblox Account Link'):
    username_input = discord.ui.TextInput(label='Enter exact Roblox Username:', required=True, max_length=50)

    async def on_submit(self, interaction: discord.Interaction):
        roblox_username = self.username_input.value.strip()
        secret_code = " ".join(random.choices(SAFE_WORDS, k=4)).title() 
        pending_roblox_verifications[interaction.user.id] = {"username": roblox_username, "code": secret_code}

        embed = discord.Embed(title="⏳ Almost there!", description=f"Paste this in your Roblox **About** section:\n\n`{secret_code}`", color=discord.Color.orange())
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
            return await interaction.response.send_message("❌ Account too new (3 weeks required).", ephemeral=True)
        
        data = get_user_data(user.id)
        current_level = data.get("level", 0) if data else 0
        
        if current_level >= 5:
            await user.add_roles(interaction.guild.get_role(VERIFIED_ROLE_ID))
            await interaction.response.send_message("✅ Level 5 reached! Verified.", ephemeral=True)
        else:
            await interaction.response.send_message(f"✅ Reach **Level 5** to verify. (Current: {current_level}).", ephemeral=True)

# ==========================================
# 🛡️ CORE EVENTS & MODERATION
# ==========================================
@bot.event
async def on_ready():
    bot.add_view(MainVerifyView())
    print(f'✅ Logged in as {bot.user} - Data synced to Cloud.')

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild: return
    user_id = message.author.id
    current_time = time.time()

    # ANTI-SPAM
    if user_id not in spam_tracker: spam_tracker[user_id] = []
    spam_tracker[user_id].append(current_time)
    spam_tracker[user_id] = [t for t in spam_tracker[user_id] if current_time - t <= SPAM_TIMEFRAME]

    if len(spam_tracker[user_id]) > SPAM_LIMIT:
        try:
            await message.author.timeout(timedelta(minutes=TIMEOUT_MINUTES), reason="Spamming")
            await message.channel.send(f"⚠️ **{message.author.mention}** timed out (Spam).")
            return 
        except: pass

    # LEVELING SYSTEM (MONGODB)
    data = get_user_data(user_id)
    if not data:
        update_user_data(user_id, 0, 1)
    else:
        new_xp = data["xp"] + XP_PER_MESSAGE
        lvl = data["level"]
        xp_needed = int(BASE_XP * (XP_MULTIPLIER ** lvl))

        if new_xp >= xp_needed:
            lvl += 1
            new_xp = 0
            await message.channel.send(f"📈 {message.author.mention} reached **Level {lvl}**!")
            if lvl == 5:
                role = message.guild.get_role(VERIFIED_ROLE_ID)
                if role: await message.author.add_roles(role)

        update_user_data(user_id, new_xp, lvl)

    await bot.process_commands(message)

# ==========================================
# 🛠️ ADMIN COMMANDS
# ==========================================
@bot.command()
@commands.has_permissions(administrator=True)
async def setup(ctx):
    embed = discord.Embed(title="🔒 Security Gateway", description="Choose a verification method below.", color=discord.Color.blue())
    await ctx.send(embed=embed, view=MainVerifyView())

bot.run(BOT_TOKEN)
