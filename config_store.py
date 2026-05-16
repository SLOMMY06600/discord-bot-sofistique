# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from pathlib import Path
from threading import Lock
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CONFIG_PATH = DATA_DIR / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "prefix": ".",
    "bot_profile": {
        "name": "Anti-Raid Bot",
        "avatar_url": "",
        "banner_url": "",
        "bio": "Le bouclier de votre serveur Discord.",
        "ping_message": "Mon préfixe est `{prefix}`. Utilise `{prefix}help` pour voir mes commandes.",
        "activity_type": "watching",
        "activity_text": "le serveur",
        "status": "online",
    },
    "anti_raid": {
        "enabled": True,
        "antilink": True,
        "antiinvite": False,
        "antimention": False,
        "antimention_limit": 5,
        "antialt": False,
        "antialt_days": 7,
        "antieveryone": True,
        "antiban": True,
        "antiunban": True,
        "antikick": True,
        "antibot": True,
        "antiwebhook": False,
        "antitoken": False,
        "antispam": False,
        "antithread": False,
        "antiemoji": False,
        "antisticker": False,
        "antiroleperm": False,
        "antiadmin": False,
        "captcha": False,
        "captcha_role_id": None,
        "captcha_channel_id": None,
        "captcha_delete_messages": True,
        "raidmode": False,
        "antiaddrole": True,
        "antidelrole": True,
        "antichannel": True,
        "log_channel_id": None,
    },
    "sanctions": {
        "antilink": "derank",
        "antiinvite": "derank",
        "antimention": "kick",
        "antialt": "ban",
        "antieveryone": "derank",
        "antiban": "ban",
        "antiunban": "ban",
        "antikick": "kick",
        "antibot": "ban",
        "antiwebhook": "derank",
        "antitoken": "ban",
        "antispam": "kick",
        "antithread": "derank",
        "antiemoji": "derank",
        "antisticker": "derank",
        "antiroleperm": "derank",
        "antiadmin": "derank",
        "captcha": "none",
        "raidmode": "none",
        "antiaddrole": "derank",
        "antidelrole": "derank",
        "antichannel": "derank",
    },
    "access": {
        "buyers": [],
        "owners": [],
        "whitelist": [],
        "whitelist_roles": [],
        "blacklist": [],
        "command_permissions": {},
    },
    "server_settings": {
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
    },
    "react_role": {
        "channel_id": None,
        "message_id": None,
        "role_id": None,
        "emoji": "✅",
        "title": "Vérification",
        "description": "Réagis avec {emoji} pour obtenir le rôle et accéder au serveur.",
        "color": "#ff5ec7",
    },
    "tickets": {
        "enabled": True,
        "category_id": None,
        "category_name": "Tickets",
        "support_role_id": None,
        "required_role_ids": [],
        "forbidden_role_ids": [],
        "panel_channel_id": None,
        "channel_name_format": "ticket-{user}",
        "panel_title": "Support",
        "panel_description": "Clique sur le bouton pour ouvrir un ticket.",
        "welcome_message": "Merci d'avoir ouvert un ticket. Explique ton probleme clairement.",
        "embed_color": "#ff5ec7",
        "panel_type": "button",
        "options": [],
        "max_per_user": 1,
        "close_button": True,
        "claim_button": True,
        "claim_lock_channel": False,
        "claim_hide_channel": False,
        "autoclaim": False,
        "auto_delete_closed": True,
        "auto_close_on_leave": True,
        "transcript_dm": False,
    },
    "embed": {
        "title": "Annonce",
        "description": "Ton message ici.",
        "color": "#69d6a2",
        "footer": "Anti-Raid Control",
        "target_channel_id": None,
        "thumbnail": "",
        "image": "",
        "author": "",
        "url": "",
        "timestamp": False,
        "message": "",
        "fields": [],
        "button_label": "",
        "button_url": "",
    },
    "giveaway": {
        "title": "Giveaway",
        "duration_seconds": 3600,
        "reward": "Récompense",
        "participation_message": "Vous avez été enregistré.",
        "color": "#ff5ec7",
        "image_url": "",
        "channel_id": None,
    },
    "shop": {
        "products": {},
        "stock": {},
        "orders": {},
        "reviews": [],
        "blacklist": [],
        "payment": {
            "paypal": "",
            "crypto": "",
        },
        "settings": {
            "autodeliver": False,
            "lowstock": {},
            "color": "#0b1f4d",
        },
    },
    "backups": {},
    "server_generator": {
        "guild_id": "",
        "template": "perso",
        "description": "serveur gtarp avec staff, informations, tickets et annonces",
        "clone_source_guild_id": "",
        "clone_target_guild_id": "",
        "clone_delete_target": True,
        "clone_roles": True,
        "clone_channels": True,
    },
    "dashboard": {
        "site_name": "Anti-Raid Control",
        "owner_name": "MKL",
        "support_url": "",
        "announcement": "Dashboard opérationnel.",
        "theme_color": "#69d6a2",
        "session_timeout_minutes": 360,
    },
}

_LOCK = Lock()


def ensure_config() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)


def deep_merge(default: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(default)
    for key, value in current.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def ids_from_env(*names: str) -> list[str]:
    values: list[str] = []
    for name in names:
        raw = os.getenv(name, "")
        values.extend(re.findall(r"\d{15,25}", raw))
    return values


def merge_unique_ids(current: list[Any], extra: list[str]) -> list[str]:
    merged = [str(item) for item in current if str(item).isdigit()]
    for user_id in extra:
        if user_id not in merged:
            merged.append(user_id)
    return merged


def apply_env_access(config: dict[str, Any]) -> dict[str, Any]:
    access = config.setdefault("access", {})
    access["owners"] = merge_unique_ids(
        access.get("owners", []),
        ids_from_env("OWNER_IDS", "OWNERS", "DISCORD_OWNER_IDS"),
    )
    access["buyers"] = merge_unique_ids(
        access.get("buyers", []),
        ids_from_env("BUYER_IDS", "BUYERS", "DISCORD_BUYER_IDS"),
    )
    access["whitelist"] = merge_unique_ids(
        access.get("whitelist", []),
        ids_from_env("WL_IDS", "WHITELIST_IDS", "DISCORD_WL_IDS"),
    )
    return config


def load_config() -> dict[str, Any]:
    ensure_config()
    with _LOCK:
        with CONFIG_PATH.open("r", encoding="utf-8") as file:
            loaded = json.load(file)
    return apply_env_access(deep_merge(DEFAULT_CONFIG, loaded))


def load_guild_config(guild_id: int | str | None) -> dict[str, Any]:
    config = load_config()
    if guild_id is None:
        return config
    guilds = config.get("guilds", {})
    guild_config = guilds.get(str(guild_id), {})
    base = deep_merge(DEFAULT_CONFIG, {
        "prefix": config.get("prefix", DEFAULT_CONFIG["prefix"]),
        "bot_profile": config.get("bot_profile", {}),
        "access": config.get("access", {}),
        "dashboard": config.get("dashboard", {}),
    })
    merged = deep_merge(base, guild_config)
    merged.pop("guilds", None)
    return apply_env_access(merged)


def save_config(config: dict[str, Any]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with _LOCK:
        with CONFIG_PATH.open("w", encoding="utf-8") as file:
            json.dump(config, file, indent=2, ensure_ascii=True)
            file.write("\n")


def update_config(updates: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    merged = deep_merge(config, updates)
    save_config(merged)
    return merged


def update_guild_config(guild_id: int | str | None, updates: dict[str, Any]) -> dict[str, Any]:
    if guild_id is None:
        return update_config(updates)
    config = load_config()
    guilds = config.setdefault("guilds", {})
    current = guilds.get(str(guild_id), {})
    guilds[str(guild_id)] = deep_merge(current, updates)
    save_config(config)
    return load_guild_config(guild_id)
