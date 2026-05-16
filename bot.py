from __future__ import annotations
import asyncio
import contextvars
import os
import re
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
import aiohttp
import discord
from discord.ext import commands
from config_store import load_config, load_guild_config, save_config, update_config, update_guild_config
from env_loader import load_env





load_env()



INVITE_RE = re.compile(r"(discord\.gg/|discord(?:app)?\.com/invite/)", re.IGNORECASE)

LINK_RE = re.compile(r"https?://|www\.", re.IGNORECASE)

TOKEN_RE = re.compile(r"[\w-]{24,28}\.[\w-]{6,12}\.[\w-]{24,40}")

ANTI_RAID_KEYS = (

    "enabled",

    "antilink",

    "antiinvite",

    "antimention",

    "antialt",

    "antieveryone",

    "antiban",

    "antiunban",

    "antikick",

    "antibot",

    "antiwebhook",

    "antitoken",

    "antispam",

    "antithread",

    "antiemoji",

    "antisticker",

    "antiroleperm",

    "antiadmin",

    "captcha",

    "raidmode",

    "antiaddrole",

    "antidelrole",

    "antichannel",

)

ANTI_RAID_PROTECTIONS = (

    ("Antilink", "antilink"),

    ("Antiinvite", "antiinvite"),

    ("Antimention", "antimention"),

    ("Antialt", "antialt"),

    ("Antieveryone", "antieveryone"),

    ("Antiban", "antiban"),

    ("Antiunban", "antiunban"),

    ("Antikick", "antikick"),

    ("Antibot", "antibot"),

    ("Antiwebhook", "antiwebhook"),

    ("Antitoken", "antitoken"),

    ("Antispam", "antispam"),

    ("Antithread", "antithread"),

    ("Antiemoji", "antiemoji"),

    ("Antisticker", "antisticker"),

    ("Antiroleperm", "antiroleperm"),

    ("Antiadmin", "antiadmin"),

    ("Captcha", "captcha"),

    ("Raidmode", "raidmode"),

    ("Antirole", "antiaddrole"),

    ("Antidelrole", "antidelrole"),

    ("Antichannel", "antichannel"),

)

ANTI_RAID_DISPLAY_NAMES = {

    "enabled": "Anti Raid",

    "antilink": "Anti Link",

    "antiinvite": "Anti Invite",

    "antimention": "Anti Mention",

    "antialt": "Anti Alt",

    "antieveryone": "Anti Everyone",

    "antiban": "Anti Ban",

    "antiunban": "Anti Unban",

    "antikick": "Anti Kick",

    "antibot": "Anti Bot",

    "antiwebhook": "Anti Webhook",

    "antitoken": "Anti Token",

    "antispam": "Anti Spam",

    "antithread": "Anti Thread",

    "antiemoji": "Anti Emoji",

    "antisticker": "Anti Sticker",

    "antiroleperm": "Anti Role Perm",

    "antiadmin": "Anti Admin",

    "captcha": "Captcha",

    "raidmode": "Raid Mode",

    "antiaddrole": "Anti Role",

    "antidelrole": "Anti Del Role",

    "antichannel": "Anti Channel",

}

SANCTION_ACTIONS = ("ban", "kick", "derank", "none")

SANCTION_DISPLAY_NAMES = {

    "ban": "Ban",

    "kick": "Kick",

    "derank": "Derank",

    "none": "Aucune",

}



intents = discord.Intents.default()

intents.guilds = True

intents.members = True

intents.messages = True

intents.message_content = True

intents.reactions = True



def command_prefix(bot_client: commands.Bot, message: discord.Message) -> str:

    guild_id = message.guild.id if message.guild else None

    cfg = load_guild_config(guild_id)

    prefix = cfg.get("prefix") or cfg.get("prefixe") or "."

    return commands.when_mentioned_or(prefix)(bot_client, message)





bot = commands.Bot(command_prefix=command_prefix, intents=intents)

bot.remove_command("help")

join_history: dict[int, deque[datetime]] = defaultdict(deque)

message_history: dict[tuple[int, int], deque[datetime]] = defaultdict(deque)

deleted_message_cache: dict[tuple[int, int], dict] = {}

captcha_pending: dict[tuple[int, int], str] = {}

giveaway_participants: dict[int, set[int]] = defaultdict(set)

giveaway_messages: dict[int, dict] = {}

locked_channels: dict[int, list[tuple[int, discord.PermissionOverwrite]]] = defaultdict(list)

ticket_views_added = False

application_owner_ids: set[int] = set()

current_guild_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_guild_id", default=None)





def set_current_guild(guild: discord.Guild | None) -> None:

    current_guild_id.set(str(guild.id) if guild else None)





def active_config() -> dict:

    return load_guild_config(current_guild_id.get())





def update_active_config(updates: dict) -> dict:

    return update_guild_config(current_guild_id.get(), updates)





def anti_raid_config() -> dict:

    return active_config()["anti_raid"]





def sanction_config() -> dict:

    return active_config()["sanctions"]





def access_config() -> dict:

    return active_config()["access"]





def giveaway_config() -> dict:

    defaults = {

        "title": "Giveaway",

        "duration_seconds": 3600,

        "reward": "Récompense",

        "participation_message": "Vous avez été enregistré.",

        "color": "#ff5ec7",

        "image_url": "",

        "channel_id": None,

    }

    return {**defaults, **active_config().get("giveaway", {})}


def shop_config() -> dict:

    defaults = {

        "products": {},

        "stock": {},

        "orders": {},

        "reviews": [],

        "blacklist": [],

        "payment": {"paypal": "", "crypto": ""},

        "settings": {"autodeliver": False, "lowstock": {}, "color": "#ff5ec7"},

    }

    cfg = active_config().get("shop", {})

    merged = {**defaults, **cfg}

    merged["payment"] = {**defaults["payment"], **cfg.get("payment", {})}

    merged["settings"] = {**defaults["settings"], **cfg.get("settings", {})}

    return merged


def update_shop_config(values: dict) -> dict:

    return update_active_config({"shop": values})["shop"]





def global_backups() -> dict:

    config = load_config()

    backups = dict(config.get("backups", {}))

    changed = False

    for guild_config in config.get("guilds", {}).values():

        guild_backups = guild_config.pop("backups", None)

        if guild_backups:

            for name, data in guild_backups.items():

                backups.setdefault(name, data)

            changed = True

    if changed:

        config["backups"] = backups

        save_config(config)

    return backups





def replace_global_backups(backups: dict) -> dict:

    config = load_config()

    config["backups"] = backups

    for guild_config in config.get("guilds", {}).values():

        guild_config.pop("backups", None)

    save_config(config)

    return load_config().get("backups", {})





def parse_duration(value: str) -> int | None:

    match = re.fullmatch(r"\s*(\d+)\s*([smhdj]?)\s*", value.lower())

    if not match:

        return None

    amount = int(match.group(1))

    unit = match.group(2) or "s"

    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400, "j": 86400}

    return max(1, amount * multipliers[unit])





def format_duration(seconds: int) -> str:

    if seconds % 86400 == 0:

        return f"{seconds // 86400}j"

    if seconds % 3600 == 0:

        return f"{seconds // 3600}h"

    if seconds % 60 == 0:

        return f"{seconds // 60}m"

    return f"{seconds}s"





def normalize_user_id(value: str) -> int | None:

    match = re.search(r"\d{15,25}", str(value))

    return int(match.group(0)) if match else None





def is_owner_id(user_id: int) -> bool:

    return str(user_id) in {str(item) for item in access_config().get("owners", [])}





def is_buyer_id(user_id: int) -> bool:

    return str(user_id) in {str(item) for item in access_config().get("buyers", [])}





async def is_application_owner_id(user_id: int) -> bool:

    if not application_owner_ids:

        try:

            info = await bot.application_info()

        except discord.DiscordException:

            return False



        if info.owner:

            application_owner_ids.add(info.owner.id)



        team = getattr(info, "team", None)

        for member in getattr(team, "members", []) or []:

            member_user = getattr(member, "user", member)

            member_id = getattr(member_user, "id", None)

            if member_id:

                application_owner_ids.add(member_id)



    return user_id in application_owner_ids





async def has_owner_access(member: discord.Member) -> bool:

    if is_buyer_id(member.id):

        return True

    if is_owner_id(member.id):

        return True

    if await is_application_owner_id(member.id):

        return True

    owners = access_config().get("owners", [])

    if not owners:

        return member.id == member.guild.owner_id or member.guild_permissions.administrator

    return False





async def has_buyer_access(member: discord.Member) -> bool:

    if is_buyer_id(member.id):

        return True

    if await is_application_owner_id(member.id):

        return True

    buyers = access_config().get("buyers", [])

    owners = access_config().get("owners", [])

    if not buyers and not owners:

        return member.id == member.guild.owner_id or member.guild_permissions.administrator

    return False





async def is_guard_bypassed(actor: discord.abc.User | None, guild: discord.Guild | None = None) -> bool:

    if not actor:

        return False

    if bot.user and actor.id == bot.user.id:

        return True

    if is_buyer_id(actor.id) or is_owner_id(actor.id) or is_whitelisted_id(actor.id):

        return True

    member = actor if isinstance(actor, discord.Member) else guild.get_member(actor.id) if guild else None

    if has_whitelist_role(member):

        return True

    return await is_application_owner_id(actor.id)





def is_whitelisted_id(user_id: int) -> bool:

    return str(user_id) in {str(item) for item in access_config().get("whitelist", [])}





def whitelist_role_ids() -> set[int]:

    return {int(item) for item in access_config().get("whitelist_roles", []) if str(item).isdigit()}





def has_whitelist_role(member: discord.Member | None) -> bool:

    if not member:

        return False

    return bool({role.id for role in member.roles}.intersection(whitelist_role_ids()))





def is_blacklisted_id(user_id: int) -> bool:

    return str(user_id) in {str(item) for item in access_config().get("blacklist", [])}





def clean_status_embed(title: str, description: str, color: discord.Color | None = None) -> discord.Embed:

    return discord.Embed(title=title, description=description, color=color or discord.Color.blurple())





def clean_emoji_name(value: str) -> str:

    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", value.strip())

    cleaned = re.sub(r"_+", "_", cleaned).strip("_")

    return (cleaned or "emoji")[:32]





def normalize_command_permission_name(command_name: str) -> str:

    return command_name.strip().lower().removeprefix(".")





def command_role_ids(command_name: str) -> set[int]:

    command_name = normalize_command_permission_name(command_name)

    permissions = access_config().get("command_permissions", {})

    return {int(item) for item in permissions.get(command_name, []) if str(item).isdigit()}





def has_command_role(member: discord.Member, command_name: str) -> bool:

    return bool({role.id for role in member.roles}.intersection(command_role_ids(command_name)))





def can_use(command_name: str):

    async def predicate(ctx: commands.Context) -> bool:

        if not ctx.guild or not isinstance(ctx.author, discord.Member):

            return False

        return await has_owner_access(ctx.author) or has_command_role(ctx.author, command_name)



    return commands.check(predicate)





PUBLIC_COMMANDS: set[str] = set()



@bot.check

async def owner_only_commands(ctx: commands.Context) -> bool:

    set_current_guild(ctx.guild)

    if not ctx.guild or not isinstance(ctx.author, discord.Member):

        return False

    command_name = ctx.command.name if ctx.command else ""

    if command_name in PUBLIC_COMMANDS:

        return True

    return await has_owner_access(ctx.author) or has_command_role(ctx.author, command_name)





@bot.before_invoke

async def set_command_guild_context(ctx: commands.Context) -> None:

    set_current_guild(ctx.guild)





async def resolve_member(guild: discord.Guild, value: str) -> discord.Member | None:

    user_id = normalize_user_id(value)

    if not user_id:

        return None

    member = guild.get_member(user_id)

    if member:

        return member

    try:

        return await guild.fetch_member(user_id)

    except discord.HTTPException:

        return None





def resolve_role(guild: discord.Guild, value: str) -> discord.Role | None:

    role_id = normalize_user_id(value)

    if role_id:

        return guild.get_role(role_id)



    cleaned = value.strip()

    lowered = cleaned.lower()

    return next((role for role in guild.roles if role.name.lower() == lowered), None)





def resolve_text_channel(guild: discord.Guild, value: str) -> discord.TextChannel | None:

    channel_id = normalize_user_id(value)

    channel = guild.get_channel(channel_id) if channel_id else None

    if isinstance(channel, discord.TextChannel):

        return channel

    lowered = value.strip().lstrip("#").lower()

    return next((item for item in guild.text_channels if item.name.lower() == lowered), None)





def resolve_category(guild: discord.Guild, value: str | None) -> discord.CategoryChannel | None:

    if not value:

        return None

    category_id = normalize_user_id(value)

    category = guild.get_channel(category_id) if category_id else None

    if isinstance(category, discord.CategoryChannel):

        return category

    lowered = value.strip().lower()

    return next((item for item in guild.categories if item.name.lower() == lowered), None)





def can_assign_role(guild: discord.Guild, role: discord.Role) -> tuple[bool, str]:

    bot_member = guild.me

    if not bot_member:

        return False, "Bot introuvable dans le serveur."

    if role == guild.default_role:

        return False, "Je ne peux pas attribuer @everyone."

    if role.managed:

        return False, "Je ne peux pas attribuer un rôle géré par une intégration."

    if role >= bot_member.top_role:

        return False, "Ce rôle est au-dessus ou au même niveau que mon rôle. Mets mon rôle plus haut."

    if not bot_member.guild_permissions.manage_roles:

        return False, "Il me manque la permission Gérer les rôles."

    return True, ""





def ticket_config() -> dict:

    return active_config()["tickets"]





def server_settings_config() -> dict:

    defaults = {

        "join_role_ids": [],

        "join_channel_id": None,

        "join_embed_enabled": False,

        "join_embed_color": "#ff5ec7",

        "leave_channel_id": None,

        "leave_embed_enabled": False,

        "leave_embed_color": "#ff5ec7",

        "leave_message": "{member} vient de quitter le serveur. Nous sommes désormais {member_count}.",

        "ghost_join_role_id": None,

        "ghost_join_channel_id": None,

        "join_message": "{member} vient de nous rejoindre pour la {join_count}e fois, son compte a été créé {user_created_at}. Il/Elle a été invité(e) par {inviter} (qui obtient {invite_count} invitations). Nous sommes désormais {member_count} !",

    }

    settings = active_config().get("server_settings", {})

    return {**defaults, **settings}





def update_server_settings(values: dict) -> dict:

    return update_active_config({"server_settings": values})["server_settings"]





def react_role_config() -> dict:

    defaults = {

        "channel_id": None,

        "message_id": None,

        "role_id": None,

        "emoji": "",

        "title": "Vérification",

        "description": "Réagis avec {emoji} pour obtenir le rôle et accéder au serveur.",

        "color": "#ff5ec7",

    }

    return {**defaults, **active_config().get("react_role", {})}





def update_react_role_config(values: dict) -> dict:

    return update_active_config({"react_role": values})["react_role"]





def update_ticket_config(values: dict) -> dict:

    return update_active_config({"tickets": values})["tickets"]





def bot_profile_config() -> dict:

    return active_config()["bot_profile"]





def parse_hex_color(value: str) -> discord.Color:

    cleaned = value.strip().removeprefix("#")

    try:

        return discord.Color(int(cleaned, 16))

    except ValueError:

        return discord.Color.blurple()





def make_configured_embed() -> discord.Embed:

    cfg = active_config()["embed"]

    embed = discord.Embed(

        title=cfg.get("title") or "Annonce",

        description=cfg.get("description") or "",

        color=parse_hex_color(cfg.get("color") or "#5865f2"),

        url=cfg.get("url") or None,

        timestamp=datetime.now(timezone.utc) if cfg.get("timestamp") else None,

    )

    if cfg.get("footer"):

        embed.set_footer(text=cfg["footer"])

    if cfg.get("thumbnail"):

        embed.set_thumbnail(url=cfg["thumbnail"])

    if cfg.get("image"):

        embed.set_image(url=cfg["image"])

    if cfg.get("author"):

        embed.set_author(name=cfg["author"])

    for field in cfg.get("fields", [])[:25]:

        embed.add_field(

            name=field.get("name") or "Field",

            value=field.get("value") or "Valeur",

            inline=bool(field.get("inline", False)),

        )

    return embed





def update_embed_config(values: dict) -> dict:

    return update_active_config({"embed": values})["embed"]





def make_embed_view() -> discord.ui.View | None:

    cfg = active_config()["embed"]

    label = (cfg.get("button_label") or "").strip()

    url = (cfg.get("button_url") or "").strip()

    if not label or not url:

        return None

    view = discord.ui.View(timeout=None)

    view.add_item(discord.ui.Button(label=label[:80], url=url))

    return view





async def punish_message_spam(message: discord.Message, reason: str) -> None:

    try:

        await message.delete()

    except discord.Forbidden:

        pass

    await log_event(message.guild, f"Anti-raid: action contre {message.author} ({reason}).")





async def derank_member(member: discord.Member, reason: str) -> int:

    removable = [

        role

        for role in member.roles

        if role != member.guild.default_role and role < member.guild.me.top_role and not role.managed

    ]

    if not removable:

        return 0

    await member.remove_roles(*removable, reason=reason)

    return len(removable)





async def apply_sanction(guild: discord.Guild, actor: discord.abc.User | None, guard_key: str, reason: str) -> None:

    if not actor or await is_guard_bypassed(actor, guild):

        return



    action = sanction_config().get(guard_key, "derank")

    member = guild.get_member(actor.id)



    try:

        if action == "ban":

            await guild.ban(actor, reason=reason, delete_message_seconds=0)

            await log_guard(guild, guard_key, f"sanction ban appliquée à {actor}", actor)

        elif action == "kick" and member:

            await member.kick(reason=reason)

            await log_guard(guild, guard_key, f"sanction kick appliquée à {actor}", actor)

        elif action == "derank" and member:

            if is_whitelisted_id(member.id) or has_whitelist_role(member):

                await log_guard(guild, guard_key, f"{actor} est whitelist, derank annulé", actor)

                return

            count = await derank_member(member, reason)

            await log_guard(guild, guard_key, f"sanction derank appliquée à {actor} ({count} rôles retirés)", actor)

        elif action == "none":

            await log_guard(guild, guard_key, f"aucune sanction automatique pour {actor}", actor)

    except discord.Forbidden:

        await log_guard(guild, guard_key, f"sanction {action} impossible, permissions insuffisantes pour {actor}", actor)

    except discord.HTTPException as error:

        await log_guard(guild, guard_key, f"sanction {action} échouée pour {actor}: {error}", actor)





async def audit_user(guild: discord.Guild, action: discord.AuditLogAction, target_id: int | None = None) -> discord.User | discord.Member | None:

    try:

        async for entry in guild.audit_logs(limit=6, action=action):

            if target_id is None or getattr(entry.target, "id", None) == target_id:

                return entry.user

    except discord.Forbidden:

        return None

    return None





async def log_guard(guild: discord.Guild, guard: str, detail: str, actor: discord.abc.User | None = None) -> None:

    actor_text = f" par {actor}" if actor else ""

    await log_event(guild, f"{guard}: {detail}{actor_text}.")





async def enable_lockdown_for_guild(guild: discord.Guild, reason: str) -> int:

    role = guild.default_role

    locked_channels[guild.id].clear()

    changed = 0



    for channel in guild.text_channels:

        overwrite = channel.overwrites_for(role)

        locked_channels[guild.id].append((channel.id, overwrite))

        overwrite.send_messages = False

        try:

            await channel.set_permissions(role, overwrite=overwrite, reason=reason)

            changed += 1

        except discord.Forbidden:

            continue

        await asyncio.sleep(0.2)



    return changed





async def disable_lockdown_for_guild(guild: discord.Guild, reason: str) -> int:

    saved = locked_channels.get(guild.id, [])

    changed = 0



    for channel_id, overwrite in saved:

        channel = guild.get_channel(channel_id)

        if not isinstance(channel, discord.TextChannel):

            continue

        try:

            await channel.set_permissions(guild.default_role, overwrite=overwrite, reason=reason)

            changed += 1

        except discord.Forbidden:

            continue

        await asyncio.sleep(0.2)



    locked_channels[guild.id].clear()

    return changed





def copy_overwrite(overwrite: discord.PermissionOverwrite) -> discord.PermissionOverwrite:

    allow, deny = overwrite.pair()

    return discord.PermissionOverwrite.from_pair(allow, deny)





async def log_event(guild: discord.Guild, message: str) -> None:

    cfg = anti_raid_config()

    channel_id = cfg.get("log_channel_id")

    channel = guild.get_channel(int(channel_id)) if channel_id else None

    if isinstance(channel, discord.TextChannel):

        await channel.send(message)





def is_admin():

    async def predicate(ctx: commands.Context) -> bool:

        return bool(ctx.guild and isinstance(ctx.author, discord.Member) and await has_owner_access(ctx.author))



    return commands.check(predicate)





def is_buyer():

    async def predicate(ctx: commands.Context) -> bool:

        return bool(ctx.guild and isinstance(ctx.author, discord.Member) and await has_buyer_access(ctx.author))



    return commands.check(predicate)





def make_activity() -> discord.BaseActivity | None:

    cfg = bot_profile_config()

    text = (cfg.get("activity_text") or "").strip()

    if not text:

        return None



    activity_type = cfg.get("activity_type", "watching")

    if activity_type == "playing":

        return discord.Game(name=text)

    if activity_type == "listening":

        return discord.Activity(type=discord.ActivityType.listening, name=text)

    if activity_type == "competing":

        return discord.Activity(type=discord.ActivityType.competing, name=text)

    return discord.Activity(type=discord.ActivityType.watching, name=text)





def make_status() -> discord.Status:

    value = bot_profile_config().get("status", "online")

    return {

        "idle": discord.Status.idle,

        "dnd": discord.Status.dnd,

        "invisible": discord.Status.invisible,

    }.get(value, discord.Status.online)





async def apply_presence() -> None:

    await bot.change_presence(status=make_status(), activity=make_activity())





async def fetch_image_bytes(url: str) -> bytes:

    async with aiohttp.ClientSession() as session:

        async with session.get(url, timeout=15) as response:

            response.raise_for_status()

            content_type = response.headers.get("content-type", "")

            if not content_type.startswith("image/"):

                raise ValueError("L'URL ne pointe pas vers une image.")

            return await response.read()





def emoji_url_from_value(value: str) -> str | None:

    custom = re.fullmatch(r"<(a?):([A-Za-z0-9_]{2,32}):(\d{15,25})>", value.strip())

    if custom:

        ext = "gif" if custom.group(1) else "png"

        return f"https://cdn.discordapp.com/emojis/{custom.group(3)}.{ext}"

    if re.match(r"https?://", value.strip(), re.IGNORECASE):

        return value.strip()

    return None





def custom_emoji_name(value: str) -> str | None:

    custom = re.fullmatch(r"<a?:([A-Za-z0-9_]{2,32}):\d{15,25}>", value.strip())

    return custom.group(1) if custom else None





def unicode_emoji_asset(value: str) -> tuple[str, str] | None:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 12:
        return None
    codepoints = []
    for char in cleaned:
        point = ord(char)
        if point == 0xFE0F:
            continue
        if point < 0x2000:
            return None
        codepoints.append(f"{point:x}")
    if not codepoints:
        return None
    key = "-".join(codepoints)
    return f"emoji_{key.replace('-', '_')}"[:32], f"https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/{key}.png"


async def apply_bot_profile() -> list[str]:

    cfg = bot_profile_config()

    changes: list[str] = []



    if not bot.user:

        return ["Bot pas encore connecte."]



    name = (cfg.get("name") or "").strip()

    avatar_url = (cfg.get("avatar_url") or "").strip()

    avatar_bytes = await fetch_image_bytes(avatar_url) if avatar_url else None



    if name or avatar_bytes:

        await bot.user.edit(username=name or bot.user.name, avatar=avatar_bytes)

        if name:

            changes.append("nom")

        if avatar_bytes:

            changes.append("avatar")



    bot.add_view(GiveawayJoinView())

    await apply_presence()

    changes.append("presence")

    return changes





def role_ids_from_config(values: list[str]) -> set[int]:

    ids = set()

    for value in values or []:

        parsed = normalize_user_id(value)

        if parsed:

            ids.add(parsed)

    return ids





def has_ticket_access(member: discord.Member, cfg: dict) -> tuple[bool, str]:

    member_role_ids = {role.id for role in member.roles}

    required = role_ids_from_config(cfg.get("required_role_ids", []))

    forbidden = role_ids_from_config(cfg.get("forbidden_role_ids", []))

    if required and not member_role_ids.intersection(required):

        return False, "Tu n'as pas le rôle requis pour ouvrir un ticket."

    if forbidden and member_role_ids.intersection(forbidden):

        return False, "Tu ne peux pas ouvrir de ticket avec un rôle interdit."

    return True, ""





def ticket_staff_role_ids(cfg: dict, option: dict | None = None) -> set[int]:

    ids = set()

    if cfg.get("support_role_id"):

        parsed = normalize_user_id(str(cfg.get("support_role_id")))

        if parsed:

            ids.add(parsed)

    ids.update(role_ids_from_config(cfg.get("required_role_ids", [])))

    ids.update(role_ids_from_config((option or {}).get("access_role_ids", [])))

    return ids





def is_ticket_staff(member: discord.Member, cfg: dict | None = None, option: dict | None = None) -> bool:

    if member.guild_permissions.manage_channels:

        return True

    config = cfg or ticket_config()

    member_role_ids = {role.id for role in member.roles}

    return bool(member_role_ids.intersection(ticket_staff_role_ids(config, option)))





def open_ticket_count(guild: discord.Guild, member_id: int) -> int:

    marker = f"ticket_owner:{member_id}"

    return sum(1 for channel in guild.text_channels if channel.topic and marker in channel.topic)





def ticket_options(cfg: dict) -> list[dict[str, str]]:

    options = cfg.get("options") or []

    cleaned = []

    for option in options[:25]:

        label = str(option.get("label", "")).strip()[:100]

        if not label:

            continue

        cleaned.append(

            {

                "label": label,

                "emoji": str(option.get("emoji", "")).strip()[:40],

                "description": str(option.get("description", "")).strip()[:100],

            }

        )

    return cleaned





async def create_ticket_channel(

    guild: discord.Guild,

    opener: discord.Member,

    option_label: str | None = None,

) -> discord.TextChannel:

    cfg = ticket_config()

    selected_option = None

    if option_label:

        selected_option = next((option for option in cfg.get("options", []) if option.get("label") == option_label), None)

    category_id = selected_option.get("category_id") if selected_option else cfg.get("category_id")

    category = guild.get_channel(int(category_id)) if category_id else None

    support_role = guild.get_role(int(cfg["support_role_id"])) if cfg.get("support_role_id") else None

    if not isinstance(category, discord.CategoryChannel):

        category_name = cfg.get("category_name") or "Tickets"

        category = discord.utils.get(guild.categories, name=category_name)

        if category is None:

            category = await guild.create_category(category_name, reason="Categorie tickets automatique")



    overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {

        guild.default_role: discord.PermissionOverwrite(view_channel=False),

        opener: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),

    }

    bot_member = guild.me or (guild.get_member(bot.user.id) if bot.user else None)

    if bot_member:

        overwrites[bot_member] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)

    if support_role:

        overwrites[support_role] = discord.PermissionOverwrite(

            view_channel=True,

            send_messages=True,

            read_message_history=True,

        )

    for role_id in role_ids_from_config((selected_option or {}).get("access_role_ids", [])):

        role = guild.get_role(role_id)

        if role:

            overwrites[role] = discord.PermissionOverwrite(

                view_channel=True,

                send_messages=True,

                read_message_history=True,

            )



    raw_name = cfg.get("channel_name_format") or "ticket-{user}"

    option_slug = re.sub(r"[^a-zA-Z0-9-]", "-", (option_label or "support").lower()).strip("-")[:30]

    name = raw_name.format(user=opener.name, id=opener.id, option=option_slug).lower().replace(" ", "-")[:90]

    channel = await guild.create_text_channel(

        name=name,

        category=category if isinstance(category, discord.CategoryChannel) else None,

        overwrites=overwrites,

        topic=f"ticket_owner:{opener.id} option:{option_label or 'Support'}",

        reason=f"Ticket ouvert par {opener}",

    )

    embed = discord.Embed(

        title="Ticket ouvert",

        description=(selected_option or {}).get("open_message") or cfg["welcome_message"],

        color=parse_hex_color(cfg.get("embed_color") or "#ff5ec7"),

    )

    manage_view = TicketManageView()

    mention_ids = role_ids_from_config((selected_option or {}).get("mentioned_role_ids", []))

    mention_text = " ".join(f"<@&{role_id}>" for role_id in mention_ids)

    if mention_text:

        embed.add_field(name="Mention", value=mention_text, inline=False)

    allowed_mentions = discord.AllowedMentions(users=True, roles=True, everyone=False)

    content = opener.mention

    await channel.send(

        content=content,

        embed=embed,

        view=manage_view if manage_view.children else None,

        allowed_mentions=allowed_mentions,

    )

    return channel





async def open_ticket_from_interaction(

    interaction: discord.Interaction,

    option_label: str | None = None,

) -> None:

    if not interaction.guild or not isinstance(interaction.user, discord.Member):

        await interaction.response.send_message("Impossible d'ouvrir un ticket ici.", ephemeral=True)

        return

    cfg = ticket_config()

    if not cfg.get("enabled"):

        await interaction.response.send_message("Les tickets sont desactives.", ephemeral=True)

        return

    allowed, message = has_ticket_access(interaction.user, cfg)

    if not allowed:

        await interaction.response.send_message(message, ephemeral=True)

        return

    await interaction.response.defer(ephemeral=True, thinking=True)

    try:

        channel = await create_ticket_channel(interaction.guild, interaction.user, option_label)

    except discord.Forbidden:

        await interaction.followup.send("Je n'ai pas la permission de creer le ticket.", ephemeral=True)

        return

    except discord.HTTPException as error:

        await interaction.followup.send(f"Impossible de creer le ticket: `{error}`", ephemeral=True)

        return

    await interaction.followup.send(f"Ticket cree: {channel.mention}", ephemeral=True)

    if interaction.message:

        try:

            await interaction.message.edit(view=TicketPanel())

        except discord.HTTPException:

            pass





class TicketOptionSelect(discord.ui.Select):

    def __init__(self) -> None:

        cfg = ticket_config()

        cleaned_options = ticket_options(cfg)

        if not cleaned_options:

            cleaned_options = [{"label": "Option non configurée", "emoji": "", "description": "Ajoute une option avec .ticket"}]

        options = [

            discord.SelectOption(

                label=option["label"],

                value=option["label"],

                description=option["description"] or None,

                emoji=option["emoji"] or None,

            )

            for option in cleaned_options

        ]

        super().__init__(

            placeholder="Choisis une option",

            min_values=1,

            max_values=1,

            options=options,

            custom_id="ticket:select",

        )



    async def callback(self, interaction: discord.Interaction) -> None:

        set_current_guild(interaction.guild)

        await open_ticket_from_interaction(interaction, self.values[0])





class TicketCreateButton(discord.ui.Button):

    def __init__(self) -> None:

        super().__init__(label="Ouvrir un ticket", style=discord.ButtonStyle.green, custom_id="ticket:create")



    async def callback(self, interaction: discord.Interaction) -> None:

        set_current_guild(interaction.guild)

        await open_ticket_from_interaction(interaction)





class TicketPanel(discord.ui.View):

    def __init__(self) -> None:

        super().__init__(timeout=None)

        if ticket_config().get("panel_type") == "selector":

            self.add_item(TicketOptionSelect())

        else:

            self.add_item(TicketCreateButton())





class TicketManageView(discord.ui.View):

    def __init__(self) -> None:

        super().__init__(timeout=None)

        cfg = ticket_config()

        if cfg.get("claim_button", True):

            self.add_item(TicketClaimButton())

        if cfg.get("close_button", True):

            self.add_item(TicketCloseButton())





class TicketClaimButton(discord.ui.Button):

    def __init__(self) -> None:

        super().__init__(label="Claim", style=discord.ButtonStyle.blurple, custom_id="ticket:claim")



    async def callback(self, interaction: discord.Interaction) -> None:

        set_current_guild(interaction.guild)

        if not interaction.guild or not isinstance(interaction.user, discord.Member):

            await interaction.response.send_message("Impossible ici.", ephemeral=True)

            return

        if not interaction.channel or not interaction.channel.name.startswith("ticket-"):

            await interaction.response.send_message("Ce bouton doit etre utilise dans un ticket.", ephemeral=True)

            return

        option_label = ""

        if interaction.channel.topic:

            match = re.search(r"option:(.+)$", interaction.channel.topic)

            option_label = match.group(1) if match else ""

        cfg = ticket_config()

        selected_option = next((option for option in cfg.get("options", []) if option.get("label") == option_label), None)

        if not is_ticket_staff(interaction.user, cfg, selected_option):

            await interaction.response.send_message("Tu n'as pas la permission de claim ce ticket.", ephemeral=True)

            return



        embed = discord.Embed(

            title="Ticket pris en charge",

            description=f"{interaction.user.mention} s'occupe de ce ticket.",

            color=discord.Color.blurple(),

        )

        await interaction.response.send_message(embed=embed)





class TicketCloseButton(discord.ui.Button):

    def __init__(self) -> None:

        super().__init__(label="Fermer le ticket", style=discord.ButtonStyle.red, custom_id="ticket:close")



    async def callback(self, interaction: discord.Interaction) -> None:

        set_current_guild(interaction.guild)

        if not interaction.guild or not isinstance(interaction.user, discord.Member):

            await interaction.response.send_message("Impossible ici.", ephemeral=True)

            return

        if not interaction.channel or not interaction.channel.name.startswith("ticket-"):

            await interaction.response.send_message("Ce bouton doit etre utilise dans un ticket.", ephemeral=True)

            return

        option_label = ""

        if interaction.channel.topic:

            match = re.search(r"option:(.+)$", interaction.channel.topic)

            option_label = match.group(1) if match else ""

        cfg = ticket_config()

        selected_option = next((option for option in cfg.get("options", []) if option.get("label") == option_label), None)

        opener_id = normalize_user_id(interaction.channel.topic or "")

        if not is_ticket_staff(interaction.user, cfg, selected_option) and interaction.user.id != opener_id:

            await interaction.response.send_message("Tu n'as pas la permission de fermer ce ticket.", ephemeral=True)

            return



        await interaction.response.send_message("Fermeture du ticket dans 5 secondes.")

        await asyncio.sleep(5)

        if not ticket_config().get("auto_delete_closed", True):

            await interaction.channel.edit(name=f"closed-{interaction.channel.name[:80]}")

            return

        try:

            await interaction.channel.delete(reason=f"Ticket ferme par {interaction.user}")

        except discord.Forbidden:

            await interaction.followup.send("Je n'ai pas la permission de supprimer ce salon.", ephemeral=True)

HELP_SECTIONS = {
    "antiraid": (
        "Anti-raid",
        "**.antiraid** - configure les protections et les sanctions anti-raid\n"
        "**.antilink <on/off>** - bloque les liens\n"
        "**.antiinvite <on/off>** - bloque les invitations Discord\n"
        "**.antimention <nombre>** - bloque les messages avec trop de mentions\n"
        "**.antialt <jours>** - bloque les comptes trop récents\n"
        "**.antieveryone <on/off>** - bloque @everyone et @here\n"
        "**.antiban <on/off>** - annule les bans suspects\n"
        "**.antiunban <on/off>** - annule les unbans suspects\n"
        "**.antikick <on/off>** - détecte les kicks suspects\n"
        "**.antibot <on/off>** - bloque les bots ajoutés sans autorisation\n"
        "**.antiwebhook <on/off>** - bloque les webhooks suspects\n"
        "**.antitoken <on/off>** - supprime les messages qui ressemblent à des tokens\n"
        "**.antispam <on/off>** - bloque le spam de messages\n"
        "**.antithread <on/off>** - bloque les threads créés sans autorisation\n"
        "**.antiemoji <on/off>** - bloque les emojis créés sans autorisation\n"
        "**.antisticker <on/off>** - bloque les stickers créés sans autorisation\n"
        "**.antiroleperm <on/off>** - bloque les permissions dangereuses ajoutées aux rôles\n"
        "**.antiadmin <on/off>** - bloque la permission administrateur ajoutée aux rôles\n"
        "**.raidmode <on/off>** - active le mode raid renforcé\n"
        "**.antirole <on/off>** - protège les rôles créés\n"
        "**.antidelrole <on/off>** - restaure les rôles supprimés\n"
        "**.antichannel <on/off>** - protège les salons",
    ),
    "tickets": (
        "Tickets",
        "**.ticket** - ouvre la configuration interactive des tickets\n"
        "**.close** - ferme le ticket actuel\n"
        "**.rename <nom>** - renomme le salon ticket\n"
        "**.adduser <@membre>** - ajoute quelqu'un au ticket\n"
        "**.deluser <@membre>** - retire quelqu'un du ticket",
    ),
    "giveaway": (
        "Giveaway",
        "**.giveaway** - ouvre le menu interactif de giveaway\n"
        "**.giveaway reroll <message_id>** - retire un gagnant du giveaway",
    ),
    "shop": (
        "Vouch",
        "**.setup vouch** - configure le rôle qui peut utiliser .vouch\n"
        "**.vouch <message>** - poste un vouch en embed bleu foncé",
    ),
    "backup": (
        "Backup",
        "**.backup** - ouvre le menu interactif de backup\n"
        "**.backup create** - sauvegarde les rôles, catégories et salons\n"
        "**.backup load** - remplace le serveur avec la backup choisie\n"
        "**.backuplist** - affiche les backups disponibles",
    ),
    "server_settings": (
        "Serveur Settings",
        "**.joinsettings** - affiche la configuration des arrivées\n"
        "**.ghostjoin <@role/id> <#salon/id>** - configure le ping ghost join\n"
        "**.embed** - ouvre la configuration interactive de l'embed\n"
        "**.embed test** - teste l'embed dans le salon actuel\n"
        "**.captcha** - ouvre la configuration interactive du captcha\n"
        "**.giveaway** - ouvre le menu interactif de giveaway\n"
        "**.backup** - ouvre le menu interactif de backup",
    ),
    "server_management": (
        "Gestion du serveur",
        "**.permcheck** - vérifie les permissions importantes du bot\n"
        "**.roleinfo <@role/id/nom>** - affiche les infos d'un rôle\n"
        "**.rolecolor <@role/id/nom> <#hex>** - change la couleur d'un rôle\n"
        "**.mentionable <@role/id/nom> <on/off>** - rend un rôle mentionnable ou non\n"
        "**.channelinfo [#salon/id]** - affiche les infos d'un salon\n"
        "**.categoryinfo [catégorie/id]** - affiche les infos d'une catégorie\n"
        "**.rolemembers <@role/id/nom>** - liste les membres d'un rôle\n"
        "**.serveur** - génère une structure de serveur avec une description\n"
        "**.createrole <nom>** - crée un rôle\n"
        "**.createchannel <nom>** - crée un salon texte\n"
        "**.renamechannel <nom>** - renomme le salon actuel\n"
        "**.massiverole add <@role/id/nom>** - donne un rôle à tous les membres\n"
        "**.syncperms** - synchronise le salon avec sa catégorie\n"
        "**.lockcategory [catégorie/id]** - verrouille une catégorie\n"
        "**.unlockcategory [catégorie/id]** - déverrouille une catégorie\n"
        "**.categorylock <catégorie/id>** - verrouille une catégorie\n"
        "**.categoryunlock <catégorie/id>** - déverrouille une catégorie\n"
        "**.delcategory <catégorie/id>** - supprime une catégorie et ses salons\n"
        "**.renamecategory <catégorie/id> <nom>** - renomme une catégorie",
    ),
    "moderation": (
        "Modération",
        "**.ban <@membre> [raison]** - bannit un membre\n"
        "**.banlist** - affiche la liste des bannis\n"
        "**.baninfo <id>** - affiche les infos d'un ban\n"
        "**.unban <id>** - débannit un utilisateur par ID\n"
        "**.unbanall** - débannit tous les utilisateurs bannis\n"
        "**.kick <@membre> [raison]** - expulse un membre\n"
        "**.tempban <@membre> <durée> [raison]** - bannit temporairement un membre\n"
        "**.tempmute <@membre> <durée> [raison]** - mute temporairement un membre\n"
        "**.clear <nombre>** - supprime des messages\n"
        "**.snipe** - affiche le dernier message supprimé du salon\n"
        "**.lock** - verrouille les salons texte\n"
        "**.unlock** - restaure les salons texte verrouillés\n"
        "**.lockall** - verrouille tous les salons texte\n"
        "**.unlockall** - déverrouille tous les salons texte\n"
        "**.slowmode <secondes>** - règle le slowmode du salon\n"
        "**.nuke** - recrée le salon actuel\n"
        "**.temprole <@membre> <@role> <durée>** - donne un rôle temporaire\n"
        "**.userinfo [@membre]** - infos utilisateur\n"
        "**.serverinfo** - infos serveur\n"
        "**.bl <id/@membre>** - blacklist et ban\n"
        "**.unbl <id/@membre>** - retire de la blacklist\n"
        "**.bllist** - affiche les utilisateurs blacklistés",
    ),
    "owner": (
        "Buyer & Owner & WL",
        "**Buyer**\n--------------------\n"
        "**.buyer <id/@membre>** - ajoute un buyer bot\n"
        "**.unbuyer <id/@membre>** - retire un buyer bot\n"
        "**.buyerlist** - affiche les buyers\n\n"
        "**Owner**\n--------------------\n"
        "**.owner <id/@membre>** - ajoute un owner bot\n"
        "**.unowner <id/@membre>** - retire un owner bot\n"
        "**.ownerlist** - affiche les owners\n\n"
        "**WL**\n--------------------\n"
        "**.wl <id/@membre>** - ajoute en whitelist anti-derank\n"
        "**.unwl <id/@membre>** - retire de la whitelist\n"
        "**.wllist** - affiche les personnes whitelist\n"
        "**.wlrole <@role/id/nom>** - whitelist tous les membres avec ce rôle\n"
        "**.unwlrole <@role/id/nom>** - retire un rôle whitelist\n"
        "**.wlrolelist** - affiche les rôles whitelist",
    ),
    "setperm": (
        "Setperm / Unsetperm",
        "**.setperm <commande> <@role>** - autorise un rôle de façon permanente\n"
        "**.unsetperm <commande> <@role>** - retire une autorisation\n"
        "**.addrole <@membre/id> <@role/id/nom>** - ajoute un rôle\n"
        "**.delrole <@membre/id> <@role/id/nom>** - retire un rôle\n"
        "**.rename <@role/id> <nom>** - renomme un rôle",
    ),
    "bot": (
        "Bot",
        "**.bot info** - affiche les infos du bot\n"
        "**.botname <nom>** - change le nom du bot\n"
        "**.botpic <url>** - change la photo du bot\n"
        "**.emoji <emoji>** - crée cet emoji sur le serveur\n"
        "**.say <message>** - fait parler le bot\n"
        "**.avatar [@membre]** - affiche l'avatar\n"
        "**.banner [@membre]** - affiche la bannière\n"
        "**.watch <phrase>** - met l'activité Regarde\n"
        "**.listen <phrase>** - met l'activité Écoute",
    ),
    "logs": (
        "Logs",
        "**.autologs** - crée automatiquement les salons de logs\n"
        "**.logconfig** - ouvre le menu de configuration des logs",
    ),
}


HELP_EMOJIS = {
    "antiraid": None,
    "tickets": None,
    "giveaway": None,
    "shop": None,
    "backup": None,
    "server_settings": None,
    "server_management": None,
    "moderation": None,
    "owner": None,
    "setperm": None,
    "bot": None,
    "logs": None,
}


COMMAND_EMOJIS = {
    ".antiraid": "🛡️", ".antilink": "🔗", ".antieveryone": "📢", ".antiban": "🔨",
    ".antiunban": "↩️", ".antikick": "🥾", ".antibot": "🤖", ".antiwebhook": "🪝",
    ".antitoken": "🔑", ".antispam": "💬", ".captcha": "🧩", ".raidmode": "🚨",
    ".antirole": "🎭", ".antidelrole": "🧱", ".antichannel": "📁", ".ticket": "🎫",
    ".close": "🔒", ".rename": "✏️", ".adduser": "➕", ".deluser": "➖",
    ".giveaway": "🎉", ".backup": "💾", ".backuplist": "📜", ".joinsettings": "👋",
    ".ghostjoin": "👻", ".syncperms": "🔄", ".embed": "📝", ".massiverole": "👥",
    ".serveur": "🏗️",
    ".ban": "🔨", ".unban": "✅", ".unbanall": "♻️", ".kick": "🥾", ".clear": "🧹",
    ".createrole": "🎭", ".createchannel": "📁", ".lock": "🔒", ".unlock": "🔓",
    ".lockcategory": "🔒", ".unlockcategory": "🔓", ".delcategory": "🗑️",
    ".slowmode": "⏱️", ".nuke": "💣", ".temprole": "⏳", ".renamechannel": "✏️",
    ".userinfo": "👤", ".serverinfo": "🏠", ".bl": "⛔", ".unbl": "✅",
    ".bllist": "📜", ".buyer": "💎", ".unbuyer": "💎", ".buyerlist": "💎",
    ".owner": "👑", ".unowner": "👑", ".ownerlist": "👑", ".wl": "⭐",
    ".unwl": "⭐", ".wllist": "⭐", ".wlrole": "⭐", ".unwlrole": "⭐",
    ".wlrolelist": "⭐", ".setperm": "🔐", ".unsetperm": "🔐", ".addrole": "➕",
    ".delrole": "➖", ".bot": "🤖", ".botname": "🏷️", ".botpic": "🖼️",
    ".emoji": "😀", ".say": "📣", ".avatar": "🖼️", ".banner": "🎴",
    ".watch": "👀", ".listen": "🎧", ".autologs": "📋", ".logconfig": "📋",
    ".setup": "⚙️", ".vouch": "✅",
}


def pretty_help_description(description: str) -> str:

    intro = (

        "**Les paramètres mis entre `< >` sont obligatoires, contrairement aux paramètres "

        "mis entre `[ ]` qui sont facultatifs.**\n"

        "**Si tu as besoin d'aide, utilise `.help`.**\n\n"

    )

    parts: list[str] = []

    for raw_line in description.splitlines():

        line = raw_line.strip()

        if not line:

            continue

        match = re.match(r"\*\*(.+?)\*\*\s*-\s*(.+)", line)

        if match:

            command, detail = match.groups()

            parts.append(f"**`{command}`**\n└ {detail}")

        else:

            cleaned = line.strip("*")

            parts.append(f"**{cleaned}**")

    return intro + "\n\n".join(parts)





class HelpSelect(discord.ui.Select):

    def __init__(self) -> None:

        options = [

            discord.SelectOption(

                label=title,

                value=value,

                description=f"Voir les commandes {title.lower()}",

            )

            for value, (title, _) in HELP_SECTIONS.items()

        ]

        super().__init__(placeholder="Choisis une catégorie", min_values=1, max_values=1, options=options)



    async def callback(self, interaction: discord.Interaction) -> None:

        set_current_guild(interaction.guild)

        title, description = HELP_SECTIONS[self.values[0]]

        embed = discord.Embed(

            title=title,

            description=pretty_help_description(description),

            color=discord.Color.blurple(),

        )

        await interaction.response.edit_message(embed=embed, view=self.view)





class HelpView(discord.ui.View):

    def __init__(self) -> None:

        super().__init__(timeout=None)

        self.add_item(HelpSelect())





def ticket_bool(value: bool) -> str:

    return "**✅**" if value else "**❌**"





def ticket_settings_embed() -> discord.Embed:

    cfg = ticket_config()

    options = ticket_options(cfg)

    option_text = "\n".join(

        f"{option['emoji']} {option['label']}".strip()

        for option in options[:10]

    )

    required_roles = cfg.get("required_role_ids") or []

    forbidden_roles = cfg.get("forbidden_role_ids") or []

    embed = discord.Embed(

        title="Paramètres des tickets",

        color=parse_hex_color(cfg.get("embed_color") or "#ff5ec7"),

    )

    embed.add_field(name="Salon", value=f"<#{cfg['panel_channel_id']}>" if cfg.get("panel_channel_id") else "Non configuré", inline=True)

    embed.add_field(name="Message", value="Message automatique", inline=True)

    embed.add_field(name="Type", value="Sélecteur" if cfg.get("panel_type") == "selector" else "Bouton", inline=True)

    embed.add_field(name="Claim", value=ticket_bool(cfg.get("claim_button", True)), inline=True)

    embed.add_field(name="Suppression automatique des tickets fermés", value=ticket_bool(cfg.get("auto_delete_closed", True)), inline=True)

    embed.add_field(name="Fermer automatiquement les tickets des membres quittant le serveur", value=ticket_bool(cfg.get("auto_close_on_leave", True)), inline=True)

    embed.add_field(name="Bouton claim", value=ticket_bool(cfg.get("claim_button", True)), inline=True)

    embed.add_field(name="Bouton close", value=ticket_bool(cfg.get("close_button", True)), inline=True)

    embed.add_field(name="Transcript MP", value=ticket_bool(cfg.get("transcript_dm", False)), inline=True)

    embed.add_field(name="Couleur embed", value=cfg.get("embed_color") or "#ff5ec7", inline=True)

    embed.add_field(name="Rôles requis", value="\n".join(f"<@&{role_id}>" for role_id in required_roles) or "Aucun", inline=True)

    embed.add_field(name="Rôles interdits", value="\n".join(f"<@&{role_id}>" for role_id in forbidden_roles) or "Aucun", inline=True)

    embed.add_field(name="Options", value=option_text or "Aucune", inline=True)

    return embed





def ticket_options_embed() -> discord.Embed:

    cfg = ticket_config()

    options = ticket_options(cfg)

    embed = discord.Embed(

        title="Options des tickets",

        description="Aucune option configurée." if not options else "Options configurées pour le sélecteur.",

        color=parse_hex_color(cfg.get("embed_color") or "#ff5ec7"),

    )

    for index, option in enumerate(options[:10], start=1):

        embed.add_field(

            name=f"{index}. {option['label']}",

            value=option.get("description") or "Aucune description",

            inline=False,

        )

    return embed





def ticket_option_detail_embed(option: dict, index: int) -> discord.Embed:

    cfg = ticket_config()

    mentioned_roles = option.get("mentioned_role_ids") or []

    access_roles = option.get("access_role_ids") or cfg.get("required_role_ids") or []

    embed = discord.Embed(

        title="Paramètres d'option",

        color=parse_hex_color(cfg.get("embed_color") or "#ff5ec7"),

    )

    embed.add_field(name="Catégorie", value=f"<#{option['category_id']}>" if option.get("category_id") else "Non configurée", inline=True)

    embed.add_field(name="Emoji", value=option.get("emoji") or "Aucun", inline=True)

    embed.add_field(name="Texte", value=option.get("label") or f"Option {index}", inline=True)

    embed.add_field(name="Description (sélecteur seulement)", value=option.get("description") or "Aucune description", inline=True)

    embed.add_field(name="Salon de logs", value=f"<#{option['log_channel_id']}>" if option.get("log_channel_id") else "Aucun", inline=True)

    embed.add_field(name="Mention", value="\n".join(f"<@&{role_id}>" for role_id in mentioned_roles) or "Aucune", inline=True)

    embed.add_field(name="Message d'ouverture de ticket", value=option.get("open_message") or cfg.get("welcome_message") or "Non configuré", inline=True)

    embed.add_field(name="Rôles ayant accès", value="\n".join(f"<@&{role_id}>" for role_id in access_roles) or "Aucun", inline=True)

    return embed





def default_ticket_option(index: int) -> dict:

    return {

        "label": f"Catégorie {index}",

        "emoji": "",

        "description": "",

        "category_id": "",

        "log_channel_id": "",

        "mentioned_role_ids": [],

        "access_role_ids": [],

        "open_message": "Merci d'avoir contacte le support.\nDecrivez votre probleme puis attendez une reponse.",

    }





def update_ticket_option(index: int, values: dict) -> dict | None:

    cfg = ticket_config()

    options = list(cfg.get("options") or [])

    if index < 0 or index >= len(options):

        return None

    option = dict(options[index])

    option.update(values)

    options[index] = option

    update_ticket_config({"options": options, "panel_type": "selector"})

    return option





def ids_from_text(value: str) -> list[str]:

    return sorted(set(re.findall(r"\d{15,25}", value or "")))





def ticket_option_prompt(field: str) -> str:

    prompts = {

        "category_id": "Envoie l'ID de la catégorie ticket.",

        "emoji": "Envoie l'emoji à utiliser.",

        "label": "Envoie le texte / nom de la catégorie.",

        "description": "Envoie la description du sélecteur.",

        "mentioned_role_ids": "Envoie les rôles à mentionner avec @role ou leurs IDs. Tu peux en mettre plusieurs.",

        "open_message": "Envoie le message d'ouverture du ticket.",

        "log_channel_id": "Envoie l'ID du salon de logs.",

        "access_role_ids": "Envoie les rôles autorisés avec @role ou leurs IDs. Tu peux en mettre plusieurs.",

    }

    return prompts[field]





def ticket_config_prompt(field: str) -> str:

    prompts = {

        "panel_channel_id": "Envoie l'ID du salon où envoyer le panneau ticket.",

        "required_role_ids": "Envoie les rôles requis avec @role ou leurs IDs. Tu peux en mettre plusieurs.",

        "forbidden_role_ids": "Envoie les rôles interdits avec @role ou leurs IDs. Tu peux en mettre plusieurs.",

        "embed_color": "Envoie une couleur hexadécimale, exemple `#ff5ec7`.",

    }

    return prompts[field]





async def ask_ticket_config_value(interaction: discord.Interaction, field: str) -> None:

    if not interaction.channel:

        await interaction.response.send_message("Salon introuvable.", ephemeral=True)

        return



    await interaction.response.send_message(f"{ticket_config_prompt(field)}\nTape `cancel` pour annuler.")

    prompt_message = await interaction.original_response()



    def check(message: discord.Message) -> bool:

        return (

            message.author.id == interaction.user.id

            and message.channel.id == interaction.channel.id

            and not message.author.bot

        )



    try:

        message = await bot.wait_for("message", check=check, timeout=60)

    except asyncio.TimeoutError:

        timeout_message = await interaction.followup.send("Temps expiré, modification annulée.", wait=True)

        await asyncio.sleep(3)

        for cleanup in (prompt_message, timeout_message):

            try:

                await cleanup.delete()

            except discord.HTTPException:

                pass

        return



    value = message.content.strip()

    if value.lower() == "cancel":

        cancel_message = await interaction.followup.send("Modification annulée.", wait=True)

        await asyncio.sleep(2)

        for cleanup in (prompt_message, message, cancel_message):

            try:

                await cleanup.delete()

            except discord.HTTPException:

                pass

        return



    if field in {"required_role_ids", "forbidden_role_ids"}:

        update = {field: ids_from_text(value)}

    elif field == "embed_color":

        if not re.fullmatch(r"#?[0-9a-fA-F]{6}", value):

            error_message = await interaction.followup.send("Couleur invalide.", wait=True)

            await asyncio.sleep(3)

            for cleanup in (prompt_message, message, error_message):

                try:

                    await cleanup.delete()

                except discord.HTTPException:

                    pass

            return

        update = {"embed_color": "#" + value.removeprefix("#")}

    else:

        parsed = normalize_user_id(value)

        if not parsed:

            error_message = await interaction.followup.send("ID invalide.", wait=True)

            await asyncio.sleep(3)

            for cleanup in (prompt_message, message, error_message):

                try:

                    await cleanup.delete()

                except discord.HTTPException:

                    pass

            return

        update = {field: str(parsed)}



    update_ticket_config(update)

    done_message = await interaction.followup.send("Configuration modifiée.", wait=True)

    if interaction.message:

        await interaction.message.edit(embed=ticket_settings_embed(), view=TicketSettingsView())

    await asyncio.sleep(2)

    for cleanup in (prompt_message, message, done_message):

        try:

            await cleanup.delete()

        except discord.HTTPException:

            pass





async def ask_ticket_option_value(interaction: discord.Interaction, index: int, field: str) -> None:

    if not interaction.channel:

        await interaction.response.send_message("Salon introuvable.", ephemeral=True)

        return



    await interaction.response.send_message(f"{ticket_option_prompt(field)}\nTape `cancel` pour annuler.")

    prompt_message = await interaction.original_response()



    def check(message: discord.Message) -> bool:

        return (

            message.author.id == interaction.user.id

            and message.channel.id == interaction.channel.id

            and not message.author.bot

        )



    try:

        message = await bot.wait_for("message", check=check, timeout=60)

    except asyncio.TimeoutError:

        timeout_message = await interaction.followup.send("Temps expiré, modification annulée.", wait=True)

        await asyncio.sleep(4)

        for cleanup in (prompt_message, timeout_message):

            try:

                await cleanup.delete()

            except discord.HTTPException:

                pass

        return



    value = message.content.strip()

    if value.lower() == "cancel":

        cancel_message = await interaction.followup.send("Modification annulée.", wait=True)

        await asyncio.sleep(2)

        for cleanup in (prompt_message, message, cancel_message):

            try:

                await cleanup.delete()

            except discord.HTTPException:

                pass

        return



    if field in {"mentioned_role_ids", "access_role_ids"}:

        update = {field: ids_from_text(value)}

    elif field in {"category_id", "log_channel_id"}:

        parsed = normalize_user_id(value)

        if not parsed:

            error_message = await interaction.followup.send("ID invalide. Relance le menu et envoie un ID valide.", wait=True)

            await asyncio.sleep(4)

            for cleanup in (prompt_message, message, error_message):

                try:

                    await cleanup.delete()

                except discord.HTTPException:

                    pass

            return

        update = {field: str(parsed)}

    else:

        update = {field: value}



    option = update_ticket_option(index, update)

    if option is None:

        error_message = await interaction.followup.send("Option introuvable.", wait=True)

        await asyncio.sleep(4)

        for cleanup in (prompt_message, message, error_message):

            try:

                await cleanup.delete()

            except discord.HTTPException:

                pass

        return



    done_message = await interaction.followup.send("Option modifiée.", wait=True)

    if interaction.message:

        await interaction.message.edit(

            embed=ticket_option_detail_embed(option, index + 1),

            view=TicketOptionEditView(index),

        )

    await asyncio.sleep(2)

    for cleanup in (prompt_message, message, done_message):

        try:

            await cleanup.delete()

        except discord.HTTPException:

            pass





class TicketOptionActionSelect(discord.ui.Select):

    def __init__(self, index: int) -> None:

        self.index = index

        options = [

            discord.SelectOption(label="Modifier la catégorie", value="category_id"),

            discord.SelectOption(label="Modifier l'emoji", value="emoji"),

            discord.SelectOption(label="Modifier le texte", value="label"),

            discord.SelectOption(label="Modifier la description", value="description"),

            discord.SelectOption(label="Modifier les rôles mentionnés", value="mentioned_role_ids"),

            discord.SelectOption(label="Modifier le message d'ouverture", value="open_message"),

            discord.SelectOption(label="Modifier le salon de logs", value="log_channel_id"),

            discord.SelectOption(label="Modifier les rôles autorisés", value="access_role_ids"),

        ]

        super().__init__(placeholder="Fais un choix", min_values=1, max_values=1, options=options, row=0)



    async def callback(self, interaction: discord.Interaction) -> None:

        set_current_guild(interaction.guild)

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        if self.index >= len(ticket_config().get("options") or []):

            await interaction.response.send_message("Option introuvable.", ephemeral=True)

            return



        field = self.values[0]

        await ask_ticket_option_value(interaction, self.index, field)





class TicketOptionEditView(discord.ui.View):

    def __init__(self, index: int) -> None:

        super().__init__(timeout=None)

        self.index = index

        self.add_item(TicketOptionActionSelect(index))



    @discord.ui.button(label="Retour", emoji="↩️", style=discord.ButtonStyle.secondary, row=1)

    async def back(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        await interaction.response.edit_message(embed=ticket_options_embed(), view=TicketOptionManageView())



    @discord.ui.button(label="Supprimer", emoji="❌", style=discord.ButtonStyle.danger, row=1)

    async def delete(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        cfg = ticket_config()

        options = list(cfg.get("options") or [])

        if self.index < len(options):

            options.pop(self.index)

            update_ticket_config({"options": options})

        await interaction.response.edit_message(embed=ticket_options_embed(), view=TicketOptionManageView())





class TicketOptionPickSelect(discord.ui.Select):

    def __init__(self) -> None:

        cfg = ticket_config()

        options = ticket_options(cfg)

        choices = [

            discord.SelectOption(

                label=option["label"],

                value=str(index),

                description=option.get("description") or None,

                emoji=option.get("emoji") or None,

            )

            for index, option in enumerate(options[:24])

        ]

        choices.append(discord.SelectOption(label="Ajouter une option", value="add"))

        super().__init__(placeholder="Gerer les options", min_values=1, max_values=1, options=choices, row=0)



    async def callback(self, interaction: discord.Interaction) -> None:

        set_current_guild(interaction.guild)

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        cfg = ticket_config()

        options = list(cfg.get("options") or [])

        if self.values[0] == "add":

            options.append(default_ticket_option(len(options) + 1))

            options = options[:25]

            update_ticket_config({"options": options, "panel_type": "selector"})

            index = len(options) - 1

            await interaction.response.edit_message(

                embed=ticket_option_detail_embed(options[index], index + 1),

                view=TicketOptionEditView(index),

            )

            return



        index = int(self.values[0])

        if index >= len(options):

            await interaction.response.send_message("Option introuvable.", ephemeral=True)

            return

        await interaction.response.edit_message(

            embed=ticket_option_detail_embed(options[index], index + 1),

            view=TicketOptionEditView(index),

        )





class TicketOptionManageView(discord.ui.View):

    def __init__(self) -> None:

        super().__init__(timeout=None)

        self.add_item(TicketOptionPickSelect())



    @discord.ui.button(label="Retour", style=discord.ButtonStyle.secondary, row=1)

    async def back(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        await interaction.response.edit_message(embed=ticket_settings_embed(), view=TicketSettingsView())





class TicketOptionsSelect(discord.ui.Select):

    def __init__(self) -> None:

        cfg = ticket_config()

        ticket_items = ticket_options(cfg)

        options = [

            discord.SelectOption(

                label=option["label"],

                value=f"option:{index}",

                description=option.get("description") or None,

            )

            for index, option in enumerate(ticket_items[:23])

        ]

        options.append(discord.SelectOption(label="Ajouter une option", value="add"))

        super().__init__(placeholder="Gerer les options", min_values=1, max_values=1, options=options, row=0)



    async def callback(self, interaction: discord.Interaction) -> None:

        set_current_guild(interaction.guild)

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return



        choice = self.values[0]

        cfg = ticket_config()

        if choice == "add":

            options = list(cfg.get("options") or [])

            options.append(default_ticket_option(len(options) + 1))

            options = options[:25]

            update_ticket_config({"options": options, "panel_type": "selector"})

            index = len(options) - 1

            await interaction.response.edit_message(

                embed=ticket_option_detail_embed(options[index], index + 1),

                view=TicketOptionEditView(index),

            )

            return

        if choice.startswith("option:"):

            options = list(cfg.get("options") or [])

            index = int(choice.split(":", 1)[1])

            if index >= len(options):

                await interaction.response.send_message("Option introuvable.", ephemeral=True)

                return

            await interaction.response.edit_message(

                embed=ticket_option_detail_embed(options[index], index + 1),

                view=TicketOptionEditView(index),

            )

            return





class TicketConfigSelect(discord.ui.Select):

    def __init__(self) -> None:

        options = [

            discord.SelectOption(label="Type bouton/sélecteur", value="panel_type"),

            discord.SelectOption(label="Modifier le salon", value="panel_channel_id"),

            discord.SelectOption(label="Modifier la couleur d'embed", value="embed_color"),

            discord.SelectOption(label="Modifier les rôles requis", value="required_role_ids"),

            discord.SelectOption(label="Modifier les rôles interdits", value="forbidden_role_ids"),

            discord.SelectOption(label="Bouton close", value="close_button"),

            discord.SelectOption(label="Bouton claim", value="claim_button"),

            discord.SelectOption(label="Suppression tickets fermés", value="auto_delete"),

            discord.SelectOption(label="Fermer si le membre quitte", value="auto_leave"),

            discord.SelectOption(label="Transcript MP", value="transcript_dm"),

        ]

        super().__init__(placeholder="Configuration des tickets", min_values=1, max_values=1, options=options, row=1)



    async def callback(self, interaction: discord.Interaction) -> None:

        set_current_guild(interaction.guild)

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return



        choice = self.values[0]

        cfg = ticket_config()

        updates = {}

        if choice in {"panel_channel_id", "required_role_ids", "forbidden_role_ids", "embed_color"}:

            await ask_ticket_config_value(interaction, choice)

            return

        if choice == "panel_type":

            updates["panel_type"] = "button" if cfg.get("panel_type") == "selector" else "selector"

        elif choice == "close_button":

            updates["close_button"] = not cfg.get("close_button", True)

        elif choice == "claim_button":

            updates["claim_button"] = not cfg.get("claim_button", True)

        elif choice == "auto_delete":

            updates["auto_delete_closed"] = not cfg.get("auto_delete_closed", True)

        elif choice == "auto_leave":

            updates["auto_close_on_leave"] = not cfg.get("auto_close_on_leave", True)

        elif choice == "transcript_dm":

            updates["transcript_dm"] = not cfg.get("transcript_dm", False)



        update_ticket_config(updates)

        await interaction.response.edit_message(embed=ticket_settings_embed(), view=TicketSettingsView())





class TicketSettingsView(discord.ui.View):

    def __init__(self) -> None:

        super().__init__(timeout=None)

        self.add_item(TicketOptionsSelect())

        self.add_item(TicketConfigSelect())



    @discord.ui.button(label="Valider", emoji="✅", style=discord.ButtonStyle.green, row=2)

    async def validate(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:

        set_current_guild(interaction.guild)

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        cfg = ticket_config()

        channel_id = cfg.get("panel_channel_id")

        channel = interaction.guild.get_channel(int(channel_id)) if interaction.guild and channel_id else None

        if not isinstance(channel, discord.TextChannel):

            await interaction.response.send_message("Salon panneau ticket non configuré.", ephemeral=True)

            return

        if cfg.get("panel_type") == "selector" and not ticket_options(cfg):

            await interaction.response.send_message("Ajoute au moins une option avant d'envoyer un sélecteur.", ephemeral=True)

            return

        embed = discord.Embed(

            title=cfg["panel_title"],

            description=cfg["panel_description"],

            color=parse_hex_color(cfg.get("embed_color") or "#ff5ec7"),

        )

        await channel.send(embed=embed, view=TicketPanel())

        await interaction.response.send_message(f"Panneau envoye dans {channel.mention}.", ephemeral=True)





def embed_panel_embed() -> discord.Embed:

    preview = make_configured_embed()

    preview.set_footer(text="Configuration de l'embed")

    return preview





async def ask_embed_value(interaction: discord.Interaction, field: str) -> None:

    prompts = {

        "target_channel_id": "Envoie l'ID du salon ou mentionne le salon pour envoyer l'embed.",

        "category_send": "Envoie l'ID de la catégorie. L'embed sera envoyé dans le premier salon texte de cette catégorie.",

        "title": "Envoie le nouveau titre.",

        "description": "Envoie la nouvelle description.",

        "thumbnail": "Envoie l'URL du thumbnail.",

        "image": "Envoie l'URL de l'image.",

        "color": "Envoie la couleur en HEX, exemple `#5865f2`.",

        "footer": "Envoie le footer.",

        "author": "Envoie le nom de l'auteur.",

        "url": "Envoie l'URL du titre.",

        "message": "Envoie le message du bot avec cet embed.",

        "dm_user": "Envoie l'ID ou la mention de la personne a qui envoyer l'embed en MP.",

        "copy_message": "Envoie l'ID du message a copier.",

        "edit_message": "Envoie l'ID du message du bot a modifier avec cet embed.",

        "add_message": "Envoie le message a ajouter a l'embed.",

        "button": "Envoie `Texte | https://lien.com` pour ajouter un bouton URL.",

        "field": "Envoie `Nom | Valeur` pour ajouter un field.",

    }

    await interaction.response.send_message(f"{prompts[field]}\nTape `cancel` pour annuler.")

    prompt_message = await interaction.original_response()



    def check(message: discord.Message) -> bool:

        return (

            message.author.id == interaction.user.id

            and interaction.channel

            and message.channel.id == interaction.channel.id

            and not message.author.bot

        )



    try:

        message = await bot.wait_for("message", check=check, timeout=90)

    except asyncio.TimeoutError:

        timeout_message = await interaction.followup.send("Temps expiré, modification annulée.", wait=True)

        await asyncio.sleep(3)

        for cleanup in (prompt_message, timeout_message):

            try:

                await cleanup.delete()

            except discord.HTTPException:

                pass

        return



    value = message.content.strip()

    if value.lower() == "cancel":

        cancel_message = await interaction.followup.send("Modification annulée.", wait=True)

        await asyncio.sleep(2)

        for cleanup in (prompt_message, message, cancel_message):

            try:

                await cleanup.delete()

            except discord.HTTPException:

                pass

        return



    cfg = active_config()["embed"]

    done_content = "Embed modifié."

    if field == "target_channel_id":

        parsed = normalize_user_id(value)

        update_embed_config({"target_channel_id": str(parsed) if parsed else None})

    elif field == "category_send":

        parsed = normalize_user_id(value)

        category = interaction.guild.get_channel(parsed) if interaction.guild and parsed else None

        target = None

        if isinstance(category, discord.TextChannel):

            target = category

        if isinstance(category, discord.CategoryChannel):

            target = next(

                (

                    channel

                    for channel in category.text_channels

                    if interaction.guild.me

                    and channel.permissions_for(interaction.guild.me).view_channel

                    and channel.permissions_for(interaction.guild.me).send_messages

                ),

                None,

            )

        if not isinstance(target, discord.TextChannel):

            available = []

            if isinstance(category, discord.CategoryChannel):

                available = [f"{channel.name} (`{channel.id}`)" for channel in category.text_channels[:5]]

            detail = "\n".join(available) if available else "Donne l'ID d'une catégorie ou directement l'ID d'un salon texte."

            error_message = await interaction.followup.send(

                f"Catégorie invalide ou aucun salon texte accessible dedans.\n{detail}",

                wait=True,

            )

            await asyncio.sleep(4)

            for cleanup in (prompt_message, message, error_message):

                try:

                    await cleanup.delete()

                except discord.HTTPException:

                    pass

            return

        await target.send(content=cfg.get("message") or None, embed=make_configured_embed(), view=make_embed_view())

        done_content = f"Embed envoyé dans {target.mention}."

    elif field == "dm_user":

        parsed = normalize_user_id(value)

        user = await bot.fetch_user(parsed) if parsed else None

        if user:

            await user.send(content=cfg.get("message") or None, embed=make_configured_embed(), view=make_embed_view())

    elif field == "copy_message":

        parsed = normalize_user_id(value)

        copied = None

        if parsed and isinstance(interaction.channel, discord.TextChannel):

            try:

                copied = await interaction.channel.fetch_message(parsed)

            except discord.HTTPException:

                copied = None

        if copied and copied.embeds:

            data = copied.embeds[0].to_dict()

            update_embed_config({

                "title": data.get("title", ""),

                "description": data.get("description", ""),

                "color": f"#{data.get('color', 0):06x}" if data.get("color") else cfg.get("color", "#69d6a2"),

                "footer": (data.get("footer") or {}).get("text", ""),

                "thumbnail": (data.get("thumbnail") or {}).get("url", ""),

                "image": (data.get("image") or {}).get("url", ""),

                "author": (data.get("author") or {}).get("name", ""),

                "url": data.get("url", ""),

                "fields": data.get("fields", []),

            })

    elif field == "edit_message":

        parsed = normalize_user_id(value)

        edited = None

        if parsed and isinstance(interaction.channel, discord.TextChannel):

            try:

                edited = await interaction.channel.fetch_message(parsed)

            except discord.HTTPException:

                edited = None

        if edited and bot.user and edited.author.id == bot.user.id:

            await edited.edit(content=cfg.get("message") or None, embed=make_configured_embed(), view=make_embed_view())

    elif field == "add_message":

        current = cfg.get("message") or ""

        update_embed_config({"message": f"{current}\n{value}".strip()})

    elif field == "button":

        parts = [part.strip() for part in value.split("|", 1)]

        if len(parts) == 2:

            update_embed_config({"button_label": parts[0], "button_url": parts[1]})

    elif field == "field":

        parts = [part.strip() for part in value.split("|", 1)]

        if len(parts) == 2:

            fields = list(cfg.get("fields") or [])

            fields.append({"name": parts[0], "value": parts[1], "inline": False})

            update_embed_config({"fields": fields[:25]})

    else:

        update_embed_config({field: value})



    done_message = await interaction.followup.send(done_content, wait=True)

    if interaction.message:

        await interaction.message.edit(embed=embed_panel_embed(), view=EmbedSettingsView())

    await asyncio.sleep(2)

    for cleanup in (prompt_message, message, done_message):

        try:

            await cleanup.delete()

        except discord.HTTPException:

            pass





class EmbedSettingsSelect(discord.ui.Select):

    def __init__(self) -> None:

        options = [

            discord.SelectOption(label="Modifier le titre", value="title"),

            discord.SelectOption(label="Modifier la description", value="description"),

            discord.SelectOption(label="Ajouter un Field", value="field"),

            discord.SelectOption(label="Retirer un Field", value="remove_field"),

            discord.SelectOption(label="Modifier le thumbnail", value="thumbnail"),

            discord.SelectOption(label="Modifier l'image", value="image"),

            discord.SelectOption(label="Modifier la couleur", value="color"),

            discord.SelectOption(label="Modifier le footer", value="footer"),

            discord.SelectOption(label="Modifier l'auteur", value="author"),

            discord.SelectOption(label="Modifier l'URL", value="url"),

            discord.SelectOption(label="Modifier le timestamp", value="timestamp"),

            discord.SelectOption(label="Copier un embed existant", value="copy_message"),

            discord.SelectOption(label="Ajouter un message à l'embed", value="add_message"),

            discord.SelectOption(label="Ajouter un bouton d'URL", value="button"),

        ]

        super().__init__(

            placeholder="Clique ici pour modifier l'embed",

            min_values=1,

            max_values=1,

            options=options,

            row=0,

        )



    async def callback(self, interaction: discord.Interaction) -> None:

        set_current_guild(interaction.guild)

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        choice = self.values[0]

        if choice == "timestamp":

            cfg = active_config()["embed"]

            update_embed_config({"timestamp": not cfg.get("timestamp", False)})

            await interaction.response.edit_message(embed=embed_panel_embed(), view=EmbedSettingsView())

            return

        if choice == "remove_field":

            cfg = active_config()["embed"]

            fields = list(cfg.get("fields") or [])

            if fields:

                fields.pop()

                update_embed_config({"fields": fields})

            await interaction.response.edit_message(embed=embed_panel_embed(), view=EmbedSettingsView())

            return

        await ask_embed_value(interaction, choice)





class EmbedSettingsView(discord.ui.View):

    def __init__(self) -> None:

        super().__init__(timeout=None)

        self.add_item(EmbedSettingsSelect())



    @discord.ui.button(label="Choisir une Catégorie", style=discord.ButtonStyle.secondary, row=1)

    async def send_embed_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        await ask_embed_value(interaction, "category_send")



    @discord.ui.button(label="Modifier un message du bot avec cette embed", style=discord.ButtonStyle.secondary, row=2)

    async def edit_bot_message(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:

        await ask_embed_value(interaction, "edit_message")



    @discord.ui.button(label="Envoyer cette embed en message privé à quelqu'un", style=discord.ButtonStyle.secondary, row=3)

    async def dm_embed(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:

        await ask_embed_value(interaction, "dm_user")



    @discord.ui.button(label="Supprimer l'embed", style=discord.ButtonStyle.danger, row=4)

    async def delete_embed(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        update_embed_config({

            "title": "",

            "description": "",

            "footer": "",

            "thumbnail": "",

            "image": "",

            "author": "",

            "url": "",

            "fields": [],

            "button_label": "",

            "button_url": "",

        })

        await interaction.response.edit_message(embed=embed_panel_embed(), view=EmbedSettingsView())





@bot.event

async def on_ready() -> None:

    global ticket_views_added

    if not ticket_views_added:

        bot.add_view(TicketPanel())

        bot.add_view(TicketManageView())

        bot.add_view(GiveawayJoinView())

        ticket_views_added = True

    await apply_presence()

    print(f"Connecte en tant que {bot.user} (ID: {bot.user.id})")





@bot.event

async def on_interaction(interaction: discord.Interaction) -> None:

    set_current_guild(interaction.guild)





def get_named_log_channel(guild: discord.Guild, name: str) -> discord.TextChannel | None:

    channel = discord.utils.get(guild.text_channels, name=name)

    return channel if isinstance(channel, discord.TextChannel) else None





async def log_message_event(message: discord.Message, action: str) -> None:

    set_current_guild(message.guild)

    if message.author.bot or not message.guild:

        return

    if isinstance(message.channel, discord.TextChannel) and message.channel.name.startswith("logs-"):

        return



    channel = get_named_log_channel(message.guild, "logs-messages")

    if not channel:

        return



    content = message.content.strip() if message.content else ""

    if not content:

        content = "[aucun texte]"

    if len(content) > 900:

        content = content[:900] + "..."



    embed = discord.Embed(

        title=f"Message {action}",

        color=discord.Color.red() if action == "supprimé" else discord.Color.blurple(),

        timestamp=datetime.now(timezone.utc),

    )

    embed.add_field(name="Auteur", value=f"{message.author.mention} (`{message.author.id}`)", inline=False)

    channel_name = message.channel.mention if hasattr(message.channel, "mention") else str(message.channel)

    embed.add_field(name="Salon", value=channel_name, inline=False)

    embed.add_field(name="Contenu", value=content, inline=False)

    if message.attachments:

        embed.add_field(name="Pièces jointes", value=str(len(message.attachments)), inline=True)

    embed.set_footer(text=f"Message ID: {message.id}")



    try:

        await channel.send(embed=embed)

    except discord.HTTPException:

        pass





@bot.event

async def on_message(message: discord.Message) -> None:

    set_current_guild(message.guild)

    if message.author.bot or not message.guild:

        return



    if bot.user and bot.user in message.mentions and message.content.strip() in {bot.user.mention, f"<@!{bot.user.id}>"}:

        cfg = bot_profile_config()

        prefix = active_config()["prefix"]

        response = (cfg.get("ping_message") or "Mon préfixe est `{prefix}`.").replace("{prefix}", prefix)

        await message.reply(response, mention_author=False)

        return



    cfg = anti_raid_config()

    pending_key = (message.guild.id, message.author.id)

    if cfg.get("enabled") and cfg.get("captcha") and pending_key in captcha_pending:

        if message.content.strip() == captcha_pending[pending_key]:

            captcha_pending.pop(pending_key, None)

            role_id = cfg.get("captcha_role_id")

            role = message.guild.get_role(int(role_id)) if role_id and str(role_id).isdigit() else None

            if role:

                allowed, reason = can_assign_role(message.guild, role)

                if allowed and isinstance(message.author, discord.Member):

                    try:

                        await message.author.add_roles(role, reason="Captcha validé")

                    except discord.HTTPException:

                        pass

                elif reason:

                    await log_event(message.guild, f"Captcha: impossible d'ajouter {role.name} à {message.author}: {reason}")

            if cfg.get("captcha_delete_messages", True):

                try:

                    await message.delete()

                except discord.Forbidden:

                    pass

                await message.channel.send(f"{message.author.mention} captcha validé.", delete_after=5)

            else:

                await message.reply("Captcha validé.", mention_author=False)

        else:

            try:

                await message.delete()

            except discord.Forbidden:

                pass

        return



    if cfg["enabled"] and not message.author.guild_permissions.manage_messages and not await is_guard_bypassed(message.author, message.guild):

        should_delete = False

        reason = ""



        if cfg.get("antiinvite") and INVITE_RE.search(message.content):

            should_delete = True

            reason = "invitation Discord interdite"

        elif cfg.get("antilink") and LINK_RE.search(message.content):

            should_delete = True

            reason = "lien interdit"

        elif cfg.get("antimention") and int(cfg.get("antimention_limit", 5) or 5) > 0 and (len(message.mentions) + len(message.role_mentions)) >= int(cfg.get("antimention_limit", 5) or 5):

            should_delete = True

            reason = "trop de mentions"

        elif cfg.get("antieveryone") and ("@everyone" in message.content or "@here" in message.content):

            should_delete = True

            reason = "everyone/here interdit"

        elif cfg.get("antitoken") and TOKEN_RE.search(message.content):

            should_delete = True

            reason = "token interdit"

        elif cfg.get("antispam"):

            key = (message.guild.id, message.author.id)

            now = datetime.now(timezone.utc)

            history = message_history[key]

            history.append(now)

            while history and (now - history[0]).total_seconds() > 6:

                history.popleft()

            if len(history) >= 5:

                should_delete = True

                reason = "spam de messages"



        if should_delete:

            await punish_message_spam(message, reason)

            guard_key = "antilink" if reason == "lien interdit" else "antieveryone"

            if reason == "invitation Discord interdite":

                guard_key = "antiinvite"

            if reason == "trop de mentions":

                guard_key = "antimention"

            if reason == "spam de messages":

                guard_key = "antispam"

            if reason == "token interdit":

                guard_key = "antitoken"

            await apply_sanction(message.guild, message.author, guard_key, f"{guard_key}: {reason}")

            return



    await log_message_event(message, "envoyé")

    await bot.process_commands(message)





@bot.event

async def on_message_delete(message: discord.Message) -> None:

    set_current_guild(message.guild)

    if message.guild and not message.author.bot:

        deleted_message_cache[(message.guild.id, message.channel.id)] = {

            "author": str(message.author),

            "author_id": message.author.id,

            "content": message.content or "",

            "attachments": [attachment.url for attachment in message.attachments],

            "created_at": message.created_at,

            "deleted_at": datetime.now(timezone.utc),

        }

    await log_message_event(message, "supprimé")





@bot.event

async def on_bulk_message_delete(messages: list[discord.Message]) -> None:

    for message in messages[:10]:

        set_current_guild(message.guild)

        await log_message_event(message, "supprimé")





@bot.event

async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:

    if payload.user_id == (bot.user.id if bot.user else None) or not payload.guild_id:

        return

    current_guild_id.set(str(payload.guild_id))

    cfg = react_role_config()

    if str(payload.message_id) != str(cfg.get("message_id")):

        return

    if str(payload.emoji) != str(cfg.get("emoji")):

        return

    guild = bot.get_guild(payload.guild_id)

    if not guild:

        return

    role = guild.get_role(int(cfg["role_id"])) if cfg.get("role_id") else None

    member = guild.get_member(payload.user_id)

    if not role or not member:

        return

    try:

        await member.add_roles(role, reason="Reactrole")

    except discord.HTTPException:

        pass





@bot.event

async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent) -> None:

    if not payload.guild_id:

        return

    current_guild_id.set(str(payload.guild_id))

    cfg = react_role_config()

    if str(payload.message_id) != str(cfg.get("message_id")):

        return

    if str(payload.emoji) != str(cfg.get("emoji")):

        return

    guild = bot.get_guild(payload.guild_id)

    if not guild:

        return

    role = guild.get_role(int(cfg["role_id"])) if cfg.get("role_id") else None

    member = guild.get_member(payload.user_id)

    if not role or not member:

        return

    try:

        await member.remove_roles(role, reason="Reactrole retiré")

    except discord.HTTPException:

        pass





async def latest_audit_actor(guild: discord.Guild, action: discord.AuditLogAction, target_id: int | None = None) -> discord.abc.User | None:

    if not guild.me or not guild.me.guild_permissions.view_audit_log:

        return None

    try:

        async for entry in guild.audit_logs(limit=6, action=action):

            target = getattr(entry, "target", None)

            if target_id is None or getattr(target, "id", None) == target_id:

                return entry.user

    except discord.Forbidden:

        return None

    return None



DANGEROUS_ROLE_PERMISSIONS = (

    "administrator",

    "manage_guild",

    "manage_roles",

    "manage_channels",

    "manage_webhooks",

    "ban_members",

    "kick_members",

    "moderate_members",

    "manage_messages",

)



def has_dangerous_role_permission(permissions: discord.Permissions) -> bool:

    return any(getattr(permissions, name, False) for name in DANGEROUS_ROLE_PERMISSIONS)



def dangerous_permission_added(before: discord.Permissions, after: discord.Permissions, admin_only: bool = False) -> bool:

    names = ("administrator",) if admin_only else DANGEROUS_ROLE_PERMISSIONS

    return any(not getattr(before, name, False) and getattr(after, name, False) for name in names)



@bot.event

async def on_thread_create(thread: discord.Thread) -> None:

    set_current_guild(thread.guild)

    cfg = anti_raid_config()

    if not cfg.get("enabled") or not cfg.get("antithread"):

        return

    actor = await latest_audit_actor(thread.guild, discord.AuditLogAction.thread_create, thread.id)

    if await is_guard_bypassed(actor, thread.guild):

        return

    try:

        await thread.delete(reason="Antithread: thread non autorisé")

    except discord.HTTPException:

        pass

    member = thread.guild.get_member(actor.id) if actor else None

    if member:

        await apply_sanction(thread.guild, member, "antithread", "Antithread: création non autorisée")



@bot.event

async def on_guild_emojis_update(guild: discord.Guild, before: list[discord.Emoji], after: list[discord.Emoji]) -> None:

    set_current_guild(guild)

    cfg = anti_raid_config()

    if not cfg.get("enabled") or not cfg.get("antiemoji") or len(after) <= len(before):

        return

    before_ids = {emoji.id for emoji in before}

    created = [emoji for emoji in after if emoji.id not in before_ids]

    for emoji in created:

        actor = await latest_audit_actor(guild, discord.AuditLogAction.emoji_create, emoji.id)

        if await is_guard_bypassed(actor, guild):

            continue

        try:

            await emoji.delete(reason="Antiemoji: emoji non autorisé")

        except discord.HTTPException:

            pass

        member = guild.get_member(actor.id) if actor else None

        if member:

            await apply_sanction(guild, member, "antiemoji", "Antiemoji: création non autorisée")



@bot.event

async def on_guild_stickers_update(guild: discord.Guild, before: list[discord.GuildSticker], after: list[discord.GuildSticker]) -> None:

    set_current_guild(guild)

    cfg = anti_raid_config()

    if not cfg.get("enabled") or not cfg.get("antisticker") or len(after) <= len(before):

        return

    before_ids = {sticker.id for sticker in before}

    created = [sticker for sticker in after if sticker.id not in before_ids]

    for sticker in created:

        actor = await latest_audit_actor(guild, discord.AuditLogAction.sticker_create, sticker.id)

        if await is_guard_bypassed(actor, guild):

            continue

        try:

            await sticker.delete(reason="Antisticker: sticker non autorisé")

        except discord.HTTPException:

            pass

        member = guild.get_member(actor.id) if actor else None

        if member:

            await apply_sanction(guild, member, "antisticker", "Antisticker: création non autorisée")



@bot.event

async def on_member_ban(guild: discord.Guild, user: discord.User) -> None:

    set_current_guild(guild)

    cfg = anti_raid_config()

    if not cfg.get("enabled") or not cfg.get("antiban"):

        return

    actor = await audit_user(guild, discord.AuditLogAction.ban, user.id)

    if await is_guard_bypassed(actor, guild):

        return

    try:

        await guild.unban(user, reason="Antiban: ban annule")

        await log_guard(guild, "Antiban", f"ban de {user} annule", actor)

        await apply_sanction(guild, actor, "antiban", f"Antiban: ban non autorisé de {user}")

    except discord.Forbidden:

        await log_guard(guild, "Antiban", f"ban detecte sur {user}, mais permission unban manquante", actor)





@bot.event

async def on_member_join(member: discord.Member) -> None:

    set_current_guild(member.guild)

    cfg = anti_raid_config()

    if member.bot and cfg.get("enabled") and cfg.get("antibot"):

        actor = await audit_user(member.guild, discord.AuditLogAction.bot_add, member.id)

        if not await is_guard_bypassed(actor, member.guild):

            try:

                await member.ban(reason="Antibot: bot ajouté sans autorisation", delete_message_seconds=0)

                await log_guard(member.guild, "Antibot", f"bot {member} banni", actor)

                await apply_sanction(member.guild, actor, "antibot", f"Antibot: ajout non autorisé de {member}")

            except discord.Forbidden:

                await log_guard(member.guild, "Antibot", f"bot {member} détecté, mais permission ban manquante", actor)

            return



    if cfg.get("enabled") and cfg.get("antialt") and not member.bot:

        min_days = int(cfg.get("antialt_days", 7) or 7)

        account_age = datetime.now(timezone.utc) - member.created_at

        if account_age < timedelta(days=min_days) and not await is_guard_bypassed(member, member.guild):

            await apply_sanction(member.guild, member, "antialt", f"Antialt: compte de moins de {min_days} jour(s)")

            return



    if cfg.get("enabled") and cfg.get("captcha") and not member.bot:

        code = str(100000 + int.from_bytes(os.urandom(3), "big") % 900000)

        captcha_pending[(member.guild.id, member.id)] = code

        channel_id = cfg.get("captcha_channel_id")

        channel = member.guild.get_channel(int(channel_id)) if channel_id and str(channel_id).isdigit() else member.guild.system_channel

        if not isinstance(channel, discord.TextChannel):

            channel = next(

                (

                    item for item in member.guild.text_channels

                    if item.permissions_for(member.guild.me).send_messages

                ),

                None,

            )

        if isinstance(channel, discord.TextChannel):

            await channel.send(f"{member.mention}, ton code captcha est `{code}`. Envoie ce code ici pour valider.")

        else:

            await log_event(member.guild, f"Captcha: aucun salon accessible pour envoyer le code de {member}.")



    if is_blacklisted_id(member.id):

        try:

            await member.ban(reason="Blacklist: retour interdit", delete_message_seconds=0)

        except discord.Forbidden:

            await log_event(member.guild, f"Blacklist: impossible de bannir {member}.")

        return



    settings = server_settings_config()

    for role_id in settings.get("join_role_ids", []):

        role = member.guild.get_role(int(role_id)) if str(role_id).isdigit() else None

        if not role:

            continue

        allowed, reason = can_assign_role(member.guild, role)

        if not allowed:

            await log_event(member.guild, f"Joinrole: impossible d'ajouter {role.name} à {member}: {reason}")

            continue

        try:

            await member.add_roles(role, reason="Joinrole automatique")

        except discord.Forbidden:

            await log_event(member.guild, f"Joinrole: impossible d'ajouter {role.name} à {member}.")



    if settings.get("join_embed_enabled") and settings.get("join_channel_id"):

        channel = member.guild.get_channel(int(settings["join_channel_id"]))

        if isinstance(channel, discord.TextChannel):

            message = format_join_message(settings.get("join_message") or server_settings_config()["join_message"], member)

            embed = discord.Embed(

                description=message,

                color=parse_hex_color(settings.get("join_embed_color") or "#ff5ec7"),

            )

            await channel.send(embed=embed)



    ghost_role = member.guild.get_role(int(settings["ghost_join_role_id"])) if settings.get("ghost_join_role_id") else None

    ghost_channel = member.guild.get_channel(int(settings["ghost_join_channel_id"])) if settings.get("ghost_join_channel_id") else None

    if ghost_role and isinstance(ghost_channel, discord.TextChannel):

        try:

            ghost_message = await ghost_channel.send(

                ghost_role.mention,

                allowed_mentions=discord.AllowedMentions(roles=True, users=False, everyone=False),

            )

            await ghost_message.delete()

        except discord.HTTPException:

            pass





@bot.event

async def on_member_unban(guild: discord.Guild, user: discord.User) -> None:

    set_current_guild(guild)

    cfg = anti_raid_config()

    if not cfg.get("enabled") or not cfg.get("antiunban"):

        return

    actor = await audit_user(guild, discord.AuditLogAction.unban, user.id)

    if await is_guard_bypassed(actor, guild):

        return

    try:

        await guild.ban(user, reason="Antiunban: unban annule")

        await log_guard(guild, "Antiunban", f"unban de {user} annule", actor)

        await apply_sanction(guild, actor, "antiunban", f"Antiunban: unban non autorisé de {user}")

    except discord.Forbidden:

        await log_guard(guild, "Antiunban", f"unban detecte sur {user}, mais permission ban manquante", actor)





@bot.event

async def on_member_remove(member: discord.Member) -> None:

    set_current_guild(member.guild)

    tickets = ticket_config()

    if tickets.get("auto_close_on_leave"):

        marker = f"ticket_owner:{member.id}"

        for channel in member.guild.text_channels:

            if channel.topic and marker in channel.topic:

                try:

                    await channel.delete(reason=f"Ticket ferme automatiquement: {member} a quitte le serveur")

                except discord.Forbidden:

                    continue



    settings = server_settings_config()

    if settings.get("leave_embed_enabled") and settings.get("leave_channel_id"):

        channel = member.guild.get_channel(int(settings["leave_channel_id"]))

        if isinstance(channel, discord.TextChannel):

            message = format_join_message(settings.get("leave_message") or server_settings_config()["leave_message"], member)

            embed = discord.Embed(

                description=message,

                color=parse_hex_color(settings.get("leave_embed_color") or "#ff5ec7"),

            )

            try:

                await channel.send(embed=embed)

            except discord.HTTPException:

                pass



    cfg = anti_raid_config()

    if not cfg.get("enabled") or not cfg.get("antikick"):

        return

    actor = await audit_user(member.guild, discord.AuditLogAction.kick, member.id)

    if await is_guard_bypassed(actor, member.guild):

        return

    if actor:

        await log_guard(member.guild, "Antikick", f"kick detecte sur {member}", actor)

        await apply_sanction(member.guild, actor, "antikick", f"Antikick: kick non autorisé de {member}")





@bot.event

async def on_guild_role_create(role: discord.Role) -> None:

    set_current_guild(role.guild)

    cfg = anti_raid_config()

    if not cfg.get("enabled"):

        return

    actor = await audit_user(role.guild, discord.AuditLogAction.role_create, role.id)

    if await is_guard_bypassed(actor, role.guild):

        return

    dangerous_key = ""

    if cfg.get("antiadmin") and role.permissions.administrator:

        dangerous_key = "antiadmin"

    elif cfg.get("antiroleperm") and has_dangerous_role_permission(role.permissions):

        dangerous_key = "antiroleperm"

    if not cfg.get("antiaddrole") and not dangerous_key:

        return

    try:

        await role.delete(reason="Antiaddrole: role cree annule")

        guard_name = ANTI_RAID_DISPLAY_NAMES.get(dangerous_key or "antiaddrole", "Antiaddrole")

        await log_guard(role.guild, guard_name, f"role {role.name} supprime", actor)

        await apply_sanction(role.guild, actor, dangerous_key or "antiaddrole", f"{guard_name}: création non autorisée de {role.name}")

    except discord.Forbidden:

        await log_guard(role.guild, "Antiaddrole", f"role {role.name} cree, mais permission delete manquante", actor)





@bot.event

async def on_guild_role_update(before: discord.Role, after: discord.Role) -> None:

    set_current_guild(after.guild)

    cfg = anti_raid_config()

    if not cfg.get("enabled") or (not cfg.get("antiadmin") and not cfg.get("antiroleperm")):

        return

    key = ""

    if cfg.get("antiadmin") and dangerous_permission_added(before.permissions, after.permissions, admin_only=True):

        key = "antiadmin"

    elif cfg.get("antiroleperm") and dangerous_permission_added(before.permissions, after.permissions):

        key = "antiroleperm"

    if not key:

        return

    actor = await audit_user(after.guild, discord.AuditLogAction.role_update, after.id)

    if await is_guard_bypassed(actor, after.guild):

        return

    try:

        await after.edit(permissions=before.permissions, reason=f"{key}: permissions dangereuses annulées")

        await log_guard(after.guild, ANTI_RAID_DISPLAY_NAMES.get(key, key), f"permissions du rôle {after.name} restaurées", actor)

    except discord.Forbidden:

        await log_guard(after.guild, ANTI_RAID_DISPLAY_NAMES.get(key, key), f"permissions dangereuses sur {after.name}, mais permission edit manquante", actor)

    if actor:

        await apply_sanction(after.guild, actor, key, f"{key}: permissions dangereuses sur {after.name}")



@bot.event

async def on_guild_role_delete(role: discord.Role) -> None:

    set_current_guild(role.guild)

    cfg = anti_raid_config()

    if not cfg.get("enabled") or not cfg.get("antidelrole"):

        return

    actor = await audit_user(role.guild, discord.AuditLogAction.role_delete, role.id)

    if await is_guard_bypassed(actor, role.guild):

        return

    try:

        restored = await role.guild.create_role(

            name=role.name,

            permissions=role.permissions,

            colour=role.colour,

            hoist=role.hoist,

            mentionable=role.mentionable,

            reason="Antidelrole: role restaure",

        )

        await log_guard(role.guild, "Antidelrole", f"role {restored.name} restaure", actor)

        await apply_sanction(role.guild, actor, "antidelrole", f"Antidelrole: suppression non autorisée de {role.name}")

    except discord.Forbidden:

        await log_guard(role.guild, "Antidelrole", f"role {role.name} supprime, mais permission creation manquante", actor)





@bot.event

async def on_guild_channel_create(channel: discord.abc.GuildChannel) -> None:

    set_current_guild(channel.guild)

    cfg = anti_raid_config()

    if not cfg.get("enabled") or not cfg.get("antichannel"):

        return

    actor = await audit_user(channel.guild, discord.AuditLogAction.channel_create, channel.id)

    if await is_guard_bypassed(actor, channel.guild):

        return

    try:

        await channel.delete(reason="Antichannel: salon cree annule")

        await log_guard(channel.guild, "Antichannel", f"salon {channel.name} supprime", actor)

        await apply_sanction(channel.guild, actor, "antichannel", f"Antichannel: création non autorisée de {channel.name}")

    except discord.Forbidden:

        await log_guard(channel.guild, "Antichannel", f"salon {channel.name} cree, mais permission delete manquante", actor)





@bot.event

async def on_guild_channel_delete(channel: discord.abc.GuildChannel) -> None:

    set_current_guild(channel.guild)

    cfg = anti_raid_config()

    if not cfg.get("enabled") or not cfg.get("antichannel"):

        return

    actor = await audit_user(channel.guild, discord.AuditLogAction.channel_delete, channel.id)

    if await is_guard_bypassed(actor, channel.guild):

        return

    try:

        overwrites = getattr(channel, "overwrites", None)

        category = getattr(channel, "category", None)

        if isinstance(channel, discord.TextChannel):

            restored = await channel.guild.create_text_channel(

                channel.name,

                category=category,

                topic=channel.topic,

                nsfw=channel.nsfw,

                slowmode_delay=channel.slowmode_delay,

                overwrites=overwrites,

                reason="Antichannel: salon restaure",

            )

        elif isinstance(channel, discord.VoiceChannel):

            restored = await channel.guild.create_voice_channel(

                channel.name,

                category=category,

                overwrites=overwrites,

                reason="Antichannel: salon vocal restaure",

            )

        else:

            await log_guard(channel.guild, "Antichannel", f"suppression detectee sur {channel.name}", actor)

            return

        await log_guard(channel.guild, "Antichannel", f"salon {restored.name} restaure", actor)

        await apply_sanction(channel.guild, actor, "antichannel", f"Antichannel: suppression non autorisée de {channel.name}")

    except discord.Forbidden:

        await log_guard(channel.guild, "Antichannel", f"salon {channel.name} supprime, mais permission creation manquante", actor)





@bot.event

async def on_webhooks_update(channel: discord.abc.GuildChannel) -> None:

    if not isinstance(channel, discord.TextChannel):

        return

    set_current_guild(channel.guild)

    cfg = anti_raid_config()

    if not cfg.get("enabled") or not cfg.get("antiwebhook"):

        return

    actor = await audit_user(channel.guild, discord.AuditLogAction.webhook_create)

    if await is_guard_bypassed(actor, guild):

        return

    deleted = 0

    try:

        webhooks = await channel.webhooks()

    except discord.Forbidden:

        await log_guard(channel.guild, "Antiwebhook", f"webhook detecte dans {channel.mention}, mais permission manquante", actor)

        return

    for webhook in webhooks:

        if actor and webhook.user and webhook.user.id != actor.id:

            continue

        try:

            await webhook.delete(reason="Antiwebhook: webhook non autorise")

            deleted += 1

        except discord.HTTPException:

            continue

    if deleted:

        await log_guard(channel.guild, "Antiwebhook", f"{deleted} webhook supprime dans {channel.mention}", actor)

        await apply_sanction(channel.guild, actor, "antiwebhook", f"Antiwebhook: creation non autorisee dans {channel.name}")





def format_channel_status(guild: discord.Guild, channel_id: str | int | None) -> str:

    if not channel_id:

        return "Non configuré"

    try:

        channel = guild.get_channel(int(channel_id))

    except (TypeError, ValueError):

        return "ID invalide"

    if isinstance(channel, discord.TextChannel):

        return channel.mention

    return f"Introuvable (`{channel_id}`)"





def raidstatus_embed(guild: discord.Guild, selected_sanction: str | None = None) -> discord.Embed:

    cfg = anti_raid_config()

    enabled = cfg.get("enabled", False)

    title = "Antiraid"

    color = discord.Color.green() if enabled else discord.Color.red()

    embed = discord.Embed(

        title=title,

        description="État des protections Anti Raid.",

        color=color,

    )

    embed.add_field(name="Système", value="Activé" if enabled else "Désactivé", inline=True)



    status_lines = [

        f"**{ANTI_RAID_DISPLAY_NAMES.get(key, label)}**: `{'ON' if cfg.get(key) else 'OFF'}`"

        for label, key in ANTI_RAID_PROTECTIONS

    ]

    embed.add_field(name="Protections", value="\n".join(status_lines), inline=False)

    sanctions = sanction_config()

    sanction_lines = []

    for label, key in ANTI_RAID_PROTECTIONS:

        marker = " ->" if key == selected_sanction else ""

        action = sanctions.get(key, "derank")

        sanction_lines.append(f"{marker} **{ANTI_RAID_DISPLAY_NAMES.get(key, label)}**: `{SANCTION_DISPLAY_NAMES.get(action, action)}`")

    embed.add_field(name="Sanctions", value="\n".join(sanction_lines), inline=False)

    embed.set_footer(text="Choisis une protection pour ON/OFF, ou règle sa sanction.")

    return embed





class RaidStatusProtectionSelect(discord.ui.Select):

    def __init__(self) -> None:

        cfg = anti_raid_config()

        global_enabled = all(cfg.get(key, False) for key in ANTI_RAID_KEYS)

        options = [

            discord.SelectOption(
                label=f"Global {'ON' if global_enabled else 'OFF'}",
                value="global",
                description="Active ou désactive toutes les protections",
            ),
        ]

        options.extend(
            discord.SelectOption(
                label=f"{ANTI_RAID_DISPLAY_NAMES.get(key, label)} {'ON' if cfg.get(key) else 'OFF'}",
                value=key,
                description="Clique pour passer en OFF" if cfg.get(key) else "Clique pour passer en ON",
            )
            for label, key in ANTI_RAID_PROTECTIONS
        )

        super().__init__(placeholder="Active ou désactive une protection", min_values=1, max_values=1, options=options, row=0)


    async def callback(self, interaction: discord.Interaction) -> None:

        set_current_guild(interaction.guild)

        if not interaction.guild or not isinstance(interaction.user, discord.Member):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        if not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        from config_store import update_config



        cfg = anti_raid_config()

        key = self.values[0]

        if key == "global":

            enabled = not all(cfg.get(item, False) for item in ANTI_RAID_KEYS)

            update_active_config({"anti_raid": {item: enabled for item in ANTI_RAID_KEYS}})

        else:

            update_active_config({"anti_raid": {key: not cfg.get(key, False)}})

        await interaction.response.edit_message(

            embed=raidstatus_embed(interaction.guild),

            view=RaidStatusView(),

        )





class RaidStatusSanctionProtectionSelect(discord.ui.Select):

    def __init__(self, selected: str | None = None) -> None:

        options = [

            discord.SelectOption(

                label=ANTI_RAID_DISPLAY_NAMES.get(key, label),

                value=key,

                description=f"Sanction actuelle: {SANCTION_DISPLAY_NAMES.get(sanction_config().get(key, 'derank'), sanction_config().get(key, 'derank'))}",

                default=key == selected,

            )

            for label, key in ANTI_RAID_PROTECTIONS

        ]

        super().__init__(placeholder="Choisis une protection pour la sanction", min_values=1, max_values=1, options=options, row=1)



    async def callback(self, interaction: discord.Interaction) -> None:

        set_current_guild(interaction.guild)

        if not interaction.guild or not isinstance(interaction.user, discord.Member):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        if not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        selected = self.values[0]

        await interaction.response.edit_message(

            embed=raidstatus_embed(interaction.guild, selected),

            view=RaidStatusView(selected),

        )





class RaidStatusSanctionActionSelect(discord.ui.Select):

    def __init__(self, selected: str | None = None) -> None:

        current = sanction_config().get(selected or "", "derank")

        options = [

            discord.SelectOption(label="Ban", value="ban", default=current == "ban"),

            discord.SelectOption(label="Kick", value="kick", default=current == "kick"),

            discord.SelectOption(label="Derank", value="derank", default=current == "derank"),

            discord.SelectOption(label="Aucune", value="none", default=current == "none"),

        ]

        super().__init__(

            placeholder="Choisis la sanction",

            min_values=1,

            max_values=1,

            options=options,

            disabled=selected is None,

            row=2,

        )

        self.selected = selected



    async def callback(self, interaction: discord.Interaction) -> None:

        set_current_guild(interaction.guild)

        if not interaction.guild or not isinstance(interaction.user, discord.Member):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        if not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        if not self.selected:

            await interaction.response.send_message("Choisis d'abord une protection.", ephemeral=True)

            return

        from config_store import update_config



        update_active_config({"sanctions": {self.selected: self.values[0]}})

        await interaction.response.edit_message(

            embed=raidstatus_embed(interaction.guild, self.selected),

            view=RaidStatusView(self.selected),

        )





class RaidStatusView(discord.ui.View):

    def __init__(self, selected_sanction: str | None = None) -> None:

        super().__init__(timeout=None)

        self.add_item(RaidStatusProtectionSelect())

        self.add_item(RaidStatusSanctionProtectionSelect(selected_sanction))

        self.add_item(RaidStatusSanctionActionSelect(selected_sanction))





@bot.command(name="antiraid")

@is_admin()

async def antiraid(ctx: commands.Context) -> None:

    if not ctx.guild:

        return

    await ctx.send(embed=raidstatus_embed(ctx.guild), view=RaidStatusView())





async def set_antiraid_toggle(ctx: commands.Context, key: str, value: str) -> None:

    from config_store import update_config



    if value.lower() not in {"on", "off", "true", "false", "1", "0", "yes", "no"}:

        await ctx.reply("Utilise `on` ou `off`.")

        return

    enabled = value.lower() in {"on", "true", "1", "yes"}

    update_active_config({"anti_raid": {key: enabled}})

    label = ANTI_RAID_DISPLAY_NAMES.get(key, key)

    state = "activée" if enabled else "désactivée"

    embed = discord.Embed(

        title="Anti Raid",

        description=f"**{label}** est désormais **{state}**.",

        color=discord.Color.green() if enabled else discord.Color.red(),

    )

    await ctx.reply(embed=embed)





def antiraid_panel_embed() -> discord.Embed:

    cfg = anti_raid_config()

    lines = [f"**Global**: `{'on' if cfg.get('enabled') else 'off'}`"]

    for label, key in ANTI_RAID_PROTECTIONS:

        lines.append(f"**{label}**: `{'on' if cfg.get(key) else 'off'}`")

    embed = discord.Embed(

        title="Configuration Anti Raid",

        description="\n".join(lines),

        color=discord.Color.green() if cfg.get("enabled") else discord.Color.red(),

    )

    embed.set_footer(text="Sélectionne une protection pour l'activer ou la désactiver.")

    return embed





def captcha_panel_embed(guild: discord.Guild) -> discord.Embed:

    cfg = anti_raid_config()

    role_id = cfg.get("captcha_role_id")

    role = guild.get_role(int(role_id)) if role_id and str(role_id).isdigit() else None

    channel_id = cfg.get("captcha_channel_id")

    channel = guild.get_channel(int(channel_id)) if channel_id and str(channel_id).isdigit() else None

    embed = discord.Embed(

        title="Configuration Captcha",

        color=discord.Color.green() if cfg.get("captcha") else discord.Color.red(),

    )

    embed.add_field(name="État", value="Activé" if cfg.get("captcha") else "Désactivé", inline=True)

    embed.add_field(name="Rôle donné", value=role.mention if role else "Non configuré", inline=True)

    embed.add_field(name="Salon captcha", value=channel.mention if isinstance(channel, discord.TextChannel) else "Salon système / automatique", inline=True)

    embed.add_field(

        name="Suppression des messages",

        value="Activée" if cfg.get("captcha_delete_messages", True) else "Désactivée",

        inline=True,

    )

    pending_count = sum(1 for guild_id, _ in captcha_pending if guild_id == guild.id)

    embed.add_field(name="Captchas en attente", value=str(pending_count), inline=True)

    embed.set_footer(text="Le membre reçoit ce rôle quand il valide le code captcha.")

    return embed





async def ask_captcha_value(interaction: discord.Interaction, field: str) -> None:

    if not interaction.channel or not interaction.guild or not isinstance(interaction.user, discord.Member):

        await interaction.response.send_message("Impossible ici.", ephemeral=True)

        return

    if not await has_owner_access(interaction.user):

        await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

        return

    prompts = {
        "role": "Envoie le rôle à donner après captcha avec @role ou son ID.",
        "channel": "Envoie le salon où envoyer les codes captcha avec #salon ou son ID.",
    }
    await interaction.response.send_message(f"{prompts[field]}\nTape `cancel` pour annuler.")
    prompt_message = await interaction.original_response()



    def check(message: discord.Message) -> bool:

        return (

            message.author.id == interaction.user.id

            and message.channel.id == interaction.channel.id

            and not message.author.bot

        )



    try:

        message = await bot.wait_for("message", timeout=60, check=check)

    except asyncio.TimeoutError:

        await interaction.followup.send("Temps écoulé.", ephemeral=True)

        return



    if message.content.lower().strip() == "cancel":

        done_message = await interaction.followup.send("Annulé.", wait=True)

    else:

        if field == "role":

            role = resolve_role(interaction.guild, message.content)

            if not role:

                done_message = await interaction.followup.send("Rôle invalide.", wait=True)

            else:

                update_active_config({"anti_raid": {"captcha_role_id": str(role.id)}})

                done_message = await interaction.followup.send(f"Rôle captcha configuré: {role.mention}.", wait=True)

                if interaction.message:

                    await interaction.message.edit(embed=captcha_panel_embed(interaction.guild), view=CaptchaPanelView())

        else:

            channel = resolve_text_channel(interaction.guild, message.content)

            if not channel:

                done_message = await interaction.followup.send("Salon invalide.", wait=True)

            else:

                update_active_config({"anti_raid": {"captcha_channel_id": str(channel.id)}})

                done_message = await interaction.followup.send(f"Salon captcha configuré: {channel.mention}.", wait=True)

                if interaction.message:

                    await interaction.message.edit(embed=captcha_panel_embed(interaction.guild), view=CaptchaPanelView())


    await asyncio.sleep(2)

    for cleanup in (prompt_message, message, done_message):

        try:

            await cleanup.delete()

        except discord.HTTPException:

            pass





class CaptchaSettingsSelect(discord.ui.Select):

    def __init__(self) -> None:

        cfg = anti_raid_config()

        options = [

            discord.SelectOption(

                label="Activer/Désactiver le captcha",

                value="toggle",

                description="Actuellement ON" if cfg.get("captcha") else "Actuellement OFF",

            ),

            discord.SelectOption(

                label="Choisir le rôle donné",

                value="role",

                description="Rôle donné quand le captcha est validé",

            ),

            discord.SelectOption(

                label="Choisir le salon captcha",

                value="channel",

                description="Salon où le code sera envoyé",

            ),

            discord.SelectOption(

                label="Activer/Désactiver la suppression",

                value="toggle_delete",

                description="Supprime le message contenant le code",

            ),

            discord.SelectOption(

                label="Retirer le rôle captcha",

                value="clear_role",

                description="Aucun rôle ne sera donné après validation",

            ),

            discord.SelectOption(

                label="Vider les captchas en attente",

                value="clear_pending",

                description="Annule les codes non validés",

            ),

        ]

        super().__init__(placeholder="Configurer le captcha", min_values=1, max_values=1, options=options)



    async def callback(self, interaction: discord.Interaction) -> None:

        set_current_guild(interaction.guild)

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        choice = self.values[0]

        if choice == "toggle":

            cfg = anti_raid_config()

            update_active_config({"anti_raid": {"captcha": not cfg.get("captcha", False)}})

            await interaction.response.edit_message(embed=captcha_panel_embed(interaction.guild), view=CaptchaPanelView())

            return

        if choice == "toggle_delete":

            cfg = anti_raid_config()

            update_active_config({"anti_raid": {"captcha_delete_messages": not cfg.get("captcha_delete_messages", True)}})

            await interaction.response.edit_message(embed=captcha_panel_embed(interaction.guild), view=CaptchaPanelView())

            return

        if choice == "clear_role":

            update_active_config({"anti_raid": {"captcha_role_id": None}})

            await interaction.response.edit_message(embed=captcha_panel_embed(interaction.guild), view=CaptchaPanelView())

            return

        if choice == "clear_pending":

            for key in [key for key in captcha_pending if key[0] == interaction.guild.id]:

                captcha_pending.pop(key, None)

            await interaction.response.edit_message(embed=captcha_panel_embed(interaction.guild), view=CaptchaPanelView())

            return

        await ask_captcha_value(interaction, choice)





class CaptchaPanelView(discord.ui.View):

    def __init__(self) -> None:

        super().__init__(timeout=None)

        self.add_item(CaptchaSettingsSelect())





def giveaway_panel_embed() -> discord.Embed:

    cfg = giveaway_config()

    channel_id = cfg.get("channel_id")

    channel = bot.get_channel(int(channel_id)) if channel_id and str(channel_id).isdigit() else None

    embed = discord.Embed(title="Configuration Giveaway", color=discord.Color.blurple())

    embed.add_field(name="Titre", value=cfg.get("title") or "Giveaway", inline=True)

    embed.add_field(name="Temps", value=format_duration(int(cfg.get("duration_seconds", 3600))), inline=True)

    embed.add_field(name="Récompense", value=cfg.get("reward") or "Récompense", inline=True)

    embed.add_field(name="Couleur", value=cfg.get("color") or "#ff5ec7", inline=True)

    embed.add_field(name="Salon", value=channel.mention if isinstance(channel, discord.TextChannel) else "Salon actuel", inline=True)

    embed.add_field(name="Image", value="Configurée" if cfg.get("image_url") else "Aucune", inline=True)

    embed.add_field(name="Message de participation", value=cfg.get("participation_message") or "Vous avez été enregistré.", inline=False)

    embed.set_footer(text="Configure le giveaway puis envoie-le.")

    return embed





def giveaway_live_embed(data: dict, participants_count: int = 0, ended: bool = False, winner_id: int | None = None) -> discord.Embed:

    reward = data.get("reward") or "Récompense"

    title = data.get("title") or "Giveaway"

    duration = int(data.get("duration_seconds", 3600))

    description = (

        f"Clique sur le bouton pour participer\n"

        f"Nombre de gagnants: 1\n\n"

        f"Fin du giveaway\n"

        f"dans {format_duration(duration)}\n\n"

        f"Participants: {participants_count}"

    )

    if ended:

        description = (

            f"Gagnant(s): {f'<@{winner_id}>' if winner_id else 'Aucun'}\n"

            f"Prix: {reward}\n"

            f"Participants: {participants_count}"

        )

    embed = discord.Embed(

        title=f"{'🎉 GIVEAWAY TERMINÉ :' if ended else 'Giveaway:'} {title}",

        description=description,

        color=parse_hex_color(data.get("color") or "#ff5ec7"),

    )

    if data.get("image_url"):

        embed.set_image(url=data["image_url"])

    return embed





async def ask_giveaway_value(interaction: discord.Interaction, field: str) -> None:

    if not interaction.channel or not interaction.guild or not isinstance(interaction.user, discord.Member):

        await interaction.response.send_message("Impossible ici.", ephemeral=True)

        return

    if not await has_owner_access(interaction.user):

        await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

        return

    prompts = {

        "title": "Envoie le titre du giveaway.",

        "time": "Envoie le temps du giveaway, exemple `30m`, `2h`, `1j`.",

        "reward": "Envoie la récompense du giveaway.",

        "message": "Envoie le message affiché quand quelqu'un participe.",

        "color": "Envoie la couleur de l'embed en hex, exemple `#ff5ec7`.",

        "image": "Envoie l'URL de l'image du giveaway, ou `del` pour retirer.",

        "channel": "Envoie le salon où envoyer le giveaway avec #salon ou son ID.",

    }

    await interaction.response.send_message(f"{prompts[field]}\nTape `cancel` pour annuler.")

    prompt_message = await interaction.original_response()



    def check(message: discord.Message) -> bool:

        return message.author.id == interaction.user.id and message.channel.id == interaction.channel.id and not message.author.bot



    try:

        message = await bot.wait_for("message", timeout=90, check=check)

    except asyncio.TimeoutError:

        await interaction.followup.send("Temps écoulé.", ephemeral=True)
        
        return



    done_text = "Configuration mise à jour."
    
    if message.content.lower().strip() == "cancel":
        
        done_text = "Annulé."
        
    elif field == "title":

        update_active_config({"giveaway": {"title": message.content[:256]}})

    elif field == "time":

        seconds = parse_duration(message.content)

        if seconds is None:

            done_text = "Durée invalide."

        else:

            update_active_config({"giveaway": {"duration_seconds": seconds}})

    elif field == "reward":

        update_active_config({"giveaway": {"reward": message.content[:256]}})

    elif field == "message":

        update_active_config({"giveaway": {"participation_message": message.content[:500]}})

    elif field == "color":

        cleaned = message.content.strip()

        if not re.fullmatch(r"#?[0-9a-fA-F]{6}", cleaned):

            done_text = "Couleur invalide."

        else:

            update_active_config({"giveaway": {"color": "#" + cleaned.removeprefix("#")}})

    elif field == "image":

        value = message.content.strip()

        update_active_config({"giveaway": {"image_url": "" if value.lower() in {"del", "remove", "off"} else value}})

    elif field == "channel":

        channel = resolve_text_channel(interaction.guild, message.content)

        if not channel:

            done_text = "Salon invalide."

        else:

            update_active_config({"giveaway": {"channel_id": str(channel.id)}})



    done_message = await interaction.followup.send(done_text, wait=True)

    if interaction.message:

        await interaction.message.edit(embed=giveaway_panel_embed(), view=GiveawaySettingsView())

    await asyncio.sleep(2)

    for cleanup in (prompt_message, message, done_message):

        try:

            await cleanup.delete()

        except discord.HTTPException:

            pass





async def finish_giveaway(message_id: int, channel_id: int, reward: str) -> None:

    data = giveaway_messages.get(message_id, {})

    duration = int(data.get("duration_seconds", 0))

    if duration > 0:

        await asyncio.sleep(duration)

    channel = bot.get_channel(channel_id)

    if not isinstance(channel, discord.TextChannel):

        return

    participants = list(giveaway_participants.get(message_id, set()))

    if not participants:

        try:

            message = await channel.fetch_message(message_id)

            await message.edit(embed=giveaway_live_embed(data, 0, ended=True), view=None)

        except discord.HTTPException:

            await channel.send(f"Giveaway terminé pour **{reward}**. Aucun participant.")

        return

    winner_id = participants[int.from_bytes(os.urandom(2), "big") % len(participants)]

    try:

        message = await channel.fetch_message(message_id)

        await message.edit(embed=giveaway_live_embed(data, len(participants), ended=True, winner_id=winner_id), view=None)

    except discord.HTTPException:

        await channel.send(f"Giveaway terminé pour **{reward}**. Gagnant: <@{winner_id}>")





class GiveawayJoinView(discord.ui.View):

    def __init__(self) -> None:

        super().__init__(timeout=None)



    @discord.ui.button(label="Participer", style=discord.ButtonStyle.success, custom_id="giveaway:join")

    async def join_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:

        if not interaction.message:

            await interaction.response.send_message("Giveaway introuvable.", ephemeral=True)

            return

        giveaway_participants[interaction.message.id].add(interaction.user.id)

        data = giveaway_messages.get(interaction.message.id, giveaway_config())

        participants_count = len(giveaway_participants[interaction.message.id])

        try:

            await interaction.message.edit(embed=giveaway_live_embed(data, participants_count), view=self)

        except discord.HTTPException:

            pass

        await interaction.response.send_message(data.get("participation_message") or "Vous avez été enregistré.", ephemeral=True)





class GiveawaySettingsSelect(discord.ui.Select):

    def __init__(self) -> None:

        options = [

            discord.SelectOption(label="Modifier le titre", value="title"),

            discord.SelectOption(label="Modifier le temps", value="time"),

            discord.SelectOption(label="Modifier la récompense", value="reward"),

            discord.SelectOption(label="Modifier le message de participation", value="message"),

            discord.SelectOption(label="Modifier la couleur de l'embed", value="color"),

            discord.SelectOption(label="Ajouter une image", value="image"),

            discord.SelectOption(label="Modifier le salon", value="channel"),

            discord.SelectOption(label="Envoyer le giveaway", value="send"),

        ]

        super().__init__(placeholder="Configurer le giveaway", min_values=1, max_values=1, options=options)



    async def callback(self, interaction: discord.Interaction) -> None:

        set_current_guild(interaction.guild)

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        choice = self.values[0]

        if choice == "send":

            cfg = giveaway_config()

            duration = int(cfg.get("duration_seconds", 3600))

            reward = cfg.get("reward") or "Récompense"

            channel_id = cfg.get("channel_id")

            channel = interaction.guild.get_channel(int(channel_id)) if channel_id and str(channel_id).isdigit() else interaction.channel

            if not isinstance(channel, discord.TextChannel):

                await interaction.response.send_message("Salon giveaway invalide.", ephemeral=True)

                return

            data = {

                "duration_seconds": duration,

                "reward": reward,

                "title": cfg.get("title") or "Giveaway",

                "participation_message": cfg.get("participation_message") or "Vous avez été enregistré.",

                "color": cfg.get("color") or "#ff5ec7",

                "image_url": cfg.get("image_url") or "",

            }

            sent = await channel.send(embed=giveaway_live_embed(data, 0), view=GiveawayJoinView())

            await interaction.response.send_message(f"Giveaway envoyé dans {channel.mention}.", ephemeral=True)

            giveaway_messages[sent.id] = {

                **data,

            }

            asyncio.create_task(finish_giveaway(sent.id, sent.channel.id, reward))

            return

        await ask_giveaway_value(interaction, choice)





class GiveawaySettingsView(discord.ui.View):

    def __init__(self) -> None:

        super().__init__(timeout=None)

        self.add_item(GiveawaySettingsSelect())





class AntiRaidToggleSelect(discord.ui.Select):

    def __init__(self) -> None:

        cfg = anti_raid_config()

        global_enabled = all(cfg.get(key, False) for key in ANTI_RAID_KEYS)

        options = [

            discord.SelectOption(

                label=f"Global {'ON' if global_enabled else 'OFF'}",

                value="global",

                description="Active ou désactive toutes les protections",

                emoji="🛡️",

            )

        ]

        options.extend(

            discord.SelectOption(

                label=label,

                value=key,

                description=f"Actuel: {'on' if cfg.get(key) else 'off'}",

                emoji="✅" if cfg.get(key) else "❌",

            )

            for label, key in ANTI_RAID_PROTECTIONS

        )

        super().__init__(placeholder="Sélectionne une protection", min_values=1, max_values=1, options=options)



    async def callback(self, interaction: discord.Interaction) -> None:

        set_current_guild(interaction.guild)

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        key = self.values[0]

        cfg = anti_raid_config()

        from config_store import update_config



        if key == "global":

            enabled = not all(cfg.get(item, False) for item in ANTI_RAID_KEYS)

            update_active_config({"anti_raid": {item: enabled for item in ANTI_RAID_KEYS}})

        else:

            update_active_config({"anti_raid": {key: not cfg.get(key, False)}})

        await interaction.response.edit_message(embed=antiraid_panel_embed(), view=AntiRaidPanelView())





class AntiRaidPanelView(discord.ui.View):

    def __init__(self) -> None:

        super().__init__(timeout=None)

        self.add_item(AntiRaidToggleSelect())





def sanction_panel_embed(selected: str | None = None) -> discord.Embed:

    sanctions = sanction_config()

    lines = []

    for label, key in ANTI_RAID_PROTECTIONS:

        marker = " ←" if key == selected else ""

        lines.append(f"{marker} **{label}**: `{sanctions.get(key, 'derank')}`")

    embed = discord.Embed(

        title="Configuration des sanctions",

        description="\n".join(lines),

        color=discord.Color.orange(),

    )

    embed.set_footer(text="Choisis une protection, puis choisis ban/kick/derank/none.")

    return embed





class SanctionProtectionSelect(discord.ui.Select):

    def __init__(self, selected: str | None = None) -> None:

        options = [

            discord.SelectOption(

                label=label,

                value=key,

                description=f"Sanction actuelle: {sanction_config().get(key, 'derank')}",

                default=key == selected,

            )

            for label, key in ANTI_RAID_PROTECTIONS

        ]

        super().__init__(placeholder="Choisis une protection", min_values=1, max_values=1, options=options, row=0)



    async def callback(self, interaction: discord.Interaction) -> None:

        set_current_guild(interaction.guild)

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        selected = self.values[0]

        await interaction.response.edit_message(embed=sanction_panel_embed(selected), view=SanctionPanelView(selected))





class SanctionActionSelect(discord.ui.Select):

    def __init__(self, selected: str | None = None) -> None:

        current = sanction_config().get(selected or "", "derank")

        options = [

            discord.SelectOption(label="Ban", value="ban", default=current == "ban"),

            discord.SelectOption(label="Kick", value="kick", default=current == "kick"),

            discord.SelectOption(label="Derank", value="derank", default=current == "derank"),

            discord.SelectOption(label="Aucune", value="none", default=current == "none"),

        ]

        disabled = selected is None

        super().__init__(

            placeholder="Choisis la sanction",

            min_values=1,

            max_values=1,

            options=options,

            disabled=disabled,

            row=1,

        )

        self.selected = selected



    async def callback(self, interaction: discord.Interaction) -> None:

        set_current_guild(interaction.guild)

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        if not self.selected:

            await interaction.response.send_message("Choisis d'abord une protection.", ephemeral=True)

            return

        action = self.values[0]

        from config_store import update_config



        update_active_config({"sanctions": {self.selected: action}})

        await interaction.response.edit_message(embed=sanction_panel_embed(self.selected), view=SanctionPanelView(self.selected))





class SanctionPanelView(discord.ui.View):

    def __init__(self, selected: str | None = None) -> None:

        super().__init__(timeout=None)

        self.add_item(SanctionProtectionSelect(selected))

        self.add_item(SanctionActionSelect(selected))





@bot.command(name="autologs")

@is_admin()

async def autologs(ctx: commands.Context) -> None:

    created = await ensure_auto_logs(ctx.guild, ctx.author)

    await ctx.reply("Salons de logs créés/configurés." + (f"\n{', '.join(created)}" if created else ""))





async def ensure_auto_logs(guild: discord.Guild, author: discord.abc.User) -> list[str]:

    category = discord.utils.get(guild.categories, name="Logs")

    if category is None:

        category = await guild.create_category("Logs", reason=f"Autologs par {author}")



    names = {

        "logs-raid": "Logs anti-raid",

        "logs-moderation": "Logs modération",

        "logs-messages": "Logs messages",

        "logs-roles": "Logs rôles",

        "logs-vocaux": "Logs vocaux",

        "logs-boost": "Logs boost",

        "logs-captcha": "Logs captcha",

    }

    created = []

    for channel_name in names:

        channel = discord.utils.get(guild.text_channels, name=channel_name)

        if channel is None:

            channel = await guild.create_text_channel(channel_name, category=category, reason=f"Autologs par {author}")

            created.append(channel.mention)



    raid_channel = discord.utils.get(guild.text_channels, name="logs-raid")

    if raid_channel:

        from config_store import update_config



        update_active_config({"anti_raid": {"log_channel_id": str(raid_channel.id)}})



    return created





def logconfig_embed(guild: discord.Guild) -> discord.Embed:

    cfg = anti_raid_config()

    raid_channel = guild.get_channel(int(cfg["log_channel_id"])) if cfg.get("log_channel_id") else None

    names = [

        "logs-raid",

        "logs-moderation",

        "logs-messages",

        "logs-roles",

        "logs-vocaux",

        "logs-boost",

        "logs-captcha",

    ]

    lines = []

    for name in names:

        channel = discord.utils.get(guild.text_channels, name=name)

        lines.append(f"`{name}` : {channel.mention if channel else 'Non créé'}")

    embed = discord.Embed(

        title="📋 Configuration des logs",

        description="Gère les salons de logs depuis le menu.",

        color=discord.Color.blurple(),

    )

    embed.add_field(name="Salon anti-raid actif", value=raid_channel.mention if isinstance(raid_channel, discord.TextChannel) else "Non configuré", inline=False)

    embed.add_field(name="Salons disponibles", value="\n".join(lines), inline=False)

    return embed





class LogConfigSelect(discord.ui.Select):

    def __init__(self) -> None:

        options = [

            discord.SelectOption(label="📁 Créer les salons de logs", value="create"),

            discord.SelectOption(label="🛡️ Mettre logs-raid en salon anti-raid", value="raid"),

            discord.SelectOption(label="🧹 Désactiver le salon anti-raid", value="clear_raid"),

        ]

        super().__init__(placeholder="📋 Gérer les logs", min_values=1, max_values=1, options=options)



    async def callback(self, interaction: discord.Interaction) -> None:

        set_current_guild(interaction.guild)

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        choice = self.values[0]

        if choice == "create":

            created = await ensure_auto_logs(interaction.guild, interaction.user)

            message = "Salons de logs créés/configurés." + (f"\n{', '.join(created)}" if created else "")

            await interaction.response.send_message(message, ephemeral=True)

        elif choice == "raid":

            channel = discord.utils.get(interaction.guild.text_channels, name="logs-raid")

            if not channel:

                await interaction.response.send_message("Le salon `logs-raid` n'existe pas. Lance d'abord la création des salons.", ephemeral=True)

                return

            update_active_config({"anti_raid": {"log_channel_id": str(channel.id)}})

            await interaction.response.send_message(f"Salon anti-raid configuré sur {channel.mention}.", ephemeral=True)

        else:

            update_active_config({"anti_raid": {"log_channel_id": None}})

            await interaction.response.send_message("Salon anti-raid désactivé.", ephemeral=True)

        if interaction.message:

            await interaction.message.edit(embed=logconfig_embed(interaction.guild), view=LogConfigView())





class LogConfigView(discord.ui.View):

    def __init__(self) -> None:

        super().__init__(timeout=None)

        self.add_item(LogConfigSelect())





@bot.command(name="logconfig")

@is_admin()

async def logconfig(ctx: commands.Context) -> None:

    await ctx.send(embed=logconfig_embed(ctx.guild), view=LogConfigView())





def bool_icon(value: bool) -> str:

    return "✅" if value else "❌"





def join_settings_embed(guild: discord.Guild) -> discord.Embed:

    settings = server_settings_config()

    join_channel = guild.get_channel(int(settings["join_channel_id"])) if settings.get("join_channel_id") else None

    leave_channel = guild.get_channel(int(settings["leave_channel_id"])) if settings.get("leave_channel_id") else None

    ghost_channel = guild.get_channel(int(settings["ghost_join_channel_id"])) if settings.get("ghost_join_channel_id") else None

    ghost_role = guild.get_role(int(settings["ghost_join_role_id"])) if settings.get("ghost_join_role_id") else None

    join_message = settings.get("join_message") or "Non configuré"

    leave_message = settings.get("leave_message") or "Non configuré"

    ghost_text = (

        f"{ghost_role.mention} dans {ghost_channel.mention}"

        if ghost_role and isinstance(ghost_channel, discord.TextChannel)

        else "Aucun"

    )

    embed = discord.Embed(

        title=f"Join settings de {guild.name}",

        color=discord.Color.blurple(),

    )

    embed.add_field(name="MP de join", value="Non configuré", inline=True)

    embed.add_field(name="Message de join", value=join_message, inline=True)

    embed.add_field(

        name="Channel de join",

        value=join_channel.mention if isinstance(join_channel, discord.TextChannel) else "Non configuré",

        inline=True,

    )

    embed.add_field(

        name="Channel de leave",

        value=leave_channel.mention if isinstance(leave_channel, discord.TextChannel) else "Non configuré",

        inline=True,

    )

    embed.add_field(name="Message de leave", value=leave_message, inline=True)

    embed.add_field(name="Join embed", value=bool_icon(settings.get("join_embed_enabled", False)), inline=True)

    embed.add_field(name="Leave embed", value=bool_icon(settings.get("leave_embed_enabled", False)), inline=True)

    embed.add_field(name="Couleur join", value=settings.get("join_embed_color") or "#ff5ec7", inline=True)

    embed.add_field(name="Couleur leave", value=settings.get("leave_embed_color") or "#ff5ec7", inline=True)

    embed.add_field(name="Ghost join", value=ghost_text, inline=True)

    embed.set_footer(text="Server Settings")

    return embed





def format_join_message(template: str, member: discord.Member, inviter: str = "Inconnu", invite_count: int = 0) -> str:

    values = {

        "member": member.mention,

        "server": member.guild.name,

        "member_count": member.guild.member_count or len(member.guild.members),

        "join_count": 1,

        "user_created_at": discord.utils.format_dt(member.created_at, "R"),

        "inviter": inviter,

        "invite_count": invite_count,

    }

    try:

        return template.format(**values)

    except (KeyError, ValueError):

        return template





async def ask_server_setting_value(interaction: discord.Interaction, field: str) -> None:

    if not interaction.channel or not interaction.guild or not isinstance(interaction.user, discord.Member):

        await interaction.response.send_message("Impossible ici.", ephemeral=True)

        return

    if not await has_owner_access(interaction.user):

        await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

        return



    prompts = {

        "join_channel": "Envoie le salon de join avec #salon, son ID, ou `del` pour retirer.",

        "join_message": "Envoie le message de join. Variables: `{member}`, `{server}`, `{member_count}`, `{user_created_at}`, `{join_count}`, `{inviter}`, `{invite_count}`.",

        "join_color": "Envoie une couleur hexadécimale, exemple `#ff5ec7`.",

        "leave_channel": "Envoie le salon de leave avec #salon, son ID, ou `del` pour retirer.",

        "leave_message": "Envoie le message de leave. Variables: `{member}`, `{server}`, `{member_count}`, `{user_created_at}`.",

        "leave_color": "Envoie une couleur hexadécimale, exemple `#ff5ec7`.",

    }

    await interaction.response.send_message(f"{prompts[field]}\nTape `cancel` pour annuler.")

    prompt_message = await interaction.original_response()



    def check(message: discord.Message) -> bool:

        return (

            message.author.id == interaction.user.id

            and message.channel.id == interaction.channel.id

            and not message.author.bot

        )



    try:

        message = await bot.wait_for("message", check=check, timeout=60)

    except asyncio.TimeoutError:

        timeout_message = await interaction.followup.send("Temps expiré, modification annulée.", wait=True)

        await asyncio.sleep(3)

        for cleanup in (prompt_message, timeout_message):

            try:

                await cleanup.delete()

            except discord.HTTPException:

                pass

        return



    value = message.content.strip()

    if value.lower() == "cancel":

        cancel_message = await interaction.followup.send("Modification annulée.", wait=True)

        await asyncio.sleep(2)

        for cleanup in (prompt_message, message, cancel_message):

            try:

                await cleanup.delete()

            except discord.HTTPException:

                pass

        return



    done_text = "Configuration modifiée."

    if field == "join_channel":

        if value.lower() in {"del", "delete", "remove", "off"}:

            update_server_settings({"join_channel_id": None})

        else:

            channel = resolve_text_channel(interaction.guild, value)

            if not channel:

                done_text = "Salon invalide."

            else:

                update_server_settings({"join_channel_id": str(channel.id)})

    elif field == "join_message":

        update_server_settings({"join_message": value})

    elif field == "join_color":

        cleaned = value.strip()

        if not re.fullmatch(r"#?[0-9a-fA-F]{6}", cleaned):

            done_text = "Couleur invalide."

        else:

            update_server_settings({"join_embed_color": "#" + cleaned.removeprefix("#")})

    elif field == "leave_channel":

        if value.lower() in {"del", "delete", "remove", "off"}:

            update_server_settings({"leave_channel_id": None})

        else:

            channel = resolve_text_channel(interaction.guild, value)

            if not channel:

                done_text = "Salon invalide."

            else:

                update_server_settings({"leave_channel_id": str(channel.id)})

    elif field == "leave_message":

        update_server_settings({"leave_message": value})

    elif field == "leave_color":

        cleaned = value.strip()

        if not re.fullmatch(r"#?[0-9a-fA-F]{6}", cleaned):

            done_text = "Couleur invalide."

        else:

            update_server_settings({"leave_embed_color": "#" + cleaned.removeprefix("#")})



    done_message = await interaction.followup.send(done_text, wait=True)

    if interaction.message:

        await interaction.message.edit(embed=join_settings_embed(interaction.guild), view=ServerSettingsView())

    await asyncio.sleep(2)

    for cleanup in (prompt_message, message, done_message):

        try:

            await cleanup.delete()

        except discord.HTTPException:

            pass





class ServerSettingsSelect(discord.ui.Select):

    def __init__(self) -> None:

        options = [

            discord.SelectOption(label="Modifier le salon de join", value="join_channel"),

            discord.SelectOption(label="Modifier le message de join", value="join_message"),

            discord.SelectOption(label="Modifier la couleur join", value="join_color"),

            discord.SelectOption(label="Activer/Désactiver l'embed de join", value="toggle_join_embed"),

            discord.SelectOption(label="Modifier le salon de leave", value="leave_channel"),

            discord.SelectOption(label="Modifier le message de leave", value="leave_message"),

            discord.SelectOption(label="Modifier la couleur leave", value="leave_color"),

            discord.SelectOption(label="Activer/Désactiver l'embed de leave", value="toggle_leave_embed"),

        ]

        super().__init__(placeholder="Gérer les paramètres du serveur", min_values=1, max_values=1, options=options)



    async def callback(self, interaction: discord.Interaction) -> None:

        set_current_guild(interaction.guild)

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        choice = self.values[0]

        if choice == "toggle_join_embed":

            settings = server_settings_config()

            update_server_settings({"join_embed_enabled": not settings.get("join_embed_enabled", False)})

            await interaction.response.edit_message(embed=join_settings_embed(interaction.guild), view=ServerSettingsView())

            return

        if choice == "toggle_leave_embed":

            settings = server_settings_config()

            update_server_settings({"leave_embed_enabled": not settings.get("leave_embed_enabled", False)})

            await interaction.response.edit_message(embed=join_settings_embed(interaction.guild), view=ServerSettingsView())

            return

        await ask_server_setting_value(interaction, choice)





class ServerSettingsView(discord.ui.View):

    def __init__(self) -> None:

        super().__init__(timeout=None)

        self.add_item(ServerSettingsSelect())





def react_role_embed(guild: discord.Guild) -> discord.Embed:

    cfg = react_role_config()

    channel = guild.get_channel(int(cfg["channel_id"])) if cfg.get("channel_id") else None

    role = guild.get_role(int(cfg["role_id"])) if cfg.get("role_id") else None

    embed = discord.Embed(title="React Role settings", color=parse_hex_color(cfg.get("color") or "#ff5ec7"))

    embed.add_field(name="Salon", value=channel.mention if isinstance(channel, discord.TextChannel) else "Non configuré", inline=True)

    embed.add_field(name="Rôle attribué", value=role.mention if role else "Non configuré", inline=True)

    embed.add_field(name="Réaction", value=cfg.get("emoji") or "✅", inline=True)

    embed.add_field(name="Couleur embed", value=cfg.get("color") or "#ff5ec7", inline=True)

    embed.add_field(name="Message ID", value=str(cfg.get("message_id") or "Non envoyé"), inline=True)

    embed.add_field(name="Titre", value=cfg.get("title") or "Vérification", inline=False)

    embed.add_field(name="Description", value=cfg.get("description") or "Non configuré", inline=False)

    embed.set_footer(text="React Role")

    return embed





def react_role_panel_embed() -> discord.Embed:

    cfg = react_role_config()

    emoji = cfg.get("emoji") or "✅"

    return discord.Embed(

        title=cfg.get("title") or "Vérification",

        description=(cfg.get("description") or "Réagis avec {emoji} pour obtenir le rôle.").replace("{emoji}", emoji),

        color=parse_hex_color(cfg.get("color") or "#ff5ec7"),

    )





async def send_react_role_panel(guild: discord.Guild) -> tuple[bool, str]:

    cfg = react_role_config()

    channel = guild.get_channel(int(cfg["channel_id"])) if cfg.get("channel_id") else None

    role = guild.get_role(int(cfg["role_id"])) if cfg.get("role_id") else None

    if not isinstance(channel, discord.TextChannel):

        return False, "Salon react role non configuré."

    if not role:

        return False, "Rôle react role non configuré."

    allowed, reason = can_assign_role(guild, role)

    if not allowed:

        return False, reason

    message = await channel.send(embed=react_role_panel_embed())

    await message.add_reaction(cfg.get("emoji") or "✅")

    update_react_role_config({"message_id": str(message.id), "channel_id": str(channel.id)})

    return True, f"Panneau envoyé: {message.jump_url}"





async def apply_react_role_access(guild: discord.Guild) -> tuple[int, str]:

    cfg = react_role_config()

    role = guild.get_role(int(cfg["role_id"])) if cfg.get("role_id") else None

    if not role:

        return 0, "Rôle react role non configuré."

    if not guild.me or not guild.me.guild_permissions.manage_channels:

        return 0, "Il me manque la permission Gérer les salons."

    changed = 0

    for channel in list(guild.channels):

        try:

            await channel.set_permissions(guild.default_role, view_channel=False, reason="Reactrole access")

            await channel.set_permissions(role, view_channel=True, read_message_history=True, reason="Reactrole access")

            changed += 1

            await asyncio.sleep(0.2)

        except discord.HTTPException:

            continue

    return changed, f"Accès configuré sur {changed} salons."





async def ask_react_role_value(interaction: discord.Interaction, field: str) -> None:

    if not interaction.channel or not interaction.guild or not isinstance(interaction.user, discord.Member):

        await interaction.response.send_message("Impossible ici.", ephemeral=True)

        return

    if not await has_owner_access(interaction.user):

        await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

        return

    prompts = {

        "channel": "Envoie le salon avec #salon, son ID, ou son nom.",

        "role": "Envoie le rôle à attribuer avec @role, son ID, ou son nom.",

        "emoji": "Envoie l'emoji à utiliser pour la réaction.",

        "title": "Envoie le titre de l'embed.",

        "description": "Envoie la description de l'embed. Tu peux utiliser `{emoji}`.",

        "color": "Envoie une couleur hexadécimale, exemple `#ff5ec7`.",

    }

    await interaction.response.send_message(f"{prompts[field]}\nTape `cancel` pour annuler.")

    prompt_message = await interaction.original_response()



    def check(message: discord.Message) -> bool:

        return message.author.id == interaction.user.id and message.channel.id == interaction.channel.id and not message.author.bot



    try:

        message = await bot.wait_for("message", check=check, timeout=60)

    except asyncio.TimeoutError:

        timeout_message = await interaction.followup.send("Temps expiré, modification annulée.", wait=True)

        await asyncio.sleep(3)

        for cleanup in (prompt_message, timeout_message):

            try:

                await cleanup.delete()

            except discord.HTTPException:

                pass

        return



    value = message.content.strip()

    if value.lower() == "cancel":

        cancel_message = await interaction.followup.send("Modification annulée.", wait=True)

        await asyncio.sleep(2)

        for cleanup in (prompt_message, message, cancel_message):

            try:

                await cleanup.delete()

            except discord.HTTPException:

                pass

        return



    done_text = "Configuration modifiée."

    if field == "channel":

        channel = resolve_text_channel(interaction.guild, value)

        if not channel:

            done_text = "Salon invalide."

        else:

            update_react_role_config({"channel_id": str(channel.id)})

    elif field == "role":

        role = resolve_role(interaction.guild, value)

        if not role:

            done_text = "Rôle invalide."

        else:

            allowed, reason = can_assign_role(interaction.guild, role)

            if not allowed:

                done_text = reason

            else:

                update_react_role_config({"role_id": str(role.id)})

    elif field == "color":

        if not re.fullmatch(r"#?[0-9a-fA-F]{6}", value):

            done_text = "Couleur invalide."

        else:

            update_react_role_config({"color": "#" + value.removeprefix("#")})

    else:

        update_react_role_config({field: value})



    done_message = await interaction.followup.send(done_text, wait=True)

    if interaction.message:

        await interaction.message.edit(embed=react_role_embed(interaction.guild), view=ReactRoleSettingsView())

    await asyncio.sleep(2)

    for cleanup in (prompt_message, message, done_message):

        try:

            await cleanup.delete()

        except discord.HTTPException:

            pass





class ReactRoleSelect(discord.ui.Select):

    def __init__(self) -> None:

        options = [

            discord.SelectOption(label="Choisir le salon", value="channel"),

            discord.SelectOption(label="Choisir le rôle attribué", value="role"),

            discord.SelectOption(label="Modifier la réaction", value="emoji"),

            discord.SelectOption(label="Modifier le titre", value="title"),

            discord.SelectOption(label="Modifier le message", value="description"),

            discord.SelectOption(label="Modifier la couleur d'embed", value="color"),

            discord.SelectOption(label="Envoyer le panneau", value="send"),

            discord.SelectOption(label="Configurer accès serveur", value="access"),

        ]

        super().__init__(placeholder="Gérer le react role", min_values=1, max_values=1, options=options)



    async def callback(self, interaction: discord.Interaction) -> None:

        set_current_guild(interaction.guild)

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        choice = self.values[0]

        if choice == "send":

            ok, message = await send_react_role_panel(interaction.guild)

            await interaction.response.send_message(message, ephemeral=not ok)

            if interaction.message:

                await interaction.message.edit(embed=react_role_embed(interaction.guild), view=ReactRoleSettingsView())

            return

        if choice == "access":

            await interaction.response.defer(ephemeral=True, thinking=True)

            _, message = await apply_react_role_access(interaction.guild)

            await interaction.followup.send(message, ephemeral=True)

            return

        await ask_react_role_value(interaction, choice)





class ReactRoleSettingsView(discord.ui.View):

    def __init__(self) -> None:

        super().__init__(timeout=None)

        self.add_item(ReactRoleSelect())





@bot.command(name="joinsettings", aliases=["serversettings", "serversetting"])

@is_admin()

async def joinsettings(ctx: commands.Context) -> None:

    await ctx.send(embed=join_settings_embed(ctx.guild), view=ServerSettingsView())





@bot.command(name="ghostjoin", aliases=["ghodtjoin"])

@is_admin()

async def ghostjoin(ctx: commands.Context, role_value: str, channel_value: str) -> None:

    role = resolve_role(ctx.guild, role_value)

    channel = resolve_text_channel(ctx.guild, channel_value)

    if not role:

        await ctx.reply("Rôle invalide.")

        return

    if not channel:

        await ctx.reply("Salon invalide.")

        return

    update_server_settings({

        "ghost_join_role_id": str(role.id),

        "ghost_join_channel_id": str(channel.id),

    })

    await ctx.reply(f"Ghost join configuré: {role.mention} dans {channel.mention}.")





@bot.command(name="joinrole")

@is_admin()

async def joinrole(ctx: commands.Context, action: str, *, role_value: str | None = None) -> None:

    action = action.lower()

    settings = server_settings_config()

    role_ids = {str(item) for item in settings.get("join_role_ids", [])}



    if action not in {"add", "remove"}:

        await ctx.reply(embed=clean_status_embed("Joinrole", "Utilise `.joinrole <add/remove> <rôle>`."))

        return

    if not role_value:

        await ctx.reply(embed=clean_status_embed("Joinrole", "Rôle manquant.", discord.Color.red()))

        return



    role = resolve_role(ctx.guild, role_value)

    if not role:

        await ctx.reply(embed=clean_status_embed("Joinrole", "Rôle invalide.", discord.Color.red()))

        return

    if action == "add":

        allowed, reason = can_assign_role(ctx.guild, role)

        if not allowed:

            await ctx.reply(embed=clean_status_embed("Joinrole", reason, discord.Color.red()))

            return

        role_ids.add(str(role.id))

        message = f"{role.mention} sera ajouté aux nouveaux membres."

    else:

        role_ids.discard(str(role.id))

        message = f"{role.mention} ne sera plus ajouté aux nouveaux membres."



    update_server_settings({"join_role_ids": sorted(role_ids)})

    await ctx.reply(embed=clean_status_embed("Joinrole", message, discord.Color.green()))





@bot.command(name="setperm")

@can_use("setperm")

async def setperm(ctx: commands.Context, command_name: str, role_value: str) -> None:

    await update_command_permission(ctx, command_name, role_value, True)





@bot.command(name="unsetperm")

@can_use("unsetperm")

async def unsetperm(ctx: commands.Context, command_name: str, role_value: str) -> None:

    await update_command_permission(ctx, command_name, role_value, False)





@bot.command(name="bl")

@is_admin()

async def blacklist_add(ctx: commands.Context, user_value: str, *, reason: str = "Blacklist") -> None:

    user_id = normalize_user_id(user_value)

    if not user_id:

        await ctx.reply("ID ou mention invalide.")

        return

    from config_store import update_config



    blacklist = {str(item) for item in access_config().get("blacklist", [])}

    blacklist.add(str(user_id))

    update_active_config({"access": {"blacklist": sorted(blacklist)}})

    try:

        await ctx.guild.ban(discord.Object(id=user_id), reason=f"{reason} - par {ctx.author}", delete_message_seconds=0)

    except discord.HTTPException as error:

        await ctx.reply(f"Blacklist ajoutée, mais ban impossible: `{error}`")

        return

    await ctx.reply(f"<@{user_id}> (`{user_id}`) ajouté à la blacklist et banni.")





@bot.command(name="unbl")

@is_admin()

async def blacklist_remove(ctx: commands.Context, user_value: str) -> None:

    user_id = normalize_user_id(user_value)

    if not user_id:

        await ctx.reply("ID ou mention invalide.")

        return

    from config_store import update_config



    blacklist = {str(item) for item in access_config().get("blacklist", [])}

    blacklist.discard(str(user_id))

    update_active_config({"access": {"blacklist": sorted(blacklist)}})

    await ctx.reply(f"<@{user_id}> (`{user_id}`) retiré de la blacklist.")





@bot.command(name="bllist")

@is_admin()

async def blacklist_list(ctx: commands.Context) -> None:

    blacklist = access_config().get("blacklist", [])

    text = "\n".join(f"<@{item}> (`{item}`)" for item in blacklist) if blacklist else "Aucun utilisateur blacklisté."

    await ctx.send(text)





async def update_access_list(ctx: commands.Context, list_name: str, user_value: str, add: bool) -> None:

    from config_store import update_config



    user_id = normalize_user_id(user_value)

    if not user_id:

        await ctx.reply("ID ou mention invalide.")

        return



    access = access_config()

    values = {str(item) for item in access.get(list_name, [])}

    label = {"owners": "owner", "buyers": "buyer", "whitelist": "wl"}.get(list_name, list_name.rstrip("s"))

    if add:

        values.add(str(user_id))

        message = f"cet utilisateur est {label}."

    else:

        values.discard(str(user_id))

        message = f"cet utilisateur n'est plus {label}."



    update_active_config({"access": {list_name: sorted(values)}})

    await ctx.reply(message)





@bot.command(name="owner")

@is_buyer()

async def owner_add(ctx: commands.Context, user: str) -> None:

    await update_access_list(ctx, "owners", user, True)





@bot.command(name="unowner")

@is_buyer()

async def owner_remove(ctx: commands.Context, user: str) -> None:

    await update_access_list(ctx, "owners", user, False)





@bot.command(name="ownerlist")

@is_buyer()

async def owner_list(ctx: commands.Context) -> None:

    owners = access_config().get("owners", [])

    text = "\n".join(f"<@{item}> (`{item}`)" for item in owners) if owners else "Aucun owner configuré."

    await ctx.send(text)





@bot.command(name="wl")

@is_admin()

async def whitelist_add(ctx: commands.Context, user: str) -> None:

    await update_access_list(ctx, "whitelist", user, True)





@bot.command(name="unwl")

@is_admin()

async def whitelist_remove(ctx: commands.Context, user: str) -> None:

    await update_access_list(ctx, "whitelist", user, False)





@bot.command(name="wllist")

@is_admin()

async def whitelist_list(ctx: commands.Context) -> None:

    whitelist = access_config().get("whitelist", [])

    text = "\n".join(f"<@{item}> (`{item}`)" for item in whitelist) if whitelist else "Aucun utilisateur whitelist."

    await ctx.send(text)





@bot.command(name="wlrole")

@is_admin()

async def whitelist_role_add(ctx: commands.Context, *, role_value: str) -> None:

    role = resolve_role(ctx.guild, role_value)

    if not role:

        await ctx.reply("Rôle invalide.")

        return

    access = access_config()

    values = {str(item) for item in access.get("whitelist_roles", [])}

    values.add(str(role.id))

    update_active_config({"access": {"whitelist_roles": sorted(values)}})

    await ctx.reply(f"Le rôle {role.mention} est désormais WL.")





@bot.command(name="unwlrole")

@is_admin()

async def whitelist_role_remove(ctx: commands.Context, *, role_value: str) -> None:

    role = resolve_role(ctx.guild, role_value)

    if not role:

        await ctx.reply("Rôle invalide.")

        return

    values = {str(item) for item in access_config().get("whitelist_roles", [])}

    values.discard(str(role.id))

    update_active_config({"access": {"whitelist_roles": sorted(values)}})

    await ctx.reply(f"Le rôle {role.mention} n'est plus WL.")





@bot.command(name="wlrolelist")

@is_admin()

async def whitelist_role_list(ctx: commands.Context) -> None:

    role_ids = access_config().get("whitelist_roles", [])

    text = "\n".join(f"<@&{item}> (`{item}`)" for item in role_ids) if role_ids else "Aucun rôle WL."

    await ctx.send(text)





@bot.command(name="buyer")

@is_buyer()

async def buyer_add(ctx: commands.Context, user: str) -> None:

    await update_access_list(ctx, "buyers", user, True)





@bot.command(name="unbuyer")

@is_buyer()

async def buyer_remove(ctx: commands.Context, user: str) -> None:

    await update_access_list(ctx, "buyers", user, False)





@bot.command(name="buyerlist")

@is_buyer()

async def buyer_list(ctx: commands.Context) -> None:

    buyers = access_config().get("buyers", [])

    text = "\n".join(f"<@{item}> (`{item}`)" for item in buyers) if buyers else "Aucun buyer configuré."

    await ctx.send(text)


@bot.command(name="antilink")

@is_admin()

async def antilink(ctx: commands.Context, value: str) -> None:

    await set_antiraid_toggle(ctx, "antilink", value)





@bot.command(name="antiinvite")

@is_admin()

async def antiinvite(ctx: commands.Context, value: str) -> None:

    await set_antiraid_toggle(ctx, "antiinvite", value)



@bot.command(name="antimention")

@is_admin()

async def antimention(ctx: commands.Context, amount: int) -> None:

    amount = max(0, min(amount, 50))

    update_active_config({"anti_raid": {"antimention": amount > 0, "antimention_limit": amount}})

    if amount <= 0:

        await ctx.reply(embed=clean_status_embed("Anti Raid", "**Anti Mention** est désormais **désactivée**.", discord.Color.red()))

        return

    await ctx.reply(embed=clean_status_embed("Anti Raid", f"**Anti Mention** est désormais **activée** à partir de `{amount}` mention(s).", discord.Color.green()))



@bot.command(name="antialt")

@is_admin()

async def antialt(ctx: commands.Context, days: int) -> None:

    days = max(0, min(days, 365))

    update_active_config({"anti_raid": {"antialt": days > 0, "antialt_days": days}})

    if days <= 0:

        await ctx.reply(embed=clean_status_embed("Anti Raid", "**Anti Alt** est désormais **désactivée**.", discord.Color.red()))

        return

    await ctx.reply(embed=clean_status_embed("Anti Raid", f"**Anti Alt** bloque désormais les comptes de moins de `{days}` jour(s).", discord.Color.green()))



@bot.command(name="antieveryone")

@is_admin()

async def antieveryone(ctx: commands.Context, value: str) -> None:

    await set_antiraid_toggle(ctx, "antieveryone", value)





@bot.command(name="antiban")

@is_admin()

async def antiban(ctx: commands.Context, value: str) -> None:

    await set_antiraid_toggle(ctx, "antiban", value)





@bot.command(name="antiunban")

@is_admin()

async def antiunban(ctx: commands.Context, value: str) -> None:

    await set_antiraid_toggle(ctx, "antiunban", value)





@bot.command(name="antikick")

@is_admin()

async def antikick(ctx: commands.Context, value: str) -> None:

    await set_antiraid_toggle(ctx, "antikick", value)





@bot.command(name="antibot")

@is_admin()

async def antibot(ctx: commands.Context, value: str) -> None:

    await set_antiraid_toggle(ctx, "antibot", value)





@bot.command(name="antiaddrole")

@is_admin()

async def antiaddrole(ctx: commands.Context, value: str) -> None:

    await set_antiraid_toggle(ctx, "antiaddrole", value)





@bot.command(name="antirole")

@is_admin()

async def antirole(ctx: commands.Context, value: str) -> None:

    await set_antiraid_toggle(ctx, "antiaddrole", value)





@bot.command(name="antidelrole")

@is_admin()

async def antidelrole(ctx: commands.Context, value: str) -> None:

    await set_antiraid_toggle(ctx, "antidelrole", value)





@bot.command(name="antichannel")

@is_admin()

async def antichannel(ctx: commands.Context, value: str) -> None:

    await set_antiraid_toggle(ctx, "antichannel", value)





@bot.command(name="antiwebhook")

@is_admin()

async def antiwebhook(ctx: commands.Context, value: str) -> None:

    await set_antiraid_toggle(ctx, "antiwebhook", value)





@bot.command(name="antitoken")

@is_admin()

async def antitoken(ctx: commands.Context, value: str) -> None:

    await set_antiraid_toggle(ctx, "antitoken", value)





@bot.command(name="antispam")

@is_admin()

async def antispam(ctx: commands.Context, value: str) -> None:

    await set_antiraid_toggle(ctx, "antispam", value)





@bot.command(name="antithread")

@is_admin()

async def antithread(ctx: commands.Context, value: str) -> None:

    await set_antiraid_toggle(ctx, "antithread", value)



@bot.command(name="antiemoji")

@is_admin()

async def antiemoji(ctx: commands.Context, value: str) -> None:

    await set_antiraid_toggle(ctx, "antiemoji", value)



@bot.command(name="antisticker")

@is_admin()

async def antisticker(ctx: commands.Context, value: str) -> None:

    await set_antiraid_toggle(ctx, "antisticker", value)



@bot.command(name="antiroleperm")

@is_admin()

async def antiroleperm(ctx: commands.Context, value: str) -> None:

    await set_antiraid_toggle(ctx, "antiroleperm", value)



@bot.command(name="antiadmin")

@is_admin()

async def antiadmin(ctx: commands.Context, value: str) -> None:

    await set_antiraid_toggle(ctx, "antiadmin", value)



@bot.command(name="captcha")

@is_admin()

async def captcha(ctx: commands.Context) -> None:

    await ctx.send(embed=captcha_panel_embed(ctx.guild), view=CaptchaPanelView())





@bot.command(name="raidmode")

@is_admin()

async def raidmode(ctx: commands.Context, value: str) -> None:

    if value.lower() not in {"on", "off", "true", "false", "1", "0", "yes", "no"}:

        await ctx.reply("Utilise `on` ou `off`.")

        return

    enabled = value.lower() in {"on", "true", "1", "yes"}

    if enabled:

        update_active_config({"anti_raid": {key: True for key in ANTI_RAID_KEYS}})

        count = await enable_lockdown_for_guild(ctx.guild, f"Raidmode active par {ctx.author}")

        await ctx.reply(f"Raidmode activé. {count} salons verrouillés.")

    else:

        update_active_config({"anti_raid": {"raidmode": False}})

        count = await disable_lockdown_for_guild(ctx.guild, f"Raidmode desactive par {ctx.author}")

        await ctx.reply(f"Raidmode désactivé. {count} salons restaurés.")





@bot.command(name="lock")

@is_admin()

async def lock(ctx: commands.Context) -> None:

    if not isinstance(ctx.channel, discord.TextChannel):

        await ctx.reply(embed=clean_status_embed("Lock", "Cette commande doit être utilisée dans un salon texte.", discord.Color.red()))

        return



    role = ctx.guild.default_role

    current = ctx.channel.overwrites_for(role)

    original = copy_overwrite(current)

    locked_channels[ctx.guild.id] = [

        item for item in locked_channels.get(ctx.guild.id, []) if item[0] != ctx.channel.id

    ]

    locked_channels[ctx.guild.id].append((ctx.channel.id, original))

    current.send_messages = False

    await ctx.channel.set_permissions(role, overwrite=current, reason=f"Lock par {ctx.author}")

    await ctx.reply("Ce salon est désormais verrouillé.")





@bot.command(name="unlock")

@is_admin()

async def unlock(ctx: commands.Context) -> None:

    if not isinstance(ctx.channel, discord.TextChannel):

        await ctx.reply(embed=clean_status_embed("Unlock", "Cette commande doit être utilisée dans un salon texte.", discord.Color.red()))

        return



    role = ctx.guild.default_role

    saved = locked_channels.get(ctx.guild.id, [])

    original = None

    remaining = []

    for channel_id, overwrite in saved:

        if channel_id == ctx.channel.id:

            original = overwrite

        else:

            remaining.append((channel_id, overwrite))

    locked_channels[ctx.guild.id] = remaining



    if original is None:

        original = ctx.channel.overwrites_for(role)

        original.send_messages = None



    await ctx.channel.set_permissions(role, overwrite=original, reason=f"Unlock par {ctx.author}")

    await ctx.reply("Ce salon est désormais déverrouillé.")





@bot.command(name="lockall")

@can_use("lockall")

async def lockall(ctx: commands.Context) -> None:

    role = ctx.guild.default_role

    saved = locked_channels.get(ctx.guild.id, [])

    saved_by_id = {channel_id: overwrite for channel_id, overwrite in saved}

    count = 0

    for channel in ctx.guild.text_channels:

        try:

            if channel.id not in saved_by_id:

                saved.append((channel.id, channel.overwrites_for(role)))

            overwrite = channel.overwrites_for(role)

            overwrite.send_messages = False

            await channel.set_permissions(role, overwrite=overwrite, reason=f"Lockall par {ctx.author}")

            count += 1

        except discord.HTTPException:

            continue

    locked_channels[ctx.guild.id] = saved

    await ctx.reply(f"Tous les salons sont désormais verrouillés. (`{count}` salon(s))")



@bot.command(name="unlockall")

@can_use("unlockall")

async def unlockall(ctx: commands.Context) -> None:

    role = ctx.guild.default_role

    saved = locked_channels.get(ctx.guild.id, [])

    saved_by_id = {channel_id: overwrite for channel_id, overwrite in saved}

    count = 0

    for channel in ctx.guild.text_channels:

        try:

            original = saved_by_id.get(channel.id)

            if original is None:

                original = channel.overwrites_for(role)

                original.send_messages = None

            await channel.set_permissions(role, overwrite=original, reason=f"Unlockall par {ctx.author}")

            count += 1

        except discord.HTTPException:

            continue

    locked_channels[ctx.guild.id] = []

    await ctx.reply(f"Tous les salons sont désormais déverrouillés. (`{count}` salon(s))")



@bot.command(name="slowmode")

@can_use("slowmode")

async def slowmode(ctx: commands.Context, seconds: int) -> None:

    if not isinstance(ctx.channel, discord.TextChannel):

        await ctx.reply("Cette commande doit être utilisée dans un salon texte.")

        return

    seconds = max(0, min(seconds, 21600))

    await ctx.channel.edit(slowmode_delay=seconds, reason=f"Slowmode par {ctx.author}")

    await ctx.reply(f"Slowmode réglé sur `{seconds}` seconde(s).")





@bot.command(name="nuke")

@can_use("nuke")

async def nuke(ctx: commands.Context) -> None:

    if not isinstance(ctx.channel, discord.TextChannel):

        await ctx.reply("Cette commande doit être utilisée dans un salon texte.")

        return

    old_channel = ctx.channel

    position = old_channel.position

    try:

        new_channel = await old_channel.clone(reason=f"Nuke par {ctx.author}")

        await new_channel.edit(position=position, reason="Nuke: position restaurée")

        await old_channel.delete(reason=f"Nuke par {ctx.author}")

    except discord.Forbidden:

        await ctx.author.send("Je n'ai pas la permission de nuke ce salon.")

        return

    await new_channel.send("Salon recréé.")





@bot.command(name="temprole")

@can_use("temprole")

async def temprole(ctx: commands.Context, member: discord.Member, role: discord.Role, duration: str) -> None:

    seconds = parse_duration(duration)

    if seconds is None:

        await ctx.reply("Durée invalide. Exemple: `10m`, `2h`, `1j`.")

        return

    allowed, reason = can_assign_role(ctx.guild, role)

    if not allowed:

        await ctx.reply(reason)

        return

    await member.add_roles(role, reason=f"Temprole par {ctx.author}")

    await ctx.reply(f"{role.mention} donné à {member.mention} pendant `{format_duration(seconds)}`.")



    async def remove_later() -> None:

        await asyncio.sleep(seconds)

        current = ctx.guild.get_member(member.id)

        current_role = ctx.guild.get_role(role.id)

        if current and current_role and current_role in current.roles:

            try:

                await current.remove_roles(current_role, reason="Temprole terminé")

            except discord.HTTPException:

                pass



    asyncio.create_task(remove_later())





@bot.command(name="renamechannel")

@can_use("renamechannel")

async def renamechannel(ctx: commands.Context, *, name: str) -> None:

    if not isinstance(ctx.channel, discord.TextChannel):

        await ctx.reply("Cette commande doit être utilisée dans un salon texte.")

        return

    clean_name = re.sub(r"[^a-zA-Z0-9-]", "-", name.lower()).strip("-")[:90]

    if not clean_name:

        await ctx.reply("Nom invalide.")

        return

    await ctx.channel.edit(name=clean_name, reason=f"Renamechannel par {ctx.author}")

    await ctx.reply(f"Salon renommé en `{clean_name}`.")





async def find_ban_audit_entry(guild: discord.Guild, user_id: int) -> discord.AuditLogEntry | None:

    if not guild.me or not guild.me.guild_permissions.view_audit_log:

        return None

    try:

        async for entry in guild.audit_logs(limit=100, action=discord.AuditLogAction.ban):

            target = getattr(entry, "target", None)

            if getattr(target, "id", None) == user_id:

                return entry

    except discord.Forbidden:

        return None

    return None



def baninfo_embed(entry: discord.guild.BanEntry, audit_entry: discord.AuditLogEntry | None = None) -> discord.Embed:

    user = entry.user

    reason = entry.reason or (audit_entry.reason if audit_entry else None) or "Aucune raison"

    moderator = audit_entry.user.mention if audit_entry and audit_entry.user else "Inconnu"

    when = audit_entry.created_at.strftime("%d/%m/%Y %H:%M UTC") if audit_entry and audit_entry.created_at else "Inconnu"

    embed = discord.Embed(title="Information ban", color=discord.Color.red())

    embed.add_field(name="Utilisateur", value=f"{user} (`{user.id}`)", inline=False)

    embed.add_field(name="Raison", value=reason[:1024], inline=False)

    embed.add_field(name="Banni par", value=moderator, inline=True)

    embed.add_field(name="Date", value=when, inline=True)

    if user.display_avatar:

        embed.set_thumbnail(url=user.display_avatar.url)

    return embed



def banlist_embed(entries: list[discord.guild.BanEntry], page: int, per_page: int = 8) -> discord.Embed:

    pages = max(1, (len(entries) + per_page - 1) // per_page)

    page = max(0, min(page, pages - 1))

    start = page * per_page

    chunk = entries[start:start + per_page]

    if not chunk:

        description = "Aucun utilisateur banni."

    else:

        lines = []

        for index, entry in enumerate(chunk, start=start + 1):

            reason = entry.reason or "Aucune raison"

            lines.append(f"**{index}. {entry.user}** (`{entry.user.id}`)\n└ {reason[:120]}")

        description = "\n\n".join(lines)

    embed = discord.Embed(title="Liste des bannis", description=description, color=discord.Color.red())

    embed.set_footer(text=f"Page {page + 1}/{pages} - {len(entries)} ban(s)")

    return embed



class BanListView(discord.ui.View):

    def __init__(self, entries: list[discord.guild.BanEntry], page: int = 0) -> None:

        super().__init__(timeout=180)

        self.entries = entries

        self.page = page



    async def refresh(self, interaction: discord.Interaction) -> None:

        await interaction.response.edit_message(embed=banlist_embed(self.entries, self.page), view=self)



    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)

    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:

        pages = max(1, (len(self.entries) + 7) // 8)

        self.page = (self.page - 1) % pages

        await self.refresh(interaction)



    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)

    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:

        pages = max(1, (len(self.entries) + 7) // 8)

        self.page = (self.page + 1) % pages

        await self.refresh(interaction)



@bot.command(name="banlist")

@can_use("banlist")

async def banlist(ctx: commands.Context) -> None:

    entries = [entry async for entry in ctx.guild.bans(limit=None)]

    await ctx.reply(embed=banlist_embed(entries, 0), view=BanListView(entries))



@bot.command(name="baninfo")

@can_use("baninfo")

async def baninfo(ctx: commands.Context, user_value: str) -> None:

    user_id = normalize_user_id(user_value)

    if not user_id:

        await ctx.reply("ID invalide.")

        return

    try:

        entry = await ctx.guild.fetch_ban(discord.Object(id=user_id))

    except discord.NotFound:

        await ctx.reply("Cet utilisateur n'est pas banni.")

        return

    audit_entry = await find_ban_audit_entry(ctx.guild, user_id)

    await ctx.reply(embed=baninfo_embed(entry, audit_entry))



@bot.command(name="ban")

@can_use("ban")

async def ban(ctx: commands.Context, member: discord.Member, *, reason: str = "Raid") -> None:

    await member.ban(reason=f"{reason} - par {ctx.author}", delete_message_seconds=86400)

    await ctx.reply(f"{member.mention} est désormais banni.")





@bot.command(name="tempban")

@can_use("tempban")

async def tempban(ctx: commands.Context, member: discord.Member, duration: str, *, reason: str = "Tempban") -> None:

    seconds = parse_duration(duration)

    if seconds is None:

        await ctx.reply("Durée invalide. Exemple: `10m`, `2h`, `1j`.")

        return

    user_id = member.id

    await member.ban(reason=f"{reason} - tempban par {ctx.author}", delete_message_seconds=86400)

    await ctx.reply(f"{member.mention} est désormais banni pendant `{format_duration(seconds)}`.")

    async def unban_later() -> None:

        await asyncio.sleep(seconds)

        try:

            await ctx.guild.unban(discord.Object(id=user_id), reason="Fin du tempban")

        except discord.HTTPException:

            pass

    asyncio.create_task(unban_later())



@bot.command(name="tempmute")

@can_use("tempmute")

async def tempmute(ctx: commands.Context, member: discord.Member, duration: str, *, reason: str = "Tempmute") -> None:

    seconds = parse_duration(duration)

    if seconds is None:

        await ctx.reply("Durée invalide. Exemple: `10m`, `2h`, `1j`.")

        return

    until = datetime.now(timezone.utc) + timedelta(seconds=seconds)

    try:

        await member.timeout(until, reason=f"{reason} - tempmute par {ctx.author}")

    except discord.Forbidden:

        await ctx.reply("Je n'ai pas la permission de mute ce membre.")

        return

    await ctx.reply(f"{member.mention} est désormais mute pendant `{format_duration(seconds)}`.")



@bot.command(name="unban")

@can_use("unban")

async def unban(ctx: commands.Context, user_value: str, *, reason: str = "Unban") -> None:

    user_id = normalize_user_id(user_value)

    if not user_id:

        await ctx.reply("ID ou mention invalide.")

        return

    try:

        await ctx.guild.unban(discord.Object(id=user_id), reason=f"{reason} - par {ctx.author}")

    except discord.NotFound:

        await ctx.reply("Cet utilisateur n'est pas banni ou l'ID est invalide.")

        return

    except discord.Forbidden:

        await ctx.reply("Je n'ai pas la permission de débannir cet utilisateur.")

        return

    except discord.HTTPException as error:

        await ctx.reply(f"Impossible de débannir cet utilisateur: `{error}`")

        return



    await ctx.reply(f"<@{user_id}> est désormais débanni.")





@bot.command(name="unbanall")

@can_use("unbanall")

async def unbanall(ctx: commands.Context) -> None:

    status = await ctx.reply("Débannissement de tous les utilisateurs bannis en cours...")

    success = 0

    failed = 0

    async for entry in ctx.guild.bans(limit=None):

        try:

            await ctx.guild.unban(entry.user, reason=f"Unbanall par {ctx.author}")

            success += 1

            await asyncio.sleep(0.5)

        except discord.Forbidden:

            failed += 1

            break

        except discord.HTTPException:

            failed += 1



    message = f"{success} utilisateur(s) débanni(s)."

    if failed:

        message += f" {failed} échec(s)."

    try:

        await status.edit(content=message)

    except discord.HTTPException:

        await ctx.reply(message)





@bot.command(name="kick")

@can_use("kick")

async def kick(ctx: commands.Context, member: discord.Member, *, reason: str = "Raid") -> None:

    await member.kick(reason=f"{reason} - par {ctx.author}")

    await ctx.reply(f"{member.mention} est désormais expulsé.")





@bot.command()

@can_use("clear")

async def clear(ctx: commands.Context, amount: int) -> None:

    amount = max(1, min(amount, 100))

    deleted = await ctx.channel.purge(limit=amount + 1)

    await ctx.send(f"{len(deleted) - 1} messages supprimés.", delete_after=5)



@bot.command(name="snipe")

@can_use("snipe")

async def snipe(ctx: commands.Context) -> None:

    data = deleted_message_cache.get((ctx.guild.id, ctx.channel.id))

    if not data:

        await ctx.reply("Aucun message supprimé trouvé dans ce salon.")

        return

    content = data.get("content") or "*Aucun texte*"

    embed = discord.Embed(title="Dernier message supprimé", description=content[:4000], color=discord.Color.blurple())

    embed.add_field(name="Auteur", value=f"<@{data['author_id']}> (`{data['author_id']}`)", inline=False)

    deleted_at = data.get("deleted_at")

    if isinstance(deleted_at, datetime):

        embed.add_field(name="Supprimé", value=discord.utils.format_dt(deleted_at, "R"), inline=True)

    attachments = data.get("attachments") or []

    if attachments:

        embed.add_field(name="Pièce jointe", value=attachments[0], inline=False)

        embed.set_image(url=attachments[0])

    await ctx.reply(embed=embed)



@bot.command(name="createrole")

@is_admin()

async def createrole(ctx: commands.Context, *, name: str) -> None:

    role_name = name.strip()[:100]

    if not role_name:

        await ctx.reply("Nom de rôle invalide.")

        return

    try:

        role = await ctx.guild.create_role(name=role_name, reason=f"Createrole par {ctx.author}")

    except discord.Forbidden:

        await ctx.reply("Je n'ai pas la permission de créer des rôles.")

        return

    await ctx.reply(f"Le rôle {role.mention} est désormais créé.")





@bot.command(name="createchannel")

@is_admin()

async def createchannel(ctx: commands.Context, *, name: str) -> None:

    channel_name = re.sub(r"[^a-zA-Z0-9-]", "-", name.lower()).strip("-")[:90]

    if not channel_name:

        await ctx.reply("Nom de salon invalide.")

        return

    try:

        channel = await ctx.guild.create_text_channel(channel_name, reason=f"Createchannel par {ctx.author}")

    except discord.Forbidden:

        await ctx.reply("Je n'ai pas la permission de créer des salons.")

        return

    await ctx.reply(f"Le salon {channel.mention} est désormais créé.")





def vouch_embed(message: str, author: discord.Member | discord.User) -> discord.Embed:
    color = shop_config().get("settings", {}).get("color", "#0b1f4d")
    embed = discord.Embed(title="Vouch", description=message, color=parse_hex_color(color))
    embed.add_field(name="Client", value=author.mention, inline=True)
    embed.set_footer(text="Merci pour ton avis.")
    return embed


def vouch_config_embed(guild: discord.Guild | None = None) -> discord.Embed:
    cfg = active_config()
    permissions = cfg.get("access", {}).get("command_permissions", {})
    role_ids = [str(item) for item in permissions.get("vouch", [])]
    role = None
    if guild and role_ids and role_ids[0].isdigit():
        role = guild.get_role(int(role_ids[0]))
    color = shop_config().get("settings", {}).get("color", "#0b1f4d")
    embed = discord.Embed(
        title="Configuration Vouch",
        description="Choisis le rôle autorisé à utiliser `.vouch`, puis règle la couleur de l'embed.",
        color=parse_hex_color(color),
    )
    embed.add_field(name="Rôle sélectionné", value=f"✅ {role.mention}" if role else "❌ Aucun rôle sélectionné", inline=False)
    embed.add_field(name="Couleur", value=f"`{color}`", inline=True)
    embed.add_field(name="Accès", value="Owners + rôle sélectionné", inline=True)
    return embed


@bot.command(name="vouch")
@can_use("vouch")
async def vouch(ctx: commands.Context, *, message: str) -> None:
    cfg = shop_config()
    cfg.setdefault("reviews", []).append({
        "user_id": str(ctx.author.id),
        "note": 5,
        "message": message,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "type": "vouch",
    })
    update_shop_config(cfg)
    await ctx.send(embed=vouch_embed(message, ctx.author))


class VouchRoleSelect(discord.ui.RoleSelect):
    def __init__(self) -> None:
        super().__init__(placeholder="Choisis le rôle autorisé à utiliser .vouch", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        set_current_guild(interaction.guild)
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):
            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)
            return
        role = self.values[0]
        cfg = active_config()
        access = cfg.setdefault("access", {})
        permissions = access.setdefault("command_permissions", {})
        permissions["vouch"] = [str(role.id)]
        update_active_config({"access": {"command_permissions": permissions}})
        await interaction.response.edit_message(embed=vouch_config_embed(interaction.guild), view=VouchSetupView())


class VouchColorSelect(discord.ui.Select):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(label="Bleu foncé", value="#0b1f4d", description="Couleur par défaut."),
            discord.SelectOption(label="Bleu", value="#5865f2"),
            discord.SelectOption(label="Rose", value="#ff5ec7"),
            discord.SelectOption(label="Vert", value="#2ecc71"),
            discord.SelectOption(label="Rouge", value="#e74c3c"),
            discord.SelectOption(label="Noir", value="#050505"),
        ]
        super().__init__(placeholder="Modifier la couleur de l'embed", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        set_current_guild(interaction.guild)
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):
            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)
            return
        cfg = shop_config()
        cfg.setdefault("settings", {})["color"] = self.values[0]
        update_shop_config(cfg)
        await interaction.response.edit_message(embed=vouch_config_embed(interaction.guild), view=VouchSetupView())


class VouchSetupView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(VouchRoleSelect())
        self.add_item(VouchColorSelect())


@bot.group(name="setup", invoke_without_command=True)
@can_use("setup")
async def setup_group(ctx: commands.Context) -> None:
    await ctx.reply(embed=clean_status_embed("Setup", "Utilise `.setup vouch`.", discord.Color.dark_blue()))


@setup_group.command(name="vouch")
@can_use("setup")
async def setup_vouch(ctx: commands.Context) -> None:
    await ctx.reply(embed=vouch_config_embed(ctx.guild), view=VouchSetupView())


@bot.command(name="help", aliases=["aide", "commands"])

async def help_command(ctx: commands.Context) -> None:

    prefix = active_config()["prefix"]

    embed = discord.Embed(

        title="Menu help",

        description=f"Sélectionne une catégorie dans le menu.\n**Préfixe actuel: `{prefix}`**",

        color=discord.Color.blurple(),

    )

    try:

        await ctx.send(embed=embed, view=HelpView())

    except Exception:

        await ctx.send(embed=embed)





@bot.group(invoke_without_command=True)

@is_admin()

async def ticket(ctx: commands.Context) -> None:

    await ctx.send(embed=ticket_settings_embed(), view=TicketSettingsView())





@ticket.command(name="panel")

@is_admin()

async def ticket_panel(ctx: commands.Context) -> None:

    cfg = ticket_config()

    embed = discord.Embed(

        title=cfg["panel_title"],

        description=cfg["panel_description"],

        color=parse_hex_color(cfg.get("embed_color") or "#ff5ec7"),

    )

    await ctx.send(embed=embed, view=TicketPanel())





@bot.command(name="close")

@is_admin()

async def close(ctx: commands.Context, *, reason: str = "Ticket ferme") -> None:

    if not ctx.channel.name.startswith("ticket-"):

        await ctx.reply("Cette commande doit etre utilisee dans un salon ticket.")

        return

    await ctx.reply("Fermeture du ticket dans 5 secondes.")

    await asyncio.sleep(5)

    await ctx.channel.delete(reason=f"{reason} - par {ctx.author}")





@bot.command(name="adduser")

@is_admin()

async def adduser(ctx: commands.Context, member: discord.Member) -> None:

    await ctx.channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True)

    await ctx.reply(f"{member.mention} ajoute au ticket.")





@bot.command(name="deluser")

@is_admin()

async def deluser(ctx: commands.Context, member: discord.Member) -> None:

    await ctx.channel.set_permissions(member, overwrite=None)

    await ctx.reply(f"{member.mention} retire du ticket.")





@bot.command(name="addrole")

@can_use("addrole")

async def addrole(ctx: commands.Context, user_value: str, *, role_value: str) -> None:

    member = await resolve_member(ctx.guild, user_value)

    role = resolve_role(ctx.guild, role_value)

    if not member or not role:

        await ctx.reply(embed=clean_status_embed("Addrole", "Membre ou rôle invalide.", discord.Color.red()))

        return

    await member.add_roles(role, reason=f"Addrole par {ctx.author}")

    await ctx.reply(embed=clean_status_embed("Addrole", "1 rôle ajouté à 1 membre.", discord.Color.green()))





@bot.command(name="delrole")

@can_use("delrole")

async def delrole(ctx: commands.Context, user_value: str, *, role_value: str) -> None:

    member = await resolve_member(ctx.guild, user_value)

    role = resolve_role(ctx.guild, role_value)

    if not member or not role:

        await ctx.reply(embed=clean_status_embed("Delrole", "Membre ou rôle invalide.", discord.Color.red()))

        return

    await member.remove_roles(role, reason=f"Delrole par {ctx.author}")

    await ctx.reply(embed=clean_status_embed("Delrole", "1 rôle retiré à 1 membre.", discord.Color.green()))





@bot.command(name="massiverole")

@is_admin()

async def massiverole(ctx: commands.Context, action: str, *, role_value: str) -> None:

    if action.lower() != "add":

        await ctx.reply("Utilise `.massiverole add <rôle>`.")

        return

    role = resolve_role(ctx.guild, role_value)

    if not role:

        await ctx.reply("Rôle invalide.")

        return

    allowed, reason = can_assign_role(ctx.guild, role)

    if not allowed:

        await ctx.reply(reason)

        return



    status = await ctx.reply(f"Ajout de {role.mention} à tous les membres...")

    added = 0

    skipped = 0

    failed = 0

    for member in ctx.guild.members:

        if member.bot or role in member.roles:

            skipped += 1

            continue

        try:

            await member.add_roles(role, reason=f"Massiverole par {ctx.author}")

            added += 1

            await asyncio.sleep(0.4)

        except discord.HTTPException:

            failed += 1



    message = f"Le rôle {role.name} a été ajouté à {added} personne{'s' if added != 1 else ''}."

    if failed:

        message += f" {failed} erreur{'s' if failed != 1 else ''}."

    await status.edit(content=message)





@bot.command(name="rename")

@can_use("rename")

async def rename(ctx: commands.Context, target_or_name: str, *, new_name: str | None = None) -> None:

    if new_name:

        role = resolve_role(ctx.guild, target_or_name)

        if role:

            await role.edit(name=new_name[:100], reason=f"Rename role par {ctx.author}")

            await ctx.reply(f"Rôle renommé en `{new_name[:100]}`.")

            return

        target_or_name = f"{target_or_name} {new_name}"



    clean_name = re.sub(r"[^a-zA-Z0-9-]", "-", target_or_name.lower()).strip("-")[:90]

    if not clean_name:

        await ctx.reply("Nom invalide.")

        return

    if not ctx.channel.name.startswith("ticket-") and not (ctx.channel.topic and "ticket_owner:" in ctx.channel.topic):

        await ctx.reply("Tu peux renommer uniquement un salon ticket.")

        return

    await ctx.channel.edit(name=clean_name, reason=f"Ticket renomme par {ctx.author}")

    await ctx.reply(f"Ticket renomme en `{clean_name}`.")





@bot.group(name="embed", invoke_without_command=True)

@is_admin()

async def embed_group(ctx: commands.Context) -> None:

    await ctx.send(embed=embed_panel_embed(), view=EmbedSettingsView())





@embed_group.command(name="test")

@is_admin()

async def embed_test(ctx: commands.Context) -> None:

    cfg = active_config()["embed"]

    await ctx.channel.send(content=cfg.get("message") or None, embed=make_configured_embed(), view=make_embed_view())

    await ctx.reply("Embed de test envoyé.")





@bot.command()

async def userinfo(ctx: commands.Context, member: discord.Member | None = None) -> None:

    target = member or ctx.author

    embed = discord.Embed(title=f"Infos utilisateur - {target}", color=discord.Color.blurple())

    embed.set_thumbnail(url=target.display_avatar.url)

    embed.add_field(name="ID", value=str(target.id), inline=True)

    embed.add_field(name="Compte cree", value=discord.utils.format_dt(target.created_at, "R"), inline=True)

    embed.add_field(name="A rejoint", value=discord.utils.format_dt(target.joined_at, "R") if target.joined_at else "Inconnu", inline=True)

    await ctx.send(embed=embed)





@bot.command()

async def serverinfo(ctx: commands.Context) -> None:

    guild = ctx.guild

    embed = discord.Embed(title=f"Infos serveur - {guild.name}", color=discord.Color.green())

    if guild.icon:

        embed.set_thumbnail(url=guild.icon.url)

    embed.add_field(name="Membres", value=str(guild.member_count), inline=True)

    embed.add_field(name="Salons", value=str(len(guild.channels)), inline=True)

    embed.add_field(name="Roles", value=str(len(guild.roles)), inline=True)

    embed.add_field(name="Cree", value=discord.utils.format_dt(guild.created_at, "R"), inline=True)

    await ctx.send(embed=embed)





@bot.command(name="permcheck")

@is_admin()

async def permcheck(ctx: commands.Context) -> None:

    me = ctx.guild.me

    permissions = {

        "Administrateur": me.guild_permissions.administrator,

        "Gérer les rôles": me.guild_permissions.manage_roles,

        "Gérer les salons": me.guild_permissions.manage_channels,

        "Bannir des membres": me.guild_permissions.ban_members,

        "Expulser des membres": me.guild_permissions.kick_members,

        "Gérer les messages": me.guild_permissions.manage_messages,

        "Voir les logs d'audit": me.guild_permissions.view_audit_log,

        "Gérer les webhooks": me.guild_permissions.manage_webhooks,

        "Gérer les emojis/stickers": me.guild_permissions.manage_emojis_and_stickers,

        "Timeout membres": me.guild_permissions.moderate_members,

    }

    lines = [f"{'OK' if value else 'MANQUE'} - {name}" for name, value in permissions.items()]

    embed = discord.Embed(title="Vérification des permissions", description="\n".join(lines), color=discord.Color.green() if all(permissions.values()) else discord.Color.orange())

    embed.add_field(name="Rôle bot", value=me.top_role.mention, inline=True)

    await ctx.reply(embed=embed)



@bot.command(name="roleinfo")

@can_use("roleinfo")

async def roleinfo(ctx: commands.Context, *, role_value: str) -> None:

    role = resolve_role(ctx.guild, role_value)

    if not role:

        await ctx.reply("Rôle introuvable.")

        return

    embed = discord.Embed(title=f"Infos rôle - {role.name}", color=role.color if role.color.value else discord.Color.blurple())

    embed.add_field(name="ID", value=str(role.id), inline=True)

    embed.add_field(name="Membres", value=str(len(role.members)), inline=True)

    embed.add_field(name="Position", value=str(role.position), inline=True)

    embed.add_field(name="Mentionnable", value="Oui" if role.mentionable else "Non", inline=True)

    embed.add_field(name="Affiché séparément", value="Oui" if role.hoist else "Non", inline=True)

    embed.add_field(name="Créé", value=discord.utils.format_dt(role.created_at, "R"), inline=True)

    await ctx.reply(embed=embed)



@bot.command(name="rolecolor")

@can_use("rolecolor")

async def rolecolor(ctx: commands.Context, role_value: str, color_value: str) -> None:

    role = resolve_role(ctx.guild, role_value)

    if not role:

        await ctx.reply("Rôle introuvable.")

        return

    if not re.fullmatch(r"#?[0-9a-fA-F]{6}", color_value.strip()):

        await ctx.reply("Couleur invalide. Exemple: `#ff5ec7`.")

        return

    allowed, reason = can_assign_role(ctx.guild, role)

    if not allowed:

        await ctx.reply(reason)

        return

    color = parse_hex_color("#" + color_value.strip().removeprefix("#"))

    await role.edit(color=color, reason=f"Rolecolor par {ctx.author}")

    await ctx.reply(f"La couleur du rôle {role.mention} est désormais `{str(color)}`.")



@bot.command(name="mentionable")

@can_use("mentionable")

async def mentionable(ctx: commands.Context, role_value: str, value: str) -> None:

    role = resolve_role(ctx.guild, role_value)

    if not role:

        await ctx.reply("Rôle introuvable.")

        return

    if value.lower() not in {"on", "off", "true", "false", "1", "0", "yes", "no"}:

        await ctx.reply("Utilise `on` ou `off`.")

        return

    allowed, reason = can_assign_role(ctx.guild, role)

    if not allowed:

        await ctx.reply(reason)

        return

    enabled = value.lower() in {"on", "true", "1", "yes"}

    await role.edit(mentionable=enabled, reason=f"Mentionable par {ctx.author}")

    await ctx.reply(f"Le rôle {role.mention} est désormais {'mentionnable' if enabled else 'non mentionnable'}.")



def resolve_any_channel(guild: discord.Guild, value: str | None, current: discord.abc.GuildChannel | None = None) -> discord.abc.GuildChannel | None:

    if not value:

        return current

    match = re.search(r"\d{15,25}", value)

    if match:

        channel = guild.get_channel(int(match.group(0)))

        if channel:

            return channel

    lowered = value.lower().lstrip("#")

    return next((channel for channel in guild.channels if channel.name.lower() == lowered), None)



@bot.command(name="channelinfo")

@can_use("channelinfo")

async def channelinfo(ctx: commands.Context, *, channel_value: str | None = None) -> None:

    channel = resolve_any_channel(ctx.guild, channel_value, ctx.channel)

    if not channel:

        await ctx.reply("Salon introuvable.")

        return

    embed = discord.Embed(title=f"Infos salon - {channel.name}", color=discord.Color.blurple())

    embed.add_field(name="ID", value=str(channel.id), inline=True)

    embed.add_field(name="Type", value=channel.__class__.__name__, inline=True)

    embed.add_field(name="Catégorie", value=channel.category.name if getattr(channel, "category", None) else "Aucune", inline=True)

    embed.add_field(name="Position", value=str(channel.position), inline=True)

    embed.add_field(name="Créé", value=discord.utils.format_dt(channel.created_at, "R"), inline=True)

    if isinstance(channel, discord.TextChannel):

        embed.add_field(name="Slowmode", value=f"{channel.slowmode_delay}s", inline=True)

        embed.add_field(name="NSFW", value="Oui" if channel.nsfw else "Non", inline=True)

    await ctx.reply(embed=embed)



@bot.command(name="categoryinfo")

@can_use("categoryinfo")

async def categoryinfo(ctx: commands.Context, *, category_value: str | None = None) -> None:

    category = target_category_from_context(ctx, category_value)

    if not category:

        await ctx.reply("Catégorie introuvable.")

        return

    text_channels = sum(isinstance(channel, discord.TextChannel) for channel in category.channels)

    voice_channels = sum(isinstance(channel, discord.VoiceChannel) for channel in category.channels)

    embed = discord.Embed(title=f"Infos catégorie - {category.name}", color=discord.Color.blurple())

    embed.add_field(name="ID", value=str(category.id), inline=True)

    embed.add_field(name="Salons", value=str(len(category.channels)), inline=True)

    embed.add_field(name="Textuels", value=str(text_channels), inline=True)

    embed.add_field(name="Vocaux", value=str(voice_channels), inline=True)

    embed.add_field(name="Position", value=str(category.position), inline=True)

    embed.add_field(name="Créée", value=discord.utils.format_dt(category.created_at, "R"), inline=True)

    await ctx.reply(embed=embed)



@bot.command(name="rolemembers")

@can_use("rolemembers")

async def rolemembers(ctx: commands.Context, *, role_value: str) -> None:

    role = resolve_role(ctx.guild, role_value)

    if not role:

        await ctx.reply("Rôle introuvable.")

        return

    members = role.members

    shown = members[:30]

    description = "\n".join(member.mention for member in shown) if shown else "Aucun membre avec ce rôle."

    if len(members) > len(shown):

        description += f"\n... et {len(members) - len(shown)} autre(s)."

    embed = discord.Embed(title=f"Membres avec {role.name}", description=description, color=discord.Color.blurple())

    embed.set_footer(text=f"Total: {len(members)} membre(s)")

    await ctx.reply(embed=embed)



@bot.command(name="syncperms")

@can_use("syncperms")

async def syncperms(ctx: commands.Context) -> None:

    channel = ctx.channel

    if not isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.ForumChannel)):

        await ctx.reply("Ce salon ne peut pas être synchronisé.")

        return

    if not channel.category:

        await ctx.reply("Ce salon n'a pas de catégorie.")

        return

    try:

        await channel.edit(sync_permissions=True, reason=f"Syncperms par {ctx.author}")

    except discord.Forbidden:

        await ctx.reply("Je n'ai pas la permission de synchroniser ce salon.")

        return

    except discord.HTTPException as error:

        await ctx.reply(f"Impossible de synchroniser ce salon: `{error}`")

        return

    await ctx.reply("Les permissions du salon sont désormais synchronisées avec sa catégorie.")





SERVER_TEMPLATES = {
    "support": [
        ("📌・Information", ["📢・annonces", "📜・règlement", "📘・guide"]),
        ("🎫・Support", ["🎫・ouvrir-un-ticket", "📁・suivi-support", "⭐・avis"]),
        ("💬・Public", ["💬・chat", "🤖・commandes-bot"]),
    ],
    "boutique": [
        ("💎・Boutique", ["💎・boutique", "🛒・acheter", "💳・paiement", "🎁・giveaway"]),
        ("✅・Preuves", ["✅・proof", "💬・vouch", "⭐・avis-clients"]),
        ("🚀・Nitro Boost", ["🚀・nitro-boost", "💜・boosters", "🎁・récompenses"]),
        ("📌・Information", ["📢・annonces", "📜・règlement", "📋・conditions"]),
        ("🎫・Support", ["🎫・ticket-support", "🛒・support-achat"]),
        ("💬・Public", ["💬・chat", "📸・media"]),
    ],
    "shop": [
        ("🏝・Only・Shop", ["🏝・welcome", "🧊・stock", "🍉・terms-of-services"]),
        ("PROOF", ["🔎・proofs", "⭐・vouch", "⭐・legit"]),
        ("Shop Hub", ["🌴・chat", "🤖・cmd"]),
        ("🎉・Support / Buy", ["🏝・buy"]),
        ("🛒・Shop", ["🌍・watch-me", "🛒・snap", "🛒・nitro", "🛒・décoration-login", "🛒・décoration-gift", "🛒・serveur-boost", "🛒・compte-dc", "🛒・tiktok", "🛒・instagram"]),
        ("subs", ["🛒・spotify", "🛒・crunchyroll", "🛒・netflix", "🛒・twitch"]),
        ("other", ["🛒・other", "slot-purist"]),
    ],
    "gaming": [
        ("🎮・Gaming", ["💬・chat", "🎮・recherche-team", "🏆・résultats"]),
        ("📌・Information", ["📢・annonces", "📜・règlement", "🎁・giveaway"]),
    ],
    "rp": [
        ("📌・Information", ["📢・annonces", "📜・règlement", "📘・guide-rp", "🚀・bien-débuter", "🧾・patch-note"]),
        ("🛡️・Staff", ["🔒・chat-staff", "📋・logs-staff", "📌・notes-staff", "🚨・signalements"]),
        ("🎫・Tickets", ["🎫・ticket-support", "⚠️・plainte-staff", "🐞・report-bug", "📨・candidature"]),
        ("💎・Boutique", ["🛒・boutique", "💎・vip", "🎁・giveaway", "⭐・avis-boutique"]),
        ("🎭・Roleplay", ["📝・présentation-personnage", "📄・dossiers-rp", "🏛️・légal", "🕶️・illégal"]),
        ("💬・Public", ["💬・chat", "📸・screenshots", "🤖・commandes-bot"]),
    ],
    "communaute": [
        ("📌・Information", ["📢・annonces", "📜・règlement", "👋・présentation"]),
        ("💬・Communauté", ["💬・chat", "📸・media", "💡・suggestions"]),
        ("🎉・Animation", ["🎁・giveaway", "🎉・événements", "📊・sondages"]),
    ],
    "profil": [
        ("Accueil", ["🌸・arrivant", "🌱・guide"]),
        ("📌・Important", ["🌼・annonces", "🍃・règlement", "🔮・boosts", "🌷・soutien", "🦋・rôles", "🌷・uploaders", "🛒・shop2tomy"]),
        ("gw", ["🎁・nitro", "🎁・deco", "🔎・proofs"]),
        ("Événements", ["🌼・vote2profil", "🌸・smash-or-pass", "📺・twitch"]),
        ("💬・Communautaire", ["💭・chat", "🌱・suggestion", "💻・cmd", "🪅・crée-ton-vocal"]),
        ("💬・helpノ♪", ["🌼・info-support", "🌷・support"]),
        ("Profils", ["🍃・anime", "🍃・movie", "🍃・series", "🍃・musical", "🍃・games", "🍃・animals", "🍃・sports", "🍃・seasons", "🍃・irl", "🍃・fantasy"]),
        ("Pfp", ["🌿・anime", "🌿・movie", "🌿・series", "🌿・musical", "🌿・games", "🌿・animals", "🌿・sports", "🌿・irl"]),
        ("Banner", ["🌼・banner-normal", "🦋・banner-anime", "🌻・banner-manga"]),
        ("boys", ["🪻・pfp-boy", "🌼・gif-boy", "🦋・profil"]),
        ("girls 🌴", ["🌸・pfp-girl", "🌺・gif-girl", "🌸・profil"]),
        ("🧬・Matching", ["🧬・anime-match", "🪅・manga-match", "🌻・divers"]),
        ("fond écran", ["🖥️・pc", "📱・téléphone", "⚙️・wallpaper-engine"]),
        ("🧾・Espace Partenariat", ["💞・nos-conditions", "💞・nos-partenaires", "💞・notre-fiche"]),
    ],
    "perso": [],
}


def add_server_section(sections: list[tuple[str, list[str]]], category: str, channels: list[str]) -> None:
    for index, (existing_category, existing_channels) in enumerate(sections):
        if existing_category == category:
            merged_channels = list(existing_channels)
            for channel in channels:
                if channel not in merged_channels:
                    merged_channels.append(channel)
            sections[index] = (existing_category, merged_channels[:12])
            return
    sections.append((category, channels))


def clean_generated_name(value: str) -> str:
    value = re.sub(r"[^\w\s\-àâäéèêëîïôöùûüç]", " ", value.lower(), flags=re.IGNORECASE)
    value = re.sub(r"\s+", "-", value.strip())
    return value[:90]


def emoji_for_category(name: str) -> str:
    text = name.lower()
    if "ticket" in text or "support" in text:
        return "🎫"
    if "info" in text or "annonce" in text:
        return "📌"
    if "shop" in text or "boutique" in text:
        return "💎"
    if "nitro" in text or "boost" in text:
        return "🚀"
    if "staff" in text:
        return "🛡️"
    if "give" in text:
        return "🎁"
    return "📁"


def emoji_for_channel(name: str) -> str:
    text = name.lower()
    if "annonce" in text:
        return "📢"
    if "tos" in text or "règlement" in text or "reglement" in text:
        return "📜"
    if "give" in text:
        return "🎁"
    if "nitro" in text or "boost" in text:
        return "🚀"
    if "account" in text or "compte" in text:
        return "👤"
    if "ticket" in text or "support" in text:
        return "🎫"
    if "chat" in text:
        return "💬"
    if "proof" in text or "preuve" in text:
        return "✅"
    if "vouch" in text or "avis" in text:
        return "⭐"
    return "#"


def split_generated_channels(raw_channels: str) -> list[str]:
    text = raw_channels.lower()
    aliases = [
        ("nitro boost", "nitro-boost"),
        ("nitro", "nitro"),
        ("boost", "boost"),
        ("account", "account"),
        ("acount", "account"),
        ("accound", "account"),
        ("compte", "compte"),
        ("info", "info"),
        ("annonce", "annonce"),
        ("annonces", "annonces"),
        ("giveaway", "giveaway"),
        ("giveway", "giveaway"),
        ("tos", "tos"),
        ("ticket", "ticket"),
        ("tickets", "tickets"),
        ("proof", "proof"),
        ("vouch", "vouch"),
    ]
    found = []
    for key, channel in aliases:
        if channel in {"nitro", "boost"} and "nitro-boost" in found:
            continue
        if re.search(rf"\b{re.escape(key)}\b", text) and channel not in found:
            found.append(channel)
    has_clear_separator = bool(re.search(r",|/|\+|\bet\b|\bpuis\b", text))
    if found and (not has_clear_separator or len(found) > 1):
        return found[:12]
    parts = re.split(r"\s*(?:,|/|\+|\bet\b|\bpuis\b)\s*", raw_channels)
    return [clean_generated_name(part) for part in parts if clean_generated_name(part)][:12]


def category_name_from_channels(raw_category: str, channels: list[str]) -> str:
    category = clean_generated_name(raw_category)
    if category:
        return category
    joined = " ".join(channels).lower()
    if "ticket" in joined:
        return "ticket"
    if "nitro" in joined or "boost" in joined or "account" in joined or "compte" in joined:
        return "nitro-boost"
    if "annonce" in joined or "tos" in joined or "giveaway" in joined:
        return "info"
    if "proof" in joined or "vouch" in joined:
        return "preuves"
    return channels[0] if channels else "categorie"


def explicit_blueprint_from_description(description: str) -> list[tuple[str, list[str]]]:
    text = description.lower()
    category_pattern = re.compile(r"(?:une\s+|un\s+|la\s+|le\s+)?cat(?:e|é)?gorie\b", re.IGNORECASE)
    content_pattern = re.compile(
        r"\b(?:dedans|avec)\b\s*(?:il\s+y\s+a|ya|y'a|juste\s+un\s+salon|un\s+salon|des\s+salons|avec|dans)?\s*",
        re.IGNORECASE,
    )
    stop_words = {"une", "un", "la", "le", "et", "puis", "apres", "après", "categorie", "catgorie", "catégorie", "dedans", "avec"}
    sections: list[tuple[str, list[str]]] = []
    matches = list(category_pattern.finditer(text))
    for index, match in enumerate(matches):
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        segment = text[match.end():next_start]
        content_match = content_pattern.search(segment)
        if not content_match:
            continue
        raw_category = segment[:content_match.start()].strip(" .,:;-")
        category_words = [word for word in raw_category.split() if word not in stop_words]
        category_name = " ".join(category_words).strip()
        raw_channels = segment[content_match.end():].strip(" .,:;-")
        channels = split_generated_channels(raw_channels)
        category_name = category_name_from_channels(category_name, channels)
        if channels:
            category = f"{emoji_for_category(category_name)}・{category_name}"
            channel_names = [f"{emoji_for_channel(channel)}・{channel}" for channel in channels[:12]]
            sections.append((category, channel_names))
    return sections[:15]


SERVER_TEMPLATE_DESCRIPTIONS = {
    "profil": "Serveur profil/PFP avec accueil, profils, banners, matching et support.",
    "perso": "Modèle personnalisé généré depuis ta description.",
}


def server_roles_from_description(description: str, template: str | None = None) -> list[str]:
    text = description.lower()
    roles = ["Fondateur", "Administrateur", "Modérateur", "Membre"]
    if template == "shop":
        roles.extend(["Client", "VIP", "Support Achat", "Vendeur", "Nitro", "Subs"])
    if template == "boutique" or any(word in text for word in ("boutique", "shop", "vente", "vip", "premium", "nitro")):
        roles.extend(["Client", "VIP", "Nitro Booster", "Support Achat", "Vendeur"])
    if template == "support" or "support" in text or "ticket" in text:
        roles.extend(["Support", "Responsable Support"])
    if template == "rp" or any(word in text for word in ("rp", "roleplay", "rôleplay")):
        roles.extend([
            "Citoyen",
            "Whitelist RP",
            "Staff RP",
            "Modérateur RP",
            "Support",
            "Boutique",
            "VIP",
            "Légal",
            "Illégal",
        ])
    if template == "gaming" or any(word in text for word in ("gaming", "game", "jeu")):
        roles.extend(["Joueur", "Team", "Event"])
    if "bot" in text:
        roles.extend(["Bot", "Développeur"])
    if template == "profil" or any(word in text for word in ("profil", "pfp", "pdp", "banner", "matching")):
        roles.extend(["Uploaders", "Booster", "Partenaire", "Support Profil"])
    return list(dict.fromkeys(roles))[:20]


def server_blueprint_from_description(description: str, template: str | None = None) -> list[tuple[str, list[str]]]:
    text = description.lower()
    explicit_sections = explicit_blueprint_from_description(description)
    if explicit_sections:
        return explicit_sections
    if template == "shop":
        return list(SERVER_TEMPLATES["shop"])
    sections: list[tuple[str, list[str]]] = []
    if template == "perso":
        pass
    elif template in SERVER_TEMPLATES:
        sections.extend(SERVER_TEMPLATES[template])
    elif any(word in text for word in ("boutique", "shop", "vente", "vip", "premium")):
        sections.extend(SERVER_TEMPLATES["boutique"])
    elif "support" in text or "ticket" in text:
        sections.extend(SERVER_TEMPLATES["support"])
    elif any(word in text for word in ("rp", "roleplay", "rôleplay")):
        sections.extend(SERVER_TEMPLATES["rp"])
    elif any(word in text for word in ("gaming", "game", "jeu")):
        sections.extend(SERVER_TEMPLATES["gaming"])
    else:
        sections.extend([
            ("📌・Information", ["📢・annonces", "📜・règlement", "📘・guide"]),
            ("💬・Public", ["💬・chat", "📸・media", "🤖・commandes-bot"]),
        ])
    if any(word in text for word in ("fortnite", "fncs", "battle royale", "ranked", "buildfight", "boxfight")):
        add_server_section(sections, "🎮・Fortnite", ["📢・annonces-fortnite", "🎯・recherche-duo", "🏆・tournois", "🎬・clips"])
        add_server_section(sections, "💬・Communauté", ["💬・chat-fortnite", "📸・screenshots", "🔥・highlights"])
    if any(word in text for word in ("gtarp", "gta rp", "gta-rp", "fivem", "roleplay", "rôleplay", "rp")):
        add_server_section(sections, "📌・Information", ["📢・annonces", "📜・règlement", "📘・guide-rp", "🚀・bien-débuter"])
        add_server_section(sections, "🎭・Roleplay", ["📝・présentation-personnage", "📄・dossiers-rp", "🏛️・légal", "🕶️・illégal"])
        add_server_section(sections, "🚓・GTA RP", ["🚓・police", "🚑・ems", "🔧・mécano", "💼・entreprises"])
        add_server_section(sections, "🎫・Tickets", ["🎫・ticket-support", "⚠️・plainte-staff", "📨・candidature"])
    if "staff" in text or "modération" in text or "moderation" in text:
        add_server_section(sections, "🛡️・Staff", ["🔒・chat-staff", "📋・logs-staff", "📌・notes-staff", "🚨・signalements"])
    if re.search(r"\b(pp|pdp|gfx)\b", text) or any(word in text for word in ("photo de profil", "avatar", "logo", "graphisme", "banner", "bannière", "design", "création", "creation")):
        add_server_section(sections, "🎨・Créations", ["🖼️・galerie-pp", "📝・demandes-pp", "📦・livraisons", "⭐・avis-clients"])
        add_server_section(sections, "🛒・Commandes", ["💳・tarifs", "🛒・commander", "✅・proof"])
        add_server_section(sections, "🎫・Support", ["🎫・ticket-support", "📁・suivi-commandes"])
    if any(word in text for word in ("shop", "boutique", "vente", "acheter", "paypal", "crypto", "ecommerce", "market")):
        add_server_section(sections, "📌・Information", ["📢・annonces", "📜・règlement", "📋・conditions", "💳・moyens-paiement"])
        add_server_section(sections, "💎・Boutique", ["💎・boutique", "🛒・acheter", "💳・paiement", "🎁・giveaway"])
        add_server_section(sections, "🎫・Support", ["🎫・ticket-support", "🛒・support-achat"])
        add_server_section(sections, "✅・Preuves", ["✅・proof", "💬・vouch", "⭐・avis-clients"])
        add_server_section(sections, "🚀・Nitro Boost", ["🚀・nitro-boost", "💜・boosters", "🎁・récompenses"])
    if template != "perso" and any(word in text for word in ("proof", "preuve", "preuves", "vouch", "avis", "review")):
        add_server_section(sections, "✅・Preuves", ["✅・proof", "💬・vouch", "⭐・avis-clients"])
    if template != "perso" and any(word in text for word in ("nitro", "boost", "booster", "premium", "vip")):
        add_server_section(sections, "🚀・Nitro Boost", ["🚀・nitro-boost", "💜・boosters", "🎁・récompenses"])
    if any(word in text for word in ("communautaire", "communauté", "communaute", "public", "discussion", "amis")):
        add_server_section(sections, "📌・Information", ["📢・annonces", "📜・règlement", "👋・présentation"])
        add_server_section(sections, "💬・Communauté", ["💬・chat", "📸・media", "💡・suggestions"])
        add_server_section(sections, "🎉・Animations", ["🎁・giveaway", "📊・sondages", "🎉・événements"])
    if "bot" in text and not any(category == "Bot" or category.endswith("・Bot") for category, _ in sections):
        sections.append(("🤖・Bot", ["🤖・commandes", "📊・statut-bot", "⭐・avis-bot"]))
    if "sombre" in text or "dark" in text:
        sections.insert(0, ("🌑・Accueil", ["👋・welcome", "📌・présentation"]))
    if template == "perso":
        if not sections and text.strip():
            add_server_section(sections, "📌・Information", ["📢・annonces", "📜・règlement", "📘・guide"])
            add_server_section(sections, "💬・Public", ["💬・chat", "📸・media", "💡・suggestions"])
            add_server_section(sections, "🎫・Support", ["🎫・ticket-support"])
        return sections[:15]
    if not sections:
        sections.extend([
            ("📌・Information", ["📢・annonces", "📜・règlement", "📘・guide"]),
            ("💬・Public", ["💬・chat", "📸・media", "💡・suggestions"]),
        ])
    return sections[:15]


def server_generator_embed(
    description: str | None = None,
    blueprint: list[tuple[str, list[str]]] | None = None,
    roles: list[str] | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title="🛠️ Générateur de serveur",
        description="Décris ton serveur, vérifie l'aperçu, puis confirme la génération.",
        color=discord.Color.blurple(),
    )
    if description:
        embed.add_field(name="Description", value=description[:900], inline=False)
    if blueprint:
        lines = []
        for category, channels in blueprint:
            lines.append(f"**{category}**")
            lines.extend(f"`#` {channel}" for channel in channels)
        embed.add_field(name="Aperçu", value="\n".join(lines)[:3500], inline=False)
        embed.add_field(name="Attention", value="La confirmation supprimera les anciens salons, catégories et rôles supprimables.", inline=False)
    if roles:
        embed.add_field(name="Rôles créés", value=", ".join(f"`{role}`" for role in roles)[:1000], inline=False)
    if not description and not blueprint:
        examples = "\n".join([
            "`serveur gtarp sombre avec staff, tickets et annonces`",
            "`serveur shop nitro avec proof, vouch, support et giveaway`",
            "`serveur pp fortnite avec commandes, galerie et tickets`",
            "`categorie info dedans annonces tos giveaway et categorie ticket avec ticket`",
        ])
        embed.add_field(name="Exemples", value=examples, inline=False)
        embed.add_field(name="Menu", value="Utilise le sélecteur pour écrire ta description, tester un exemple ou revoir l'aide.", inline=False)
        embed.add_field(name="Attention", value="La confirmation supprimera les anciens salons, catégories et rôles supprimables.", inline=False)
    return embed


async def generate_server_structure(
    guild: discord.Guild,
    author: discord.abc.User,
    blueprint: list[tuple[str, list[str]]],
    roles: list[str],
) -> tuple[int, int, int]:
    deleted = 0
    for channel in list(guild.channels):
        if isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.ForumChannel)):
            try:
                await channel.delete(reason=f"Génération serveur par {author}")
                deleted += 1
            except discord.HTTPException:
                continue
    for category in list(guild.categories):
        try:
            await category.delete(reason=f"Génération serveur par {author}")
            deleted += 1
        except discord.HTTPException:
            continue
    bot_top_role = guild.me.top_role if guild.me else None
    for role in sorted(guild.roles, key=lambda item: item.position, reverse=True):
        if role == guild.default_role or role.managed:
            continue
        if bot_top_role and role >= bot_top_role:
            continue
        try:
            await role.delete(reason=f"Génération serveur par {author}")
            deleted += 1
        except discord.HTTPException:
            continue
    created = 0
    created_roles = 0
    for role_name in roles:
        if discord.utils.get(guild.roles, name=role_name):
            continue
        try:
            role = await guild.create_role(name=role_name[:100], reason=f"Génération serveur par {author}")
            if bot_top_role and role < bot_top_role:
                created_roles += 1
        except discord.HTTPException:
            continue
    for category_name, channels in blueprint:
        try:
            category = await guild.create_category(category_name[:100], reason=f"Génération serveur par {author}")
            created += 1
        except discord.HTTPException:
            continue
        for channel_name in channels:
            try:
                await guild.create_text_channel(channel_name[:100], category=category, reason=f"Génération serveur par {author}")
                created += 1
            except discord.HTTPException:
                continue
    return deleted, created, created_roles


def clone_overwrites_for_target(
    source_channel: discord.abc.GuildChannel,
    target_guild: discord.Guild,
    role_map: dict[int, discord.Role],
) -> dict[discord.Role | discord.Member, discord.PermissionOverwrite]:
    overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {}
    for target, overwrite in source_channel.overwrites.items():
        if isinstance(target, discord.Role):
            mapped_role = target_guild.default_role if target.is_default() else role_map.get(target.id)
            if mapped_role:
                overwrites[mapped_role] = overwrite
        elif isinstance(target, discord.Member):
            mapped_member = target_guild.get_member(target.id)
            if mapped_member:
                overwrites[mapped_member] = overwrite
    return overwrites


async def clone_discord_server(
    source_guild: discord.Guild,
    target_guild: discord.Guild,
    author: discord.abc.User,
    delete_target: bool = True,
    clone_roles: bool = True,
    clone_channels: bool = True,
) -> tuple[int, int, int]:
    deleted = 0
    if delete_target:
        for channel in list(target_guild.channels):
            if isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.ForumChannel)):
                try:
                    await channel.delete(reason=f"Clonage serveur par {author}")
                    deleted += 1
                except discord.HTTPException:
                    continue
        for category in list(target_guild.categories):
            try:
                await category.delete(reason=f"Clonage serveur par {author}")
                deleted += 1
            except discord.HTTPException:
                continue
        bot_top_role = target_guild.me.top_role if target_guild.me else None
        for role in sorted(target_guild.roles, key=lambda item: item.position, reverse=True):
            if role == target_guild.default_role or role.managed:
                continue
            if bot_top_role and role >= bot_top_role:
                continue
            try:
                await role.delete(reason=f"Clonage serveur par {author}")
                deleted += 1
            except discord.HTTPException:
                continue

    role_map: dict[int, discord.Role] = {source_guild.default_role.id: target_guild.default_role}
    created_roles = 0
    if clone_roles:
        for role in sorted(source_guild.roles, key=lambda item: item.position):
            if role == source_guild.default_role or role.managed:
                continue
            try:
                created_role = await target_guild.create_role(
                    name=role.name[:100],
                    permissions=role.permissions,
                    colour=role.colour,
                    hoist=role.hoist,
                    mentionable=role.mentionable,
                    reason=f"Clonage serveur par {author}",
                )
                role_map[role.id] = created_role
                created_roles += 1
            except discord.HTTPException:
                continue
    else:
        for source_role in source_guild.roles:
            existing = discord.utils.get(target_guild.roles, name=source_role.name)
            if existing:
                role_map[source_role.id] = existing

    created_channels = 0
    if clone_channels:
        category_map: dict[int, discord.CategoryChannel] = {}
        for category in sorted(source_guild.categories, key=lambda item: item.position):
            overwrites = clone_overwrites_for_target(category, target_guild, role_map)
            try:
                created_category = await target_guild.create_category(
                    category.name[:100],
                    overwrites=overwrites,
                    reason=f"Clonage serveur par {author}",
                )
                category_map[category.id] = created_category
                created_channels += 1
            except discord.HTTPException:
                continue

        clonable_channels = [
            channel for channel in source_guild.channels
            if not isinstance(channel, discord.CategoryChannel)
        ]
        for channel in sorted(clonable_channels, key=lambda item: item.position):
            category = category_map.get(channel.category_id) if getattr(channel, "category_id", None) else None
            overwrites = clone_overwrites_for_target(channel, target_guild, role_map)
            try:
                if isinstance(channel, discord.TextChannel):
                    await target_guild.create_text_channel(
                        channel.name[:100],
                        category=category,
                        overwrites=overwrites,
                        topic=channel.topic,
                        nsfw=channel.nsfw,
                        slowmode_delay=channel.slowmode_delay,
                        reason=f"Clonage serveur par {author}",
                    )
                elif isinstance(channel, discord.VoiceChannel):
                    await target_guild.create_voice_channel(
                        channel.name[:100],
                        category=category,
                        overwrites=overwrites,
                        bitrate=channel.bitrate,
                        user_limit=channel.user_limit,
                        reason=f"Clonage serveur par {author}",
                    )
                elif isinstance(channel, discord.StageChannel):
                    await target_guild.create_stage_channel(
                        channel.name[:100],
                        category=category,
                        overwrites=overwrites,
                        bitrate=channel.bitrate,
                        user_limit=channel.user_limit,
                        reason=f"Clonage serveur par {author}",
                    )
                elif isinstance(channel, discord.ForumChannel) and hasattr(target_guild, "create_forum"):
                    await target_guild.create_forum(
                        channel.name[:100],
                        category=category,
                        overwrites=overwrites,
                        topic=channel.topic,
                        nsfw=channel.nsfw,
                        slowmode_delay=channel.slowmode_delay,
                        reason=f"Clonage serveur par {author}",
                    )
                else:
                    continue
                created_channels += 1
            except discord.HTTPException:
                continue
    return deleted, created_roles, created_channels


def cloner_embed(source_id: str | None = None, target_id: str | None = None) -> discord.Embed:
    embed = discord.Embed(
        title="📋 Cloner un serveur",
        description="Copie les rôles, catégories, salons et permissions d'un serveur source vers un serveur cible.",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Serveur source", value=f"`{source_id}`" if source_id else "`Non configuré`", inline=True)
    embed.add_field(name="Serveur cible", value=f"`{target_id}`" if target_id else "`Non configuré`", inline=True)
    embed.add_field(
        name="Important",
        value="Le bot doit être sur les deux serveurs avec les permissions administrateur. La confirmation supprime l'ancienne structure du serveur cible.",
        inline=False,
    )
    return embed


class CloneIdsModal(discord.ui.Modal, title="Configurer le clonage"):
    source_id = discord.ui.TextInput(label="ID du serveur à cloner", placeholder="Serveur source", min_length=15, max_length=25)
    target_id = discord.ui.TextInput(label="ID du serveur qui va être cloné", placeholder="Serveur cible", min_length=15, max_length=25)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        source = str(self.source_id.value).strip()
        target = str(self.target_id.value).strip()
        if not source.isdigit() or not target.isdigit() or source == target:
            await interaction.response.send_message("IDs invalides ou identiques.", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=cloner_embed(source, target),
            view=ClonerConfirmView(source, target),
            ephemeral=True,
        )


class ClonerView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(ClonerSelect())


class ClonerSelect(discord.ui.Select):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(label="Configurer les IDs", value="ids", emoji="📝", description="ID du serveur source et du serveur cible."),
            discord.SelectOption(label="Aide", value="help", emoji="📘", description="Voir les conditions pour cloner."),
        ]
        super().__init__(placeholder="Choisis une action", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):
            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)
            return
        if self.values[0] == "ids":
            await interaction.response.send_modal(CloneIdsModal())
            return
        await interaction.response.edit_message(embed=cloner_embed(), view=ClonerView())


class ClonerConfirmView(discord.ui.View):
    def __init__(self, source_id: str, target_id: str) -> None:
        super().__init__(timeout=300)
        self.source_id = source_id
        self.target_id = target_id

    @discord.ui.button(label="Lancer le clonage", style=discord.ButtonStyle.danger)
    async def confirm_clone(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):
            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)
            return
        source_guild = bot.get_guild(int(self.source_id))
        target_guild = bot.get_guild(int(self.target_id))
        if not source_guild or not target_guild:
            await interaction.response.send_message("Le bot doit être présent sur les deux serveurs.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        deleted, created_roles, created_channels = await clone_discord_server(source_guild, target_guild, interaction.user)
        await interaction.followup.send(
            f"Clonage terminé: {deleted} élément(s) supprimé(s), {created_roles} rôle(s) copié(s), {created_channels} salon(s)/catégorie(s) copié(s).",
            ephemeral=True,
        )

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel_clone(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Clonage annulé.", embed=None, view=None)


async def ask_server_description(interaction: discord.Interaction) -> None:
    if not interaction.channel or not interaction.guild or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("Impossible ici.", ephemeral=True)
        return
    if not await has_owner_access(interaction.user):
        await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)
        return
    await interaction.response.send_message("Décris le serveur à créer. Exemple: `boutique bot sombre avec support et annonces`.\nTape `cancel` pour annuler.")
    prompt = await interaction.original_response()

    def check(message: discord.Message) -> bool:
        return message.author.id == interaction.user.id and message.channel.id == interaction.channel.id and not message.author.bot

    try:
        message = await bot.wait_for("message", timeout=120, check=check)
    except asyncio.TimeoutError:
        await interaction.followup.send("Temps écoulé.", ephemeral=True)
        return
    content = message.content.strip()
    if content.lower() == "cancel":
        await interaction.followup.send("Annulé.", ephemeral=True)
    else:
        blueprint = server_blueprint_from_description(content, "perso")
        roles = server_roles_from_description(content, "perso")
        await interaction.followup.send(embed=server_generator_embed(content, blueprint, roles), view=ServerGeneratorConfirmView(content, "perso"))
    for item in (prompt, message):
        try:
            await item.delete()
        except discord.HTTPException:
            pass


class ServerGeneratorView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(ServerGeneratorActionSelect())


class ServerGeneratorConfirmView(discord.ui.View):
    def __init__(self, description: str, template: str | None = None) -> None:
        super().__init__(timeout=None)
        self.description = description
        self.template = template

    @discord.ui.button(label="Confirmer et générer", style=discord.ButtonStyle.danger, row=0)
    async def confirm_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        set_current_guild(interaction.guild)
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):
            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        blueprint = server_blueprint_from_description(self.description, self.template)
        roles = server_roles_from_description(self.description, self.template)
        deleted, created, created_roles = await generate_server_structure(interaction.guild, interaction.user, blueprint, roles)
        await interaction.followup.send(
            f"Serveur généré: {deleted} ancien(s) élément(s) supprimé(s), {created} salon(s)/catégorie(s) créé(s), {created_roles} rôle(s) créé(s).",
            ephemeral=True,
        )

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary, row=0)
    async def cancel_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(embed=server_generator_embed(), view=ServerGeneratorView())


class ServerGeneratorActionSelect(discord.ui.Select):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(label="Décrire ton serveur", value="write", emoji="🧩", description="Écris ton idée, le bot prépare une preview."),
            discord.SelectOption(label="Modèle Shop", value="shop", emoji="🛒", description="Shop complet avec proof, vouch, nitro, subs et support."),
            discord.SelectOption(label="Modèle Profil / PFP", value="profil", emoji="🌸", description="Serveur profil, pfp, banner, matching, support."),
        ]
        super().__init__(placeholder="Choisis une action", min_values=1, max_values=1, options=options, row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        set_current_guild(interaction.guild)
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):
            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)
            return
        action = self.values[0]
        if action == "write":
            await ask_server_description(interaction)
            return
        if action == "shop":
            description = "modèle shop complet avec welcome stock terms proof vouch support buy nitro subs et réseaux"
            blueprint = server_blueprint_from_description(description, "shop")
            roles = server_roles_from_description(description, "shop")
            await interaction.response.edit_message(
                embed=server_generator_embed(description, blueprint, roles),
                view=ServerGeneratorConfirmView(description, "shop"),
            )
            return
        if action == "profil":
            description = "modèle profil pfp banner matching avec accueil important giveaway communautaire support partenariat"
            blueprint = server_blueprint_from_description(description, "profil")
            roles = server_roles_from_description(description, "profil")
            await interaction.response.edit_message(
                embed=server_generator_embed(description, blueprint, roles),
                view=ServerGeneratorConfirmView(description, "profil"),
            )


@bot.command(name="serveur")
@is_admin()
async def serveur(ctx: commands.Context) -> None:
    await ctx.send(embed=server_generator_embed(), view=ServerGeneratorView())


@bot.command(name="cloner")
@is_admin()
async def cloner(ctx: commands.Context) -> None:
    await ctx.send(embed=cloner_embed(), view=ClonerView())


def target_category_from_context(ctx: commands.Context, value: str | None) -> discord.CategoryChannel | None:

    category = resolve_category(ctx.guild, value) if value else None

    if category:

        return category

    current_category = getattr(ctx.channel, "category", None)

    return current_category if isinstance(current_category, discord.CategoryChannel) else None





async def set_category_locked(category: discord.CategoryChannel, locked: bool, author: discord.abc.User) -> int:

    overwrite = category.overwrites_for(category.guild.default_role)

    overwrite.send_messages = False if locked else None

    overwrite.add_reactions = False if locked else None

    overwrite.connect = False if locked else None

    overwrite.speak = False if locked else None

    await category.set_permissions(category.guild.default_role, overwrite=overwrite, reason=f"Category lock par {author}")

    changed = 0

    for channel in category.channels:

        try:

            overwrite = channel.overwrites_for(category.guild.default_role)

            overwrite.send_messages = False if locked else None

            overwrite.add_reactions = False if locked else None

            overwrite.connect = False if locked else None

            overwrite.speak = False if locked else None

            await channel.set_permissions(category.guild.default_role, overwrite=overwrite, reason=f"Category lock par {author}")

            changed += 1

        except discord.HTTPException:

            continue

    return changed





@bot.command(name="lockcategory")

@can_use("lockcategory")

async def lockcategory(ctx: commands.Context, *, category_value: str | None = None) -> None:

    category = target_category_from_context(ctx, category_value)

    if not category:

        await ctx.reply("Catégorie introuvable. Donne l'ID ou le nom d'une catégorie.")

        return

    count = await set_category_locked(category, True, ctx.author)

    await ctx.reply(f"La catégorie `{category.name}` est désormais verrouillée ({count} salon(s)).")





@bot.command(name="categorylock")

@can_use("categorylock")

async def categorylock(ctx: commands.Context, *, category_value: str | None = None) -> None:

    await lockcategory(ctx, category_value=category_value)



@bot.command(name="unlockcategory")

@can_use("unlockcategory")

async def unlockcategory(ctx: commands.Context, *, category_value: str | None = None) -> None:

    category = target_category_from_context(ctx, category_value)

    if not category:

        await ctx.reply("Catégorie introuvable. Donne l'ID ou le nom d'une catégorie.")

        return

    count = await set_category_locked(category, False, ctx.author)

    await ctx.reply(f"La catégorie `{category.name}` est désormais déverrouillée ({count} salon(s)).")





@bot.command(name="categoryunlock")

@can_use("categoryunlock")

async def categoryunlock(ctx: commands.Context, *, category_value: str | None = None) -> None:

    await unlockcategory(ctx, category_value=category_value)



@bot.command(name="delcategory")

@can_use("delcategory")

async def delcategory(ctx: commands.Context, *, category_value: str) -> None:

    category = resolve_category(ctx.guild, category_value)

    if not category:

        await ctx.reply("Catégorie introuvable. Donne l'ID ou le nom d'une catégorie.")

        return

    name = category.name

    deleted_channels = 0

    for channel in list(category.channels):

        try:

            await channel.delete(reason=f"Delcategory par {ctx.author}")

            deleted_channels += 1

        except discord.HTTPException:

            continue

    try:

        await category.delete(reason=f"Delcategory par {ctx.author}")

    except discord.HTTPException as error:

        await ctx.reply(f"Salons supprimés, mais impossible de supprimer la catégorie: `{error}`")

        return

    await ctx.reply(f"La catégorie `{name}` et {deleted_channels} salon(s) ont été supprimés.")





@bot.command(name="renamecategory")

@can_use("renamecategory")

async def renamecategory(ctx: commands.Context, category_value: str, *, new_name: str) -> None:

    category = resolve_category(ctx.guild, category_value)

    if not category:

        await ctx.reply("Catégorie introuvable. Donne l'ID ou le nom d'une catégorie.")

        return

    clean_name = new_name.strip()[:100]

    if not clean_name:

        await ctx.reply("Nom invalide.")

        return

    old_name = category.name

    await category.edit(name=clean_name, reason=f"Renamecategory par {ctx.author}")

    await ctx.reply(f"La catégorie `{old_name}` est désormais renommée en `{clean_name}`.")



@bot.group(name="giveaway", invoke_without_command=True)

@is_admin()

async def giveaway(ctx: commands.Context) -> None:

    await ctx.send(embed=giveaway_panel_embed(), view=GiveawaySettingsView())





@giveaway.command(name="reroll")

@is_admin()

async def giveaway_reroll(ctx: commands.Context, message_id: int) -> None:

    participants = list(giveaway_participants.get(message_id, set()))

    data = giveaway_messages.get(message_id, giveaway_config())

    if not participants:

        await ctx.reply("Aucun participant enregistré pour ce giveaway. Le reroll marche sur les giveaways créés depuis le dernier démarrage du bot.")

        return

    winner_id = participants[int.from_bytes(os.urandom(2), "big") % len(participants)]

    embed = giveaway_live_embed(data, len(participants), ended=True, winner_id=winner_id)

    try:

        message = await ctx.channel.fetch_message(message_id)

        await message.edit(embed=embed, view=None)

    except discord.HTTPException:

        pass

    await ctx.reply(f"Nouveau gagnant: <@{winner_id}>")



def build_backup(guild: discord.Guild) -> dict:

    return {

        "created_at": datetime.now(timezone.utc).isoformat(),

        "guild_name": guild.name,

        "roles": [

            {

                "name": role.name,

                "color": role.color.value,

                "hoist": role.hoist,

                "mentionable": role.mentionable,

                "permissions": role.permissions.value,

                "position": role.position,

            }

            for role in guild.roles

            if role != guild.default_role and not role.managed

        ],

        "categories": [

            {

                "name": category.name,

                "position": category.position,

            }

            for category in guild.categories

        ],

        "text_channels": [

            {

                "name": channel.name,

                "category": channel.category.name if channel.category else None,

                "topic": channel.topic,

                "slowmode_delay": channel.slowmode_delay,

                "nsfw": channel.nsfw,

                "position": channel.position,

            }

            for channel in guild.text_channels

        ],

    }





def backup_panel_embed() -> discord.Embed:

    backups = global_backups()

    embed = discord.Embed(

        title="💾 Gestion des backups",

        description="Sauvegarde, charge, renomme ou supprime tes backups depuis le menu.",

        color=discord.Color.blurple(),

    )

    latest = next(reversed(backups), "Aucune") if backups else "Aucune"

    embed.add_field(name="📦 Backups", value=str(len(backups)), inline=True)

    embed.add_field(name="🕒 Dernière backup", value=latest, inline=True)

    embed.add_field(

        name="⚠️ Chargement",

        value="Charger une backup supprime les anciens salons, catégories et rôles supprimables.",

        inline=False,

    )

    embed.set_footer(text="Choisis une action dans le menu.")

    return embed





def backup_rename_embed() -> discord.Embed:

    backups = global_backups()

    embed = discord.Embed(

        title="✏️ Renommer une backup",

        description="Choisis une backup dans le sélecteur, puis envoie seulement le nouveau nom.",

        color=discord.Color.blurple(),

    )

    if backups:

        preview = []

        for name, data in list(backups.items())[:8]:

            preview.append(f"**{name}**\n`{data.get('created_at', 'date inconnue')}`")

        embed.add_field(name="📦 Backups disponibles", value="\n\n".join(preview), inline=False)

    else:

        embed.add_field(name="📦 Backups disponibles", value="Aucune backup disponible.", inline=False)

    embed.set_footer(text="Le renommage remplace l'ancien nom, il ne crée pas une copie.")

    return embed





def backup_action_embed(title: str, description: str) -> discord.Embed:

    backups = global_backups()

    embed = discord.Embed(title=title, description=description, color=discord.Color.blurple())

    if backups:

        preview = []

        for name, data in list(backups.items())[:8]:

            roles = len(data.get("roles", []))

            categories = len(data.get("categories", []))

            channels = len(data.get("text_channels", []))

            preview.append(f"**{name}**\n`{roles} rôles` - `{categories} catégories` - `{channels} salons`")

        embed.add_field(name="📦 Backups disponibles", value="\n\n".join(preview), inline=False)

    else:

        embed.add_field(name="📦 Backups disponibles", value="Aucune backup disponible.", inline=False)

    return embed





def backup_confirm_embed(name: str) -> discord.Embed:

    data = global_backups().get(name, {})

    embed = discord.Embed(

        title="⚠️ Confirmer le chargement",

        description=(

            f"Tu vas charger la backup **{name}**.\n\n"

            "Cette action supprime les anciens salons, catégories et rôles supprimables du serveur, "

            "puis recrée ceux de la backup."

        ),

        color=discord.Color.orange(),

    )

    embed.add_field(name="🎭 Rôles", value=str(len(data.get("roles", []))), inline=True)

    embed.add_field(name="📁 Catégories", value=str(len(data.get("categories", []))), inline=True)

    embed.add_field(name="💬 Salons", value=str(len(data.get("text_channels", []))), inline=True)

    embed.set_footer(text="Clique sur Confirmer seulement si tu veux remplacer le serveur.")

    return embed





def backup_list_embed() -> discord.Embed:

    backups = global_backups()

    embed = discord.Embed(title="📜 Liste des backups", color=discord.Color.blurple())

    if not backups:

        embed.description = "Aucune backup disponible."

        return embed

    for name, data in list(backups.items())[:20]:

        roles = len(data.get("roles", []))

        categories = len(data.get("categories", []))

        channels = len(data.get("text_channels", []))

        created = data.get("created_at", "date inconnue")

        embed.add_field(

            name=f"💾 {name}",

            value=f"Créée: `{created}`\nRôles: `{roles}` - Catégories: `{categories}` - Salons: `{channels}`",

            inline=False,

        )

    embed.set_footer(text=f"{len(backups)} backup(s) enregistrée(s).")

    return embed





def backup_list_text() -> str:

    backups = global_backups()

    if not backups:

        return "Aucune backup disponible."

    return "\n".join(f"`{name}` - {value.get('created_at', 'date inconnue')}" for name, value in backups.items())





async def perform_backup_create(guild: discord.Guild, name: str) -> str:

    backups = dict(global_backups())

    backups[name] = build_backup(guild)

    replace_global_backups(backups)

    return f"Backup `{name}` créée."





async def perform_backup_load(guild: discord.Guild, author: discord.abc.User, name: str) -> str:

    data = global_backups().get(name)

    if not data:

        return "Backup introuvable."

    deleted_roles = 0

    deleted_categories = 0

    deleted_channels = 0

    created_roles = 0

    created_categories = 0

    created_channels = 0

    created_role_positions: dict[discord.Role, int] = {}



    for channel in list(guild.text_channels):

        try:

            await channel.delete(reason=f"Backup load par {author}")

            deleted_channels += 1

        except discord.HTTPException:

            continue

    for category in list(guild.categories):

        try:

            await category.delete(reason=f"Backup load par {author}")

            deleted_categories += 1

        except discord.HTTPException:

            continue

    bot_member = guild.me

    bot_top_role = bot_member.top_role if bot_member else None

    for role in sorted(guild.roles, key=lambda item: item.position, reverse=True):

        if role == guild.default_role or role.managed:

            continue

        if bot_top_role and role >= bot_top_role:

            continue

        try:

            await role.delete(reason=f"Backup load par {author}")

            deleted_roles += 1

        except discord.HTTPException:

            continue



    for index, role_data in enumerate(data.get("roles", []), start=1):

        if discord.utils.get(guild.roles, name=role_data.get("name")):

            continue

        try:

            role = await guild.create_role(

                name=role_data.get("name", "role")[:100],

                permissions=discord.Permissions(int(role_data.get("permissions", 0))),

                colour=discord.Colour(int(role_data.get("color", 0))),

                hoist=bool(role_data.get("hoist", False)),

                mentionable=bool(role_data.get("mentionable", False)),

                reason=f"Backup load par {author}",

            )

            created_role_positions[role] = int(role_data.get("position") or index)

            created_roles += 1

        except discord.HTTPException:

            continue

    if created_role_positions:

        try:

            await guild.edit_role_positions(positions=created_role_positions)

        except discord.HTTPException:

            pass

    categories_by_name = {category.name: category for category in guild.categories}

    created_category_positions: dict[discord.abc.GuildChannel, int] = {}

    for category_data in sorted(data.get("categories", []), key=lambda item: int(item.get("position", 0))):

        name_value = category_data.get("name")

        if not name_value or name_value in categories_by_name:

            continue

        try:

            category = await guild.create_category(name_value[:100], reason=f"Backup load par {author}")

            categories_by_name[category.name] = category

            created_category_positions[category] = int(category_data.get("position") or category.position)

            created_categories += 1

        except discord.HTTPException:

            continue

    for category, position in created_category_positions.items():

        try:

            await category.edit(position=position, reason=f"Backup load par {author}")

        except discord.HTTPException:

            continue

    for channel_data in sorted(data.get("text_channels", []), key=lambda item: int(item.get("position", 0))):

        name_value = channel_data.get("name")

        if not name_value or discord.utils.get(guild.text_channels, name=name_value):

            continue

        category = categories_by_name.get(channel_data.get("category"))

        try:

            channel = await guild.create_text_channel(

                name_value[:100],

                category=category,

                topic=channel_data.get("topic"),

                slowmode_delay=int(channel_data.get("slowmode_delay", 0)),

                nsfw=bool(channel_data.get("nsfw", False)),

                reason=f"Backup load par {author}",

            )

            await channel.edit(position=int(channel_data.get("position") or channel.position), reason=f"Backup load par {author}")

            created_channels += 1

        except discord.HTTPException:

            continue

    return (

        f"Backup `{name}` chargée: "

        f"{deleted_roles} rôles, {deleted_categories} catégories, {deleted_channels} salons supprimés. "

        f"{created_roles} rôles, {created_categories} catégories, {created_channels} salons créés."

    )





async def ask_backup_rename_name(interaction: discord.Interaction, old_name: str) -> None:

    if not interaction.channel or not interaction.guild or not isinstance(interaction.user, discord.Member):

        await interaction.response.send_message("Impossible ici.", ephemeral=True)

        return

    if not await has_owner_access(interaction.user):

        await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

        return



    await interaction.response.send_message(f"Envoie le nouveau nom pour la backup `{old_name}`.\nTape `cancel` pour annuler.")

    prompt_message = await interaction.original_response()



    def check(message: discord.Message) -> bool:

        return message.author.id == interaction.user.id and message.channel.id == interaction.channel.id and not message.author.bot



    try:

        message = await bot.wait_for("message", timeout=90, check=check)

    except asyncio.TimeoutError:

        await interaction.followup.send("Temps écoulé.", ephemeral=True)

        return



    content = message.content.strip()

    backups = dict(global_backups())

    if content.lower() == "cancel":

        done_text = "Annulé."

    elif old_name not in backups:

        done_text = "Backup introuvable."

    elif not content:

        done_text = "Nom invalide."

    else:

        new_name = content[:60]

        backup_data = backups.pop(old_name)

        if new_name in backups:

            done_text = f"Une backup `{new_name}` existe déjà."

            backups[old_name] = backup_data

            replace_global_backups(backups)

        else:

            backups[new_name] = backup_data

            replace_global_backups(backups)

            done_text = f"Backup `{old_name}` renommée en `{new_name}`."



    done_message = await interaction.followup.send(done_text, wait=True)

    if interaction.message:

        await interaction.message.edit(embed=backup_panel_embed(), view=BackupSettingsView())

    await asyncio.sleep(2)

    for cleanup in (prompt_message, message, done_message):

        try:

            await cleanup.delete()

        except discord.HTTPException:

            pass





async def ask_backup_value(interaction: discord.Interaction, action: str) -> None:

    if not interaction.channel or not interaction.guild or not isinstance(interaction.user, discord.Member):

        await interaction.response.send_message("Impossible ici.", ephemeral=True)

        return

    if not await has_owner_access(interaction.user):

        await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

        return

    prompts = {

        "create": "Envoie le nom de la backup à créer.",

        "load": "Envoie le nom de la backup à charger.",

        "rename": "Envoie l'ancien nom puis le nouveau nom, exemple `default serveur-1`.",

    }

    await interaction.response.send_message(f"{prompts[action]}\nTape `cancel` pour annuler.")

    prompt_message = await interaction.original_response()



    def check(message: discord.Message) -> bool:

        return message.author.id == interaction.user.id and message.channel.id == interaction.channel.id and not message.author.bot



    try:

        message = await bot.wait_for("message", timeout=90, check=check)

    except asyncio.TimeoutError:

        await interaction.followup.send("Temps écoulé.", ephemeral=True)

        return



    content = message.content.strip()

    if content.lower() == "cancel":

        done_text = "Annulé."

    elif action == "create":

        done_text = await perform_backup_create(interaction.guild, content[:60] or "default")

    elif action == "load":

        done_text = await perform_backup_load(interaction.guild, interaction.user, content[:60] or "default")

    else:

        parts = content.split(maxsplit=1)

        backups = dict(global_backups())

        if len(parts) != 2:

            done_text = "Format invalide. Exemple: `ancienne nouvelle`."

        elif parts[0] not in backups:

            done_text = "Backup introuvable."

        else:

            backups[parts[1][:60]] = backups.pop(parts[0])

            replace_global_backups(backups)

            done_text = f"Backup `{parts[0]}` renommée en `{parts[1][:60]}`."



    done_message = await interaction.followup.send(done_text, wait=True)

    if interaction.message:

        await interaction.message.edit(embed=backup_panel_embed(), view=BackupSettingsView())

    await asyncio.sleep(2)

    for cleanup in (prompt_message, message, done_message):

        try:

            await cleanup.delete()

        except discord.HTTPException:

            pass





class BackupSettingsSelect(discord.ui.Select):

    def __init__(self) -> None:

        options = [

            discord.SelectOption(label="💾 Faire une backup", value="create"),

            discord.SelectOption(label="📥 Mettre une backup", value="load"),

            discord.SelectOption(label="✏️ Renommer une backup", value="rename"),

            discord.SelectOption(label="🗑️ Supprimer une backup", value="delete"),

            discord.SelectOption(label="📜 Backuplist", value="list"),

        ]

        super().__init__(placeholder="💾 Gérer les backups", min_values=1, max_values=1, options=options)



    async def callback(self, interaction: discord.Interaction) -> None:

        set_current_guild(interaction.guild)

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        choice = self.values[0]

        if choice == "list":

            await interaction.response.edit_message(embed=backup_list_embed(), view=BackupListView())

            return

        if choice == "load":

            await interaction.response.edit_message(

                embed=backup_action_embed("📥 Mettre une backup", "Choisis la backup à charger dans le menu."),

                view=BackupLoadView(),

            )

            return

        if choice == "rename":

            await interaction.response.edit_message(embed=backup_rename_embed(), view=BackupRenameView())

            return

        if choice == "delete":

            await interaction.response.edit_message(

                embed=backup_action_embed("🗑️ Supprimer une backup", "Choisis la backup à supprimer dans le menu."),

                view=BackupDeleteView(),

            )

            return

        await ask_backup_value(interaction, choice)





class BackupSettingsView(discord.ui.View):

    def __init__(self) -> None:

        super().__init__(timeout=None)

        self.add_item(BackupSettingsSelect())





def backup_select_options(empty_description: str) -> list[discord.SelectOption]:

    backups = global_backups()

    options = [

        discord.SelectOption(

            label=f"💾 {name}"[:100],

            value=name,

            description=f"{len(data.get('roles', []))} rôles | {len(data.get('text_channels', []))} salons"[:100],

        )

        for name, data in list(backups.items())[:25]

    ]

    if not options:

        options = [discord.SelectOption(label="Aucune backup", value="none", description=empty_description)]

    return options





class BackupLoadSelect(discord.ui.Select):

    def __init__(self) -> None:

        super().__init__(

            placeholder="Sélectionne la backup à charger",

            min_values=1,

            max_values=1,

            options=backup_select_options("Crée une backup avant d'en charger une."),

            row=0,

        )



    async def callback(self, interaction: discord.Interaction) -> None:

        set_current_guild(interaction.guild)

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        if self.values[0] == "none":

            await interaction.response.send_message("Aucune backup disponible.", ephemeral=True)

            return

        await interaction.response.edit_message(

            embed=backup_confirm_embed(self.values[0]),

            view=BackupConfirmLoadView(self.values[0]),

        )





class BackupDeleteSelect(discord.ui.Select):

    def __init__(self) -> None:

        super().__init__(

            placeholder="Sélectionne la backup à supprimer",

            min_values=1,

            max_values=1,

            options=backup_select_options("Crée une backup avant d'en supprimer une."),

            row=0,

        )



    async def callback(self, interaction: discord.Interaction) -> None:

        set_current_guild(interaction.guild)

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        selected = self.values[0]

        if selected == "none":

            await interaction.response.send_message("Aucune backup disponible.", ephemeral=True)

            return

        backups = dict(global_backups())

        if selected not in backups:

            await interaction.response.send_message("Backup introuvable.", ephemeral=True)

            return

        backups.pop(selected)

        replace_global_backups(backups)

        await interaction.response.edit_message(

            embed=backup_action_embed("Supprimer une backup", f"Backup `{selected}` supprimée."),

            view=BackupDeleteView(),

        )





class BackupConfirmLoadView(discord.ui.View):

    def __init__(self, backup_name: str) -> None:

        super().__init__(timeout=None)

        self.backup_name = backup_name



    @discord.ui.button(label="Confirmer le chargement", style=discord.ButtonStyle.danger, row=0)

    async def confirm_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:

        set_current_guild(interaction.guild)

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        await interaction.response.defer(ephemeral=True)

        result = await perform_backup_load(interaction.guild, interaction.user, self.backup_name)

        await interaction.followup.send(result, ephemeral=True)



    @discord.ui.button(label="Retour", style=discord.ButtonStyle.secondary, row=0)

    async def back_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:

        set_current_guild(interaction.guild)

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        await interaction.response.edit_message(

            embed=backup_action_embed("📥 Mettre une backup", "Choisis la backup à charger dans le menu."),

            view=BackupLoadView(),

        )





class BackupLoadView(discord.ui.View):

    def __init__(self) -> None:

        super().__init__(timeout=None)

        self.add_item(BackupLoadSelect())



    @discord.ui.button(label="Retour", style=discord.ButtonStyle.secondary, row=1)

    async def back_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:

        set_current_guild(interaction.guild)

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        await interaction.response.edit_message(embed=backup_panel_embed(), view=BackupSettingsView())





class BackupDeleteView(discord.ui.View):

    def __init__(self) -> None:

        super().__init__(timeout=None)

        self.add_item(BackupDeleteSelect())



    @discord.ui.button(label="Retour", style=discord.ButtonStyle.secondary, row=1)

    async def back_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:

        set_current_guild(interaction.guild)

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        await interaction.response.edit_message(embed=backup_panel_embed(), view=BackupSettingsView())





class BackupListView(discord.ui.View):

    def __init__(self) -> None:

        super().__init__(timeout=None)



    @discord.ui.button(label="Retour", style=discord.ButtonStyle.secondary, row=0)

    async def back_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:

        set_current_guild(interaction.guild)

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        await interaction.response.edit_message(embed=backup_panel_embed(), view=BackupSettingsView())





class BackupRenameSelect(discord.ui.Select):

    def __init__(self) -> None:

        super().__init__(

            placeholder="Sélectionne la backup à renommer",

            min_values=1,

            max_values=1,

            options=backup_select_options("Crée une backup avant de renommer."),

            row=0,

        )



    async def callback(self, interaction: discord.Interaction) -> None:

        set_current_guild(interaction.guild)

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        if self.values[0] == "none":

            await interaction.response.send_message("Aucune backup disponible.", ephemeral=True)

            return

        await ask_backup_rename_name(interaction, self.values[0])





class BackupRenameView(discord.ui.View):

    def __init__(self) -> None:

        super().__init__(timeout=None)

        self.add_item(BackupRenameSelect())



    @discord.ui.button(label="Retour", style=discord.ButtonStyle.secondary, row=1)

    async def back_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:

        set_current_guild(interaction.guild)

        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):

            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)

            return

        await interaction.response.edit_message(embed=backup_panel_embed(), view=BackupSettingsView())





@bot.group(name="backup", invoke_without_command=True)

@is_admin()

async def backup(ctx: commands.Context) -> None:

    await ctx.send(embed=backup_panel_embed(), view=BackupSettingsView())





@backup.command(name="create")

@is_admin()

async def backup_create(ctx: commands.Context, name: str = "default") -> None:

    await ctx.reply(await perform_backup_create(ctx.guild, name))





@backup.command(name="load")

@is_admin()

async def backup_load(ctx: commands.Context, name: str = "default") -> None:

    await ctx.reply(await perform_backup_load(ctx.guild, ctx.author, name))





@bot.command(name="backuplist")

@is_admin()

async def backuplist(ctx: commands.Context) -> None:

    await ctx.send(embed=backup_list_embed())





@bot.command(name="say")

@can_use("say")

async def say(ctx: commands.Context, *, message: str) -> None:

    try:

        await ctx.message.delete()

    except discord.HTTPException:

        pass

    await ctx.send(message)





@bot.command(name="avatar")

@can_use("avatar")

async def avatar(ctx: commands.Context, member: discord.Member | None = None) -> None:

    target = member or ctx.author

    embed = discord.Embed(title=f"Avatar de {target}", color=discord.Color.blurple())

    embed.set_image(url=target.display_avatar.url)

    await ctx.send(embed=embed)





@bot.command(name="banner")

@can_use("banner")

async def banner(ctx: commands.Context, member: discord.Member | None = None) -> None:

    target = member or ctx.author

    user = await bot.fetch_user(target.id)

    if not user.banner:

        await ctx.reply("Cet utilisateur n'a pas de bannière.")

        return

    embed = discord.Embed(title=f"Bannière de {target}", color=discord.Color.blurple())

    embed.set_image(url=user.banner.url)

    await ctx.send(embed=embed)





@bot.command(name="emoji")

@can_use("emoji")

async def emoji(ctx: commands.Context, emoji_value: str) -> None:

    if not ctx.guild.me.guild_permissions.manage_emojis_and_stickers:

        await ctx.reply("Il me manque la permission Gérer les emojis et stickers.")

        return

    inferred_name = custom_emoji_name(emoji_value)

    if inferred_name:

        name = inferred_name

        image_url = emoji_url_from_value(emoji_value)

    else:

        asset = unicode_emoji_asset(emoji_value)

        if not asset:

            await ctx.reply("Envoie seulement un emoji, exemple `.emoji 🐌` ou `.emoji <:emoji:123456789012345678>`.")

            return

        name, image_url = asset

    if not image_url:

        await ctx.reply("Envoie seulement un emoji, exemple `.emoji 🐌` ou `.emoji <:emoji:123456789012345678>`.")

        return

    try:

        image_bytes = await fetch_image_bytes(image_url)

        created = await ctx.guild.create_custom_emoji(name=clean_emoji_name(name), image=image_bytes, reason=f"Emoji par {ctx.author}")

    except (discord.HTTPException, aiohttp.ClientError, ValueError, asyncio.TimeoutError) as error:

        await ctx.reply(f"Impossible de créer l'emoji: `{error}`")

        return

    await ctx.reply(f"Emoji créé: {created}")





@bot.command(name="botname")

@is_admin()

async def botname(ctx: commands.Context, *, name: str) -> None:

    if len(name) > 32:

        await ctx.reply("Le nom du bot doit faire 32 caractères maximum.")

        return

    update_active_config({"bot_profile": {"name": name}})

    try:

        await bot.user.edit(username=name)

    except discord.HTTPException as error:

        await ctx.reply(f"Nom sauvegardé, mais Discord a refusé la modification: `{error}`")

        return

    await ctx.reply(f"Nom du bot mis à jour: `{name}`.")





@bot.command(name="botpic")

@is_admin()

async def botpic(ctx: commands.Context, url: str) -> None:

    update_active_config({"bot_profile": {"avatar_url": url}})

    try:

        avatar_bytes = await fetch_image_bytes(url)

        await bot.user.edit(avatar=avatar_bytes)

    except (discord.HTTPException, aiohttp.ClientError, ValueError, asyncio.TimeoutError) as error:

        await ctx.reply(f"Photo sauvegardée, mais impossible de l'appliquer: `{error}`")

        return

    await ctx.reply("Photo du bot mise à jour.")





@bot.command(name="watch")

@is_admin()

async def watch(ctx: commands.Context, *, phrase: str) -> None:

    from config_store import update_config



    update_active_config({"bot_profile": {"activity_type": "watching", "activity_text": phrase}})

    await bot.change_presence(status=make_status(), activity=discord.Activity(type=discord.ActivityType.watching, name=phrase))

    await ctx.reply(f"Le bot regarde maintenant: `{phrase}`.")





@bot.command(name="listen")

@is_admin()

async def listen(ctx: commands.Context, *, phrase: str) -> None:

    from config_store import update_config



    update_active_config({"bot_profile": {"activity_type": "listening", "activity_text": phrase}})

    await bot.change_presence(status=make_status(), activity=discord.Activity(type=discord.ActivityType.listening, name=phrase))

    await ctx.reply(f"Le bot écoute maintenant: `{phrase}`.")





@bot.group(name="bot", invoke_without_command=True)

@is_admin()

async def bot_group(ctx: commands.Context) -> None:

    await ctx.reply("Utilise `.bot info`, `.botname <nom>` ou `.botpic <url>`.")





@bot_group.command(name="info")

@is_admin()

async def bot_info(ctx: commands.Context) -> None:

    cfg = bot_profile_config()

    status = (cfg.get("status") or "online").lower()

    status_label = {

        "online": "Online",

        "idle": "Inactif",

        "dnd": "Ne pas déranger",

        "invisible": "Invisible",

    }.get(status, "Online")

    embed = discord.Embed(title="Informations du bot", color=discord.Color.blurple())

    embed.add_field(name="Nom Du Bot", value=cfg.get("name") or "Non configuré", inline=True)

    embed.add_field(name="Statut", value=status_label, inline=True)

    if bot.user and bot.user.display_avatar:

        embed.set_thumbnail(url=bot.user.display_avatar.url)

    await ctx.send(embed=embed)





@bot_group.command(name="apply")

@is_admin()

async def bot_apply(ctx: commands.Context) -> None:

    try:

        changes = await apply_bot_profile()

    except discord.HTTPException as error:

        await ctx.reply(f"Discord a refusé la modification: `{error}`")

        return

    except (aiohttp.ClientError, ValueError, asyncio.TimeoutError) as error:

        await ctx.reply(f"Impossible de charger l'image: `{error}`")

        return



    await ctx.reply(f"Profil bot appliqué: {', '.join(changes)}.")





@bot_group.command(name="presence")

@is_admin()

async def bot_presence(ctx: commands.Context) -> None:

    await apply_presence()

    await ctx.reply("Présence du bot mise à jour.")





@bot.event

async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:

    if isinstance(error, commands.MissingPermissions):

        await ctx.reply("Tu n'as pas la permission pour cette commande.")

    elif isinstance(error, commands.CheckFailure):

        await ctx.reply("Tu n'as pas la permission de faire cette commande.")

    elif isinstance(error, commands.MissingRequiredArgument):

        await ctx.reply(f"Argument manquant: `{error.param.name}`.")

    elif isinstance(error, commands.BadArgument):

        await ctx.reply("Argument invalide.")

    else:

        raise error





if __name__ == "__main__":

    token = os.getenv("DISCORD_TOKEN")

    if not token:

        raise RuntimeError("DISCORD_TOKEN est manquant. Copie .env.example en .env puis ajoute ton token.")

    bot.run(token)



