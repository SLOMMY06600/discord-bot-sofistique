from __future__ import annotations

import asyncio
import os
import re
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import aiohttp
import discord
from discord.ext import commands

from config_store import load_config, update_config
from env_loader import load_env


load_env()

INVITE_RE = re.compile(r"(discord\.gg/|discord(?:app)?\.com/invite/)", re.IGNORECASE)
LINK_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
ANTI_RAID_KEYS = (
    "enabled",
    "antilink",
    "antieveryone",
    "antiban",
    "antiunban",
    "antikick",
    "antibot",
    "antiaddrole",
    "antidelrole",
    "antichannel",
)
ANTI_RAID_PROTECTIONS = (
    ("Antilink", "antilink"),
    ("Antieveryone", "antieveryone"),
    ("Antiban", "antiban"),
    ("Antiunban", "antiunban"),
    ("Antikick", "antikick"),
    ("Antibot", "antibot"),
    ("Antirole", "antiaddrole"),
    ("Antidelrole", "antidelrole"),
    ("Antichannel", "antichannel"),
)
SANCTION_ACTIONS = ("ban", "kick", "derank", "none")

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix=lambda *_: load_config()["prefix"], intents=intents)
bot.remove_command("help")
join_history: dict[int, deque[datetime]] = defaultdict(deque)
locked_channels: dict[int, list[tuple[int, discord.PermissionOverwrite]]] = defaultdict(list)
ticket_views_added = False
application_owner_ids: set[int] = set()


def anti_raid_config() -> dict:
    return load_config()["anti_raid"]


def sanction_config() -> dict:
    return load_config()["sanctions"]


def access_config() -> dict:
    return load_config()["access"]


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


async def is_guard_bypassed(actor: discord.abc.User | None) -> bool:
    if not actor:
        return False
    if bot.user and actor.id == bot.user.id:
        return True
    if is_buyer_id(actor.id) or is_owner_id(actor.id) or is_whitelisted_id(actor.id):
        return True
    return await is_application_owner_id(actor.id)


def is_whitelisted_id(user_id: int) -> bool:
    return str(user_id) in {str(item) for item in access_config().get("whitelist", [])}


def is_blacklisted_id(user_id: int) -> bool:
    return str(user_id) in {str(item) for item in access_config().get("blacklist", [])}


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


@bot.check
async def owner_only_commands(ctx: commands.Context) -> bool:
    if not ctx.guild or not isinstance(ctx.author, discord.Member):
        return False
    command_name = ctx.command.name if ctx.command else ""
    return await has_owner_access(ctx.author) or has_command_role(ctx.author, command_name)


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
    return guild.get_role(role_id) if role_id else None


def ticket_config() -> dict:
    return load_config()["tickets"]


def update_ticket_config(values: dict) -> dict:
    return update_config({"tickets": values})["tickets"]


def bot_profile_config() -> dict:
    return load_config()["bot_profile"]


def parse_hex_color(value: str) -> discord.Color:
    cleaned = value.strip().removeprefix("#")
    try:
        return discord.Color(int(cleaned, 16))
    except ValueError:
        return discord.Color.blurple()


def make_configured_embed() -> discord.Embed:
    cfg = load_config()["embed"]
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
    return update_config({"embed": values})["embed"]


def make_embed_view() -> discord.ui.View | None:
    cfg = load_config()["embed"]
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
    if not actor or await is_guard_bypassed(actor):
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
            if is_whitelisted_id(member.id):
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
        return False, "Tu ne peux pas ouvrir de ticket avec un role interdit."
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
        color=parse_hex_color(cfg.get("embed_color") or "#69d6a2"),
    )
    if option_label:
        embed.add_field(name="Option", value=option_label, inline=True)
    embed.set_footer(text=f"Ouvert par {opener}")
    manage_view = TicketManageView()
    mention_ids = role_ids_from_config((selected_option or {}).get("mentioned_role_ids", []))
    mention_text = " ".join(f"<@&{role_id}>" for role_id in mention_ids)
    allowed_mentions = discord.AllowedMentions(users=True, roles=True, everyone=False)
    content = f"{opener.mention} {mention_text}".strip()
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
    max_per_user = max(1, int(cfg.get("max_per_user", 1)))
    if open_ticket_count(interaction.guild, interaction.user.id) >= max_per_user:
        await interaction.response.send_message(
            f"Tu as déjà le maximum de tickets ouverts ({max_per_user}).",
            ephemeral=True,
        )
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
        await open_ticket_from_interaction(interaction, self.values[0])


class TicketCreateButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="Ouvrir un ticket", style=discord.ButtonStyle.green, custom_id="ticket:create")

    async def callback(self, interaction: discord.Interaction) -> None:
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
        "**.antiraid** - ouvre la configuration interactive anti-raid\n"
        "**.raidstatus** - affiche l'état des protections\n"
        "**.allraid on/off** - active ou désactive toutes les protections\n"
        "**.sanction** - configure les sanctions anti-raid\n"
        "**.antilink on/off** - bloque les liens\n"
        "**.antieveryone on/off** - bloque @everyone et @here\n"
        "**.antiban on/off** - annule les bans suspects\n"
        "**.antiunban on/off** - annule les unbans suspects\n"
        "**.antikick on/off** - détecte les kicks suspects\n"
        "**.antibot on/off** - bloque les bots ajoutés sans autorisation\n"
        "**.antirole on/off** - protège les rôles créés\n"
        "**.antidelrole on/off** - restaure les rôles supprimés\n"
        "**.antichannel on/off** - protège les salons",
    ),
    "tickets": (
        "Tickets",
        "**.ticket** - ouvre la configuration interactive des tickets\n"
        "**.close** - ferme le ticket actuel\n"
        "**.rename <nom>** - renomme le salon ticket\n"
        "**.adduser @membre** - ajoute quelqu'un au ticket\n"
        "**.deluser @membre** - retire quelqu'un du ticket",
    ),
    "embeds": (
        "Embeds",
        "**.embed** - ouvre la configuration interactive de l'embed\n"
        "**.embed test** - teste l'embed dans le salon actuel",
    ),
    "moderation": (
        "Modération",
        "**.ban @membre [raison]** - bannit un membre\n"
        "**.unban <id>** - débannit un utilisateur par ID\n"
        "**.kick @membre [raison]** - expulse un membre\n"
        "**.clear <nombre>** - supprime des messages\n"
        "**.lock** - verrouille les salons texte\n"
        "**.unlock** - restaure les salons texte verrouillés\n"
        "**.userinfo [@membre]** - infos utilisateur\n"
        "**.serverinfo** - infos serveur",
    ),
    "owner": (
        "Owner",
        "**.buyer <id/@membre>** - donne l'accès total buyer\n"
        "**.unbuyer <id/@membre>** - retire l'accès buyer\n"
        "**.buyerlist** - affiche les buyers\n"
        "**.owner <id/@membre>** - ajoute un owner bot\n"
        "**.unowner <id/@membre>** - retire un owner bot\n"
        "**.ownerlist** - affiche les owners",
    ),
    "wl": (
        "WL",
        "**.wl <id/@membre>** - ajoute en whitelist anti-derank\n"
        "**.unwl <id/@membre>** - retire de la whitelist\n"
        "**.wllist** - affiche les personnes whitelist",
    ),
    "setperm": (
        "Setperm / Unsetperm",
        "**.setperm <commande> @role** - autorise un rôle de façon permanente (`help`, `setperm`, `unsetperm`, `ban`, `unban`, `kick`, `clear`, `addrole`, `delrole`, `rename`)\n"
        "**.unsetperm <commande> @role** - retire une autorisation\n"
        "**.addrole @membre @role** - ajoute un rôle\n"
        "**.delrole @membre @role** - retire un rôle\n"
        "**.rename @role <nom>** - renomme un rôle",
    ),
    "blacklist": (
        "Blacklist",
        "**.bl <id/@membre>** - blacklist et ban\n"
        "**.unbl <id/@membre>** - retire de la blacklist",
    ),
    "bot": (
        "Bot",
        "**.bot info** - affiche les infos du bot\n"
        "**.botname <nom>** - change le nom du bot\n"
        "**.botpic <url>** - change la photo du bot\n"
        "**.watch <phrase>** - met l'activité Regarde\n"
        "**.listen <phrase>** - met l'activité Écoute\n"
        "**.bot apply** - force l'application du nom/logo/présence\n"
        "**.bot presence** - met à jour le statut Discord",
    ),
    "logs": (
        "Logs",
        "**.autologs** - crée automatiquement les salons de logs",
    ),
}


class HelpSelect(discord.ui.Select):
    def __init__(self) -> None:
        emojis = {
            "antiraid": "🛡️",
            "tickets": "🎫",
            "embeds": "📝",
            "moderation": "🔨",
            "owner": "👑",
            "wl": "✅",
            "setperm": "🔐",
            "blacklist": "⛔",
            "bot": "🤖",
            "logs": "📚",
        }
        options = [
            discord.SelectOption(
                label=title,
                value=value,
                description=f"Voir les commandes {title.lower()}",
                emoji=emojis.get(value),
            )
            for value, (title, _) in HELP_SECTIONS.items()
        ]
        super().__init__(placeholder="Choisis une catégorie", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        title, description = HELP_SECTIONS[self.values[0]]
        embed = discord.Embed(title=f"Help - {title}", description=description, color=discord.Color.blurple())
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
        color=parse_hex_color(cfg.get("embed_color") or "#69d6a2"),
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
        color=parse_hex_color(cfg.get("embed_color") or "#69d6a2"),
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
        color=parse_hex_color(cfg.get("embed_color") or "#69d6a2"),
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
            discord.SelectOption(label="Modifier la catégorie", value="category_id", emoji="📁"),
            discord.SelectOption(label="Modifier l'emoji", value="emoji", emoji="🙂"),
            discord.SelectOption(label="Modifier le texte", value="label", emoji="🖌️"),
            discord.SelectOption(label="Modifier la description", value="description", emoji="💬"),
            discord.SelectOption(label="Modifier les rôles mentionnés", value="mentioned_role_ids", emoji="🔔"),
            discord.SelectOption(label="Modifier le message d'ouverture", value="open_message", emoji="📜"),
            discord.SelectOption(label="Modifier le salon de logs", value="log_channel_id", emoji="📡"),
            discord.SelectOption(label="Modifier les rôles autorisés", value="access_role_ids", emoji="🛡️"),
        ]
        super().__init__(placeholder="Fais un choix", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
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
        choices.append(discord.SelectOption(label="Ajouter une option", value="add", emoji="➕"))
        super().__init__(placeholder="Gerer les options", min_values=1, max_values=1, options=choices, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
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
                emoji=option.get("emoji") or None,
            )
            for index, option in enumerate(ticket_items[:23])
        ]
        options.append(discord.SelectOption(label="Ajouter une option", value="add", emoji="➕"))
        super().__init__(placeholder="Gerer les options", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
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
            discord.SelectOption(label="Type bouton/sélecteur", value="panel_type", emoji="🔘"),
            discord.SelectOption(label="Modifier le salon", value="panel_channel_id", emoji="📨"),
            discord.SelectOption(label="Modifier les rôles requis", value="required_role_ids", emoji="🛡️"),
            discord.SelectOption(label="Modifier les rôles interdits", value="forbidden_role_ids", emoji="⛔"),
            discord.SelectOption(label="Bouton close", value="close_button", emoji="✅"),
            discord.SelectOption(label="Bouton claim", value="claim_button", emoji="✅"),
            discord.SelectOption(label="Suppression tickets fermés", value="auto_delete", emoji="🗑️"),
            discord.SelectOption(label="Fermer si le membre quitte", value="auto_leave", emoji="🚪"),
            discord.SelectOption(label="Transcript MP", value="transcript_dm", emoji="📩"),
        ]
        super().__init__(placeholder="Configuration des tickets", min_values=1, max_values=1, options=options, row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):
            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)
            return

        choice = self.values[0]
        cfg = ticket_config()
        updates = {}
        if choice in {"panel_channel_id", "required_role_ids", "forbidden_role_ids"}:
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
            color=parse_hex_color(cfg.get("embed_color") or "#69d6a2"),
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

    cfg = load_config()["embed"]
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
            discord.SelectOption(label="Modifier le titre", value="title", emoji="✏️"),
            discord.SelectOption(label="Modifier la description", value="description", emoji="💬"),
            discord.SelectOption(label="Ajouter un Field", value="field", emoji="➕"),
            discord.SelectOption(label="Retirer un Field", value="remove_field", emoji="➖"),
            discord.SelectOption(label="Modifier le thumbnail", value="thumbnail", emoji="🏷️"),
            discord.SelectOption(label="Modifier l'image", value="image", emoji="🖼️"),
            discord.SelectOption(label="Modifier la couleur", value="color", emoji="🔴"),
            discord.SelectOption(label="Modifier le footer", value="footer", emoji="🔻"),
            discord.SelectOption(label="Modifier l'auteur", value="author", emoji="🔶"),
            discord.SelectOption(label="Modifier l'URL", value="url", emoji="➡️"),
            discord.SelectOption(label="Modifier le timestamp", value="timestamp", emoji="🕘"),
            discord.SelectOption(label="Copier un embed existant", value="copy_message", emoji="📥"),
            discord.SelectOption(label="Ajouter un message à l'embed", value="add_message", emoji="🪄"),
            discord.SelectOption(label="Ajouter un bouton d'URL", value="button", emoji="✉️"),
        ]
        super().__init__(
            placeholder="Clique ici pour modifier l'embed",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):
            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)
            return
        choice = self.values[0]
        if choice == "timestamp":
            cfg = load_config()["embed"]
            update_embed_config({"timestamp": not cfg.get("timestamp", False)})
            await interaction.response.edit_message(embed=embed_panel_embed(), view=EmbedSettingsView())
            return
        if choice == "remove_field":
            cfg = load_config()["embed"]
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
        ticket_views_added = True
    await apply_presence()
    print(f"Connecte en tant que {bot.user} (ID: {bot.user.id})")


def get_named_log_channel(guild: discord.Guild, name: str) -> discord.TextChannel | None:
    channel = discord.utils.get(guild.text_channels, name=name)
    return channel if isinstance(channel, discord.TextChannel) else None


async def log_message_event(message: discord.Message, action: str) -> None:
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
    if message.author.bot or not message.guild:
        return

    if bot.user and bot.user in message.mentions and message.content.strip() in {bot.user.mention, f"<@!{bot.user.id}>"}:
        cfg = bot_profile_config()
        prefix = load_config()["prefix"]
        response = (cfg.get("ping_message") or "Mon préfixe est `{prefix}`.").replace("{prefix}", prefix)
        await message.reply(response, mention_author=False)
        return

    cfg = anti_raid_config()
    if cfg["enabled"] and not message.author.guild_permissions.manage_messages and not await is_guard_bypassed(message.author):
        should_delete = False
        reason = ""

        if cfg.get("antilink") and (INVITE_RE.search(message.content) or LINK_RE.search(message.content)):
            should_delete = True
            reason = "lien interdit"
        elif cfg.get("antieveryone") and ("@everyone" in message.content or "@here" in message.content):
            should_delete = True
            reason = "everyone/here interdit"

        if should_delete:
            await punish_message_spam(message, reason)
            guard_key = "antilink" if reason == "lien interdit" else "antieveryone"
            await apply_sanction(message.guild, message.author, guard_key, f"{guard_key}: {reason}")
            return

    await log_message_event(message, "envoyé")
    await bot.process_commands(message)


@bot.event
async def on_message_delete(message: discord.Message) -> None:
    await log_message_event(message, "supprimé")


@bot.event
async def on_bulk_message_delete(messages: list[discord.Message]) -> None:
    for message in messages[:10]:
        await log_message_event(message, "supprimé")


@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User) -> None:
    cfg = anti_raid_config()
    if not cfg.get("enabled") or not cfg.get("antiban"):
        return
    actor = await audit_user(guild, discord.AuditLogAction.ban, user.id)
    if await is_guard_bypassed(actor):
        return
    try:
        await guild.unban(user, reason="Antiban: ban annule")
        await log_guard(guild, "Antiban", f"ban de {user} annule", actor)
        await apply_sanction(guild, actor, "antiban", f"Antiban: ban non autorisé de {user}")
    except discord.Forbidden:
        await log_guard(guild, "Antiban", f"ban detecte sur {user}, mais permission unban manquante", actor)


@bot.event
async def on_member_join(member: discord.Member) -> None:
    cfg = anti_raid_config()
    if member.bot and cfg.get("enabled") and cfg.get("antibot"):
        actor = await audit_user(member.guild, discord.AuditLogAction.bot_add, member.id)
        if not await is_guard_bypassed(actor):
            try:
                await member.ban(reason="Antibot: bot ajouté sans autorisation", delete_message_seconds=0)
                await log_guard(member.guild, "Antibot", f"bot {member} banni", actor)
                await apply_sanction(member.guild, actor, "antibot", f"Antibot: ajout non autorisé de {member}")
            except discord.Forbidden:
                await log_guard(member.guild, "Antibot", f"bot {member} détecté, mais permission ban manquante", actor)
            return

    if not is_blacklisted_id(member.id):
        return
    try:
        await member.ban(reason="Blacklist: retour interdit", delete_message_seconds=0)
    except discord.Forbidden:
        await log_event(member.guild, f"Blacklist: impossible de bannir {member}.")


@bot.event
async def on_member_unban(guild: discord.Guild, user: discord.User) -> None:
    cfg = anti_raid_config()
    if not cfg.get("enabled") or not cfg.get("antiunban"):
        return
    actor = await audit_user(guild, discord.AuditLogAction.unban, user.id)
    if await is_guard_bypassed(actor):
        return
    try:
        await guild.ban(user, reason="Antiunban: unban annule")
        await log_guard(guild, "Antiunban", f"unban de {user} annule", actor)
        await apply_sanction(guild, actor, "antiunban", f"Antiunban: unban non autorisé de {user}")
    except discord.Forbidden:
        await log_guard(guild, "Antiunban", f"unban detecte sur {user}, mais permission ban manquante", actor)


@bot.event
async def on_member_remove(member: discord.Member) -> None:
    tickets = ticket_config()
    if tickets.get("auto_close_on_leave"):
        marker = f"ticket_owner:{member.id}"
        for channel in member.guild.text_channels:
            if channel.topic and marker in channel.topic:
                try:
                    await channel.delete(reason=f"Ticket ferme automatiquement: {member} a quitte le serveur")
                except discord.Forbidden:
                    continue

    cfg = anti_raid_config()
    if not cfg.get("enabled") or not cfg.get("antikick"):
        return
    actor = await audit_user(member.guild, discord.AuditLogAction.kick, member.id)
    if await is_guard_bypassed(actor):
        return
    if actor:
        await log_guard(member.guild, "Antikick", f"kick detecte sur {member}", actor)
        await apply_sanction(member.guild, actor, "antikick", f"Antikick: kick non autorisé de {member}")


@bot.event
async def on_guild_role_create(role: discord.Role) -> None:
    cfg = anti_raid_config()
    if not cfg.get("enabled") or not cfg.get("antiaddrole"):
        return
    actor = await audit_user(role.guild, discord.AuditLogAction.role_create, role.id)
    if await is_guard_bypassed(actor):
        return
    try:
        await role.delete(reason="Antiaddrole: role cree annule")
        await log_guard(role.guild, "Antiaddrole", f"role {role.name} supprime", actor)
        await apply_sanction(role.guild, actor, "antiaddrole", f"Antiaddrole: création non autorisée de {role.name}")
    except discord.Forbidden:
        await log_guard(role.guild, "Antiaddrole", f"role {role.name} cree, mais permission delete manquante", actor)


@bot.event
async def on_guild_role_delete(role: discord.Role) -> None:
    cfg = anti_raid_config()
    if not cfg.get("enabled") or not cfg.get("antidelrole"):
        return
    actor = await audit_user(role.guild, discord.AuditLogAction.role_delete, role.id)
    if await is_guard_bypassed(actor):
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
    cfg = anti_raid_config()
    if not cfg.get("enabled") or not cfg.get("antichannel"):
        return
    actor = await audit_user(channel.guild, discord.AuditLogAction.channel_create, channel.id)
    if await is_guard_bypassed(actor):
        return
    try:
        await channel.delete(reason="Antichannel: salon cree annule")
        await log_guard(channel.guild, "Antichannel", f"salon {channel.name} supprime", actor)
        await apply_sanction(channel.guild, actor, "antichannel", f"Antichannel: création non autorisée de {channel.name}")
    except discord.Forbidden:
        await log_guard(channel.guild, "Antichannel", f"salon {channel.name} cree, mais permission delete manquante", actor)


@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel) -> None:
    cfg = anti_raid_config()
    if not cfg.get("enabled") or not cfg.get("antichannel"):
        return
    actor = await audit_user(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
    if await is_guard_bypassed(actor):
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


@bot.command(name="raidstatus")
@is_admin()
async def raidstatus(ctx: commands.Context) -> None:
    cfg = anti_raid_config()
    enabled = cfg.get("enabled", False)
    embed = discord.Embed(
        title="Anti-Raid Status",
        description="État des protections Anti Raid.",
        color=discord.Color.green() if enabled else discord.Color.red(),
    )
    embed.add_field(name="Système", value="Activé" if enabled else "Désactivé", inline=True)
    embed.add_field(name="Salon logs", value=str(cfg.get("log_channel_id") or "Non configuré"), inline=True)

    protections = ANTI_RAID_PROTECTIONS
    status_lines = [f"`{key}`: {'ON' if cfg.get(key) else 'OFF'}" for _, key in protections]
    embed.add_field(name="Protections", value="\n".join(status_lines), inline=False)
    sanctions = sanction_config()
    sanction_lines = [f"`{key}`: {sanctions.get(key, 'derank')}" for _, key in protections]
    embed.add_field(name="Sanctions", value="\n".join(sanction_lines), inline=False)
    await ctx.send(embed=embed)


async def set_antiraid_toggle(ctx: commands.Context, key: str, value: str) -> None:
    from config_store import update_config

    if value.lower() not in {"on", "off", "true", "false", "1", "0", "yes", "no"}:
        await ctx.reply("Utilise `on` ou `off`.")
        return
    enabled = value.lower() in {"on", "true", "1", "yes"}
    update_config({"anti_raid": {key: enabled}})
    await ctx.reply(f"{key}: {'on' if enabled else 'off'}.")


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
        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):
            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)
            return
        key = self.values[0]
        cfg = anti_raid_config()
        from config_store import update_config

        if key == "global":
            enabled = not all(cfg.get(item, False) for item in ANTI_RAID_KEYS)
            update_config({"anti_raid": {item: enabled for item in ANTI_RAID_KEYS}})
        else:
            update_config({"anti_raid": {key: not cfg.get(key, False)}})
        await interaction.response.edit_message(embed=antiraid_panel_embed(), view=AntiRaidPanelView())


class AntiRaidPanelView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(AntiRaidToggleSelect())


@bot.command(name="antiraid")
@is_admin()
async def antiraid_panel(ctx: commands.Context) -> None:
    await ctx.send(embed=antiraid_panel_embed(), view=AntiRaidPanelView())


def sanction_panel_embed(selected: str | None = None) -> discord.Embed:
    sanctions = sanction_config()
    lines = []
    for label, key in ANTI_RAID_PROTECTIONS:
        marker = " ➜" if key == selected else ""
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
        if not isinstance(interaction.user, discord.Member) or not await has_owner_access(interaction.user):
            await interaction.response.send_message("Tu n'as pas la permission de faire cette commande.", ephemeral=True)
            return
        if not self.selected:
            await interaction.response.send_message("Choisis d'abord une protection.", ephemeral=True)
            return
        action = self.values[0]
        from config_store import update_config

        update_config({"sanctions": {self.selected: action}})
        await interaction.response.edit_message(embed=sanction_panel_embed(self.selected), view=SanctionPanelView(self.selected))


class SanctionPanelView(discord.ui.View):
    def __init__(self, selected: str | None = None) -> None:
        super().__init__(timeout=None)
        self.add_item(SanctionProtectionSelect(selected))
        self.add_item(SanctionActionSelect(selected))


@bot.command(name="sanction")
@is_admin()
async def sanction_panel(ctx: commands.Context) -> None:
    await ctx.send(embed=sanction_panel_embed(), view=SanctionPanelView())


@bot.command(name="allraid")
@is_admin()
async def allraid(ctx: commands.Context, value: str) -> None:
    if value.lower() not in {"on", "off", "true", "false", "1", "0", "yes", "no"}:
        await ctx.reply("Utilise `on` ou `off`.")
        return
    enabled = value.lower() in {"on", "true", "1", "yes"}
    from config_store import update_config

    update_config({"anti_raid": {key: enabled for key in ANTI_RAID_KEYS}})
    await ctx.reply(f"Toutes les protections anti-raid sont {'activées' if enabled else 'désactivées'}.")


@bot.command(name="autologs")
@is_admin()
async def autologs(ctx: commands.Context) -> None:
    guild = ctx.guild
    category = discord.utils.get(guild.categories, name="Logs")
    if category is None:
        category = await guild.create_category("Logs", reason=f"Autologs par {ctx.author}")

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
            channel = await guild.create_text_channel(channel_name, category=category, reason=f"Autologs par {ctx.author}")
            created.append(channel.mention)

    raid_channel = discord.utils.get(guild.text_channels, name="logs-raid")
    if raid_channel:
        from config_store import update_config

        update_config({"anti_raid": {"log_channel_id": str(raid_channel.id)}})

    await ctx.reply("Salons de logs créés/configurés." + (f"\n{', '.join(created)}" if created else ""))


async def update_command_permission(ctx: commands.Context, command_name: str, role_value: str, add: bool) -> None:
    allowed = {"help", "setperm", "unsetperm", "ban", "unban", "kick", "clear", "addrole", "delrole", "rename"}
    command_name = normalize_command_permission_name(command_name)
    if command_name not in allowed:
        await ctx.reply(f"Commande invalide. Commandes autorisées: `{', '.join(sorted(allowed))}`.")
        return
    role = resolve_role(ctx.guild, role_value)
    if not role:
        await ctx.reply("Rôle invalide.")
        return
    from config_store import update_config

    permissions = access_config().get("command_permissions", {})
    values = {str(item) for item in permissions.get(command_name, [])}
    if add:
        values.add(str(role.id))
        action = "autorisé"
    else:
        values.discard(str(role.id))
        action = "retiré"
    update_config({"access": {"command_permissions": {command_name: sorted(values)}}})
    await ctx.reply(f"{role.mention} {action} pour `.{command_name}`. Permission enregistrée de façon permanente.")


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
    update_config({"access": {"blacklist": sorted(blacklist)}})
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
    update_config({"access": {"blacklist": sorted(blacklist)}})
    await ctx.reply(f"<@{user_id}> (`{user_id}`) retiré de la blacklist.")


async def update_access_list(ctx: commands.Context, list_name: str, user_value: str, add: bool) -> None:
    from config_store import update_config

    user_id = normalize_user_id(user_value)
    if not user_id:
        await ctx.reply("ID ou mention invalide.")
        return

    access = access_config()
    values = {str(item) for item in access.get(list_name, [])}
    if add:
        values.add(str(user_id))
        action = "ajouté"
    else:
        values.discard(str(user_id))
        action = "retiré"

    update_config({"access": {list_name: sorted(values)}})
    await ctx.reply(f"<@{user_id}> (`{user_id}`) {action} dans `{list_name}`.")


@bot.command(name="owner")
@is_admin()
async def owner_add(ctx: commands.Context, user: str) -> None:
    await update_access_list(ctx, "owners", user, True)


@bot.command(name="unowner")
@is_admin()
async def owner_remove(ctx: commands.Context, user: str) -> None:
    await update_access_list(ctx, "owners", user, False)


@bot.command(name="ownerlist")
@is_admin()
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


@bot.command(name="buyer")
@is_admin()
async def buyer_add(ctx: commands.Context, user: str) -> None:
    await update_access_list(ctx, "buyers", user, True)


@bot.command(name="unbuyer")
@is_admin()
async def buyer_remove(ctx: commands.Context, user: str) -> None:
    await update_access_list(ctx, "buyers", user, False)


@bot.command(name="buyerlist")
@is_admin()
async def buyer_list(ctx: commands.Context) -> None:
    buyers = access_config().get("buyers", [])
    text = "\n".join(f"<@{item}> (`{item}`)" for item in buyers) if buyers else "Aucun buyer configuré."
    await ctx.send(text)


@bot.command(name="antilink")
@is_admin()
async def antilink(ctx: commands.Context, value: str) -> None:
    await set_antiraid_toggle(ctx, "antilink", value)


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


@bot.command(name="lock")
@is_admin()
async def lock(ctx: commands.Context) -> None:
    if not isinstance(ctx.channel, discord.TextChannel):
        await ctx.reply("Cette commande doit etre utilisee dans un salon texte.")
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
    await ctx.reply(f"Salon verrouille: {ctx.channel.mention}.")


@bot.command(name="unlock")
@is_admin()
async def unlock(ctx: commands.Context) -> None:
    if not isinstance(ctx.channel, discord.TextChannel):
        await ctx.reply("Cette commande doit etre utilisee dans un salon texte.")
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
    await ctx.reply(f"Salon deverrouille: {ctx.channel.mention}.")


@bot.command(name="ban")
@can_use("ban")
async def ban(ctx: commands.Context, member: discord.Member, *, reason: str = "Raid") -> None:
    await member.ban(reason=f"{reason} - par {ctx.author}", delete_message_seconds=86400)
    await ctx.reply(f"{member} banni.")


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

    await ctx.reply(f"<@{user_id}> (`{user_id}`) débanni.")


@bot.command(name="kick")
@can_use("kick")
async def kick(ctx: commands.Context, member: discord.Member, *, reason: str = "Raid") -> None:
    await member.kick(reason=f"{reason} - par {ctx.author}")
    await ctx.reply(f"{member} expulse.")


@bot.command()
@can_use("clear")
async def clear(ctx: commands.Context, amount: int) -> None:
    amount = max(1, min(amount, 100))
    deleted = await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"{len(deleted) - 1} messages supprimes.", delete_after=5)


@bot.command(name="help", aliases=["aide", "commands"])
async def help_command(ctx: commands.Context) -> None:
    prefix = load_config()["prefix"]
    embed = discord.Embed(
        title="Menu help",
        description=f"Selectionne une categorie dans le menu.\nPrefix actuel: `{prefix}`",
        color=discord.Color.blurple(),
    )
    await ctx.send(embed=embed, view=HelpView())


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
        color=parse_hex_color(cfg.get("embed_color") or "#69d6a2"),
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
async def addrole(ctx: commands.Context, user_value: str, role_value: str) -> None:
    member = await resolve_member(ctx.guild, user_value)
    role = resolve_role(ctx.guild, role_value)
    if not member or not role:
        await ctx.reply("Membre ou rôle invalide.")
        return
    await member.add_roles(role, reason=f"Addrole par {ctx.author}")
    await ctx.reply(f"{role.mention} ajouté à {member.mention}.")


@bot.command(name="delrole")
@can_use("delrole")
async def delrole(ctx: commands.Context, user_value: str, role_value: str) -> None:
    member = await resolve_member(ctx.guild, user_value)
    role = resolve_role(ctx.guild, role_value)
    if not member or not role:
        await ctx.reply("Membre ou rôle invalide.")
        return
    await member.remove_roles(role, reason=f"Delrole par {ctx.author}")
    await ctx.reply(f"{role.mention} retiré de {member.mention}.")


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
    await ctx.channel.edit(name=clean_name, reason=f"Ticket renomme par {ctx.author}")
    await ctx.reply(f"Ticket renomme en `{clean_name}`.")


@bot.group(name="embed", invoke_without_command=True)
@is_admin()
async def embed_group(ctx: commands.Context) -> None:
    await ctx.send(embed=embed_panel_embed(), view=EmbedSettingsView())


@embed_group.command(name="test")
@is_admin()
async def embed_test(ctx: commands.Context) -> None:
    cfg = load_config()["embed"]
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


@bot.command(name="botname")
@is_admin()
async def botname(ctx: commands.Context, *, name: str) -> None:
    if len(name) > 32:
        await ctx.reply("Le nom du bot doit faire 32 caractères maximum.")
        return
    update_config({"bot_profile": {"name": name}})
    try:
        await bot.user.edit(username=name)
    except discord.HTTPException as error:
        await ctx.reply(f"Nom sauvegardé, mais Discord a refusé la modification: `{error}`")
        return
    await ctx.reply(f"Nom du bot mis à jour: `{name}`.")


@bot.command(name="botpic")
@is_admin()
async def botpic(ctx: commands.Context, url: str) -> None:
    update_config({"bot_profile": {"avatar_url": url}})
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

    update_config({"bot_profile": {"activity_type": "watching", "activity_text": phrase}})
    await bot.change_presence(status=make_status(), activity=discord.Activity(type=discord.ActivityType.watching, name=phrase))
    await ctx.reply(f"Le bot regarde maintenant: `{phrase}`.")


@bot.command(name="listen")
@is_admin()
async def listen(ctx: commands.Context, *, phrase: str) -> None:
    from config_store import update_config

    update_config({"bot_profile": {"activity_type": "listening", "activity_text": phrase}})
    await bot.change_presence(status=make_status(), activity=discord.Activity(type=discord.ActivityType.listening, name=phrase))
    await ctx.reply(f"Le bot écoute maintenant: `{phrase}`.")


@bot.group(name="bot", invoke_without_command=True)
@is_admin()
async def bot_group(ctx: commands.Context) -> None:
    await ctx.reply("Utilise `!bot info`, `!bot apply` ou `!bot presence`.")


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
        await ctx.reply(f"Discord a refuse la modification: `{error}`")
        return
    except (aiohttp.ClientError, ValueError, asyncio.TimeoutError) as error:
        await ctx.reply(f"Impossible de charger l'image: `{error}`")
        return

    await ctx.reply(f"Profil bot applique: {', '.join(changes)}.")


@bot_group.command(name="presence")
@is_admin()
async def bot_presence(ctx: commands.Context) -> None:
    await apply_presence()
    await ctx.reply("Presence du bot mise a jour.")


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
