import os

# Get the token from the GitHub Environment Variable
BOT_TOKEN = os.getenv('DISCORD_TOKEN')

# Then at the very end
TRAINEE_MOD_ROLE_ID = 1457361860574580757
OWNER_USER_ID = 1443691889613344850

def is_staff():
    """Tier 1: Trainee Mods, Admins, and the Owner."""
    def predicate(ctx):
        if ctx.author.id == OWNER_USER_ID:
            return True
        if ctx.author.guild_permissions.administrator:
            return True
        role = ctx.guild.get_role(TRAINEE_MOD_ROLE_ID)
        if role and role in ctx.author.roles:
            return True
        return False
    return commands.check(predicate)

def is_owner_or_admin():
    """Tier 2: Only Admins and the Owner (You)."""
    def predicate(ctx):
        if ctx.author.id == OWNER_USER_ID:
            return True
        if ctx.author.guild_permissions.administrator:
            return True
        return False
    return commands.check(predicate)

# ==========================================
# 🛠️ REMASTERED ADMIN / MOD COMMANDS
# ==========================================

# --- TIER 2 COMMANDS (OWNER / ADMIN ONLY) ---
@bot.command()
@is_owner_or_admin()
async def setup(ctx):
    embed = discord.Embed(title="🔒 Security Gateway", description="Choose a verification method below.", color=discord.Color.blue())
    await ctx.send(embed=embed, view=MainVerifyView())

@bot.command(name="add_xp")
@is_owner_or_admin()
async def add_xp(ctx, member: discord.Member, amount: int):
    data = get_user_data(member.id)
    current_xp = data["xp"] if data else 0
    current_level = data["level"] if data else 1
    
    update_user_data(member.id, current_xp + amount, current_level)
    await ctx.send(f"✅ Added **{amount} XP** to {member.mention}.")

@bot.command(name="add_level")
@is_owner_or_admin()
async def add_level(ctx, member: discord.Member, amount: int):
    data = get_user_data(member.id)
    current_xp = data["xp"] if data else 0
    current_level = data["level"] if data else 1
    
    update_user_data(member.id, current_xp, current_level + amount)
    await ctx.send(f"✅ Added **{amount} Levels** to {member.mention}.")

# --- TIER 1 COMMANDS (TRAINEE MODS & UP) ---
@bot.command()
@is_staff()
async def kick(ctx, member: discord.Member, *, reason="No reason provided"):
    if member.top_role >= ctx.author.top_role and ctx.author.id != OWNER_USER_ID:
        return await ctx.send("❌ You cannot kick someone with a higher or equal role to you.")
    
    await member.kick(reason=reason)
    await ctx.send(f"👢 **{member.name}** was kicked by {ctx.author.name}. Reason: *{reason}*")

@bot.command()
@is_staff()
async def ban(ctx, member: discord.Member, *, reason="No reason provided"):
    if member.top_role >= ctx.author.top_role and ctx.author.id != OWNER_USER_ID:
        return await ctx.send("❌ You cannot ban someone with a higher or equal role to you.")
        
    await member.ban(reason=reason)
    await ctx.send(f"🔨 **{member.name}** was banned by {ctx.author.name}. Reason: *{reason}*")

@bot.command()
@is_staff()
async def warn(ctx, member: discord.Member, *, reason="No reason provided"):
    # Sends a DM to the user warning them
    try:
        await member.send(f"⚠️ **You have been warned in {ctx.guild.name}**\nReason: {reason}")
        await ctx.send(f"✅ **{member.name}** has been warned.")
    except discord.Forbidden:
        await ctx.send(f"✅ **{member.name}** has been warned. (Could not DM them, their DMs are closed).")

# ==========================================
# 🚨 ERROR HANDLER
# ==========================================
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("❌ You do not have the respected power to use this command.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing details. Example: `!kick @user reason`")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Could not find that user. Make sure you ping them correctly.")
    else:
        print(f"Command Error: {error}")

bot.run(BOT_TOKEN)
