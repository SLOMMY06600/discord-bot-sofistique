from __future__ import annotations

import os
import json
import base64
import re
import secrets
import time
import urllib.error
import urllib.request
from datetime import timedelta

from flask import Flask, flash, redirect, render_template, request, session, url_for

from config_store import load_config, update_config
from env_loader import load_env
from env_store import read_env_values, update_env_values


load_env()

app = Flask(__name__)
app.secret_key = os.getenv("DASHBOARD_SECRET", "MKL04")
app.permanent_session_lifetime = timedelta(hours=6)
FAILED_LOGINS: dict[str, list[float]] = {}
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_SECONDS = 300


def require_login() -> bool:
    if not session.get("logged_in"):
        return False
    timeout = int(load_config()["dashboard"].get("session_timeout_minutes", 360))
    logged_at = float(session.get("logged_at", 0))
    if time.time() - logged_at > timeout * 60:
        session.clear()
        return False
    return True


def csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def valid_csrf() -> bool:
    return bool(session.get("csrf_token")) and request.form.get("csrf_token") == session.get("csrf_token")


def client_key() -> str:
    return request.headers.get("X-Forwarded-For", request.remote_addr or "local").split(",")[0].strip()


def login_locked() -> tuple[bool, int]:
    now = time.time()
    key = client_key()
    attempts = [stamp for stamp in FAILED_LOGINS.get(key, []) if now - stamp < LOCKOUT_SECONDS]
    FAILED_LOGINS[key] = attempts
    if len(attempts) >= MAX_LOGIN_ATTEMPTS:
        return True, int(LOCKOUT_SECONDS - (now - attempts[0]))
    return False, 0


def register_failed_login() -> None:
    key = client_key()
    FAILED_LOGINS.setdefault(key, []).append(time.time())


def clear_failed_logins() -> None:
    FAILED_LOGINS.pop(client_key(), None)


def checkbox(name: str) -> bool:
    return request.form.get(name) == "on"


def extract_user_id(value: str) -> str | None:
    match = re.search(r"\d{15,25}", value or "")
    return match.group(0) if match else None


def extract_id_list(value: str) -> list[str]:
    return sorted(set(re.findall(r"\d{15,25}", value or "")))


def parse_ticket_options(value: str) -> list[dict[str, str]]:
    options = []
    for line in (value or "").splitlines():
        raw = line.strip()
        if not raw:
            continue
        parts = [part.strip() for part in raw.split("|")]
        if len(parts) == 1:
            option = {"label": parts[0], "emoji": "", "description": ""}
        elif len(parts) == 2:
            option = {"emoji": parts[0], "label": parts[1], "description": ""}
        else:
            option = {"emoji": parts[0], "label": parts[1], "description": parts[2]}
        if option["label"]:
            options.append(option)
    return options[:25]


def apply_access_form(current: dict) -> dict:
    access = current.get("access", {})
    owners = {str(item) for item in access.get("owners", [])}
    whitelist = {str(item) for item in access.get("whitelist", [])}

    owner_add = extract_user_id(request.form.get("owner_add_id", ""))
    owner_remove = extract_user_id(request.form.get("owner_remove_id", ""))
    whitelist_add = extract_user_id(request.form.get("whitelist_add_id", ""))
    whitelist_remove = extract_user_id(request.form.get("whitelist_remove_id", ""))

    if owner_add:
        owners.add(owner_add)
    if owner_remove:
        owners.discard(owner_remove)
    if whitelist_add:
        whitelist.add(whitelist_add)
    if whitelist_remove:
        whitelist.discard(whitelist_remove)

    return {
        "owners": sorted(owners),
        "whitelist": sorted(whitelist),
    }


def token_status() -> str:
    token = read_env_values().get("DISCORD_TOKEN") or os.getenv("DISCORD_TOKEN", "")
    if not token:
        return "Aucun token configure"
    return f"Token configure (...{token[-4:]})"


def dashboard_stats(config: dict) -> dict:
    anti = config["anti_raid"]
    active_guards = [
        key
        for key in ("antilink", "antieveryone", "antiban", "antiunban", "antikick", "antiaddrole", "antidelrole", "antichannel")
        if anti.get(key)
    ]
    return {
        "prefix": config["prefix"],
        "token": token_status(),
        "guards": f"{len(active_guards)}/8",
        "tickets": "Actif" if config["tickets"].get("enabled") else "Désactivé",
        "logs": config["anti_raid"].get("log_channel_id") or "Non configuré",
    }


def discord_token() -> str:
    return read_env_values().get("DISCORD_TOKEN") or os.getenv("DISCORD_TOKEN", "")


def post_discord_message(channel_id: str, payload: dict) -> tuple[bool, str]:
    token = discord_token()
    if not token:
        return False, "Token Discord manquant dans .env."
    if not channel_id:
        return False, "ID du salon manquant."

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        data=body,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "AntiRaidDashboard/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            if 200 <= response.status < 300:
                return True, "Message envoye."
            return False, f"Discord a repondu avec le code {response.status}."
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        return False, f"Erreur Discord {error.code}: {detail}"
    except urllib.error.URLError as error:
        return False, f"Impossible de contacter Discord: {error.reason}"


def image_url_to_data_uri(url: str) -> tuple[bool, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "AntiRaidDashboard/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            content_type = response.headers.get("content-type", "")
            if not content_type.startswith("image/"):
                return False, "L'URL du logo/banniere ne pointe pas vers une image."
            raw = response.read()
            encoded = base64.b64encode(raw).decode("ascii")
            return True, f"data:{content_type};base64,{encoded}"
    except urllib.error.URLError as error:
        return False, f"Impossible de charger l'image: {error.reason}"


def apply_bot_profile_to_discord(profile: dict) -> tuple[bool, str]:
    token = discord_token()
    if not token:
        return False, "Token Discord manquant dans .env."

    payload: dict[str, str] = {}
    if profile.get("name"):
        payload["username"] = profile["name"]

    if profile.get("avatar_url"):
        ok, value = image_url_to_data_uri(profile["avatar_url"])
        if not ok:
            return False, value
        payload["avatar"] = value

    if profile.get("banner_url"):
        ok, value = image_url_to_data_uri(profile["banner_url"])
        if ok:
            payload["banner"] = value
    if profile.get("bio"):
        payload["bio"] = profile["bio"][:190]

    if not payload:
        return True, "Profil bot conserve."

    ok, message = patch_discord_profile(payload)
    if ok:
        return True, "Nom/logo appliques au bot."

    if "USERNAME_RATE_LIMIT" in message and "username" in payload:
        retry_payload = dict(payload)
        retry_payload.pop("username", None)
        if retry_payload:
            retry_ok, retry_message = patch_discord_profile(retry_payload)
            if retry_ok:
                return True, "Logo/banniere appliques. Nom non modifie: Discord limite les changements de nom trop rapides."
            return False, retry_message
        return False, "Nom non modifie: Discord limite les changements de nom trop rapides."

    if '"bio"' in message and "bio" in payload:
        retry_payload = dict(payload)
        retry_payload.pop("bio", None)
        if retry_payload:
            retry_ok, retry_message = patch_discord_profile(retry_payload)
            if retry_ok:
                return True, "Profil applique. Bio sauvegardee dans le dashboard, mais Discord l'a refusee pour ce bot."
            return False, retry_message
        return True, "Bio sauvegardee dans le dashboard."

    return False, message


def patch_discord_profile(payload: dict) -> tuple[bool, str]:
    token = discord_token()
    req = urllib.request.Request(
        "https://discord.com/api/v10/users/@me",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "AntiRaidDashboard/1.0",
        },
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            if 200 <= response.status < 300:
                return True, "Profil applique."
            return False, f"Discord a repondu avec le code {response.status}."
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        return False, f"Erreur profil Discord {error.code}: {detail}"
    except urllib.error.URLError as error:
        return False, f"Impossible de contacter Discord: {error.reason}"


def ticket_panel_payload(tickets: dict) -> dict:
    color = int((tickets.get("embed_color") or "#69d6a2").removeprefix("#"), 16)
    if tickets.get("panel_type") == "selector":
        options = []
        for option in tickets.get("options", [])[:25]:
            payload_option = {
                "label": option.get("label") or "Ticket",
                "value": option.get("label") or "Ticket",
            }
            if option.get("description"):
                payload_option["description"] = option["description"]
            if option.get("emoji"):
                payload_option["emoji"] = {"name": option["emoji"]}
            options.append(payload_option)
        component = {
            "type": 3,
            "custom_id": "ticket:select",
            "placeholder": "Choisis une option",
            "min_values": 1,
            "max_values": 1,
            "options": options or [{"label": "Contacter le Support", "value": "Contacter le Support"}],
        }
    else:
        component = {
            "type": 2,
            "style": 3,
            "label": "Ouvrir un ticket",
            "custom_id": "ticket:create",
        }
    return {
        "embeds": [
            {
                "title": tickets["panel_title"],
                "description": tickets["panel_description"],
                "color": color,
            }
        ],
        "components": [
            {
                "type": 1,
                "components": [component],
            }
        ],
    }


def embed_payload(embed: dict) -> dict:
    color = int((embed.get("color") or "#69d6a2").removeprefix("#"), 16)
    payload = {
        "embeds": [
            {
                "title": embed["title"],
                "description": embed["description"],
                "color": color,
            }
        ]
    }
    if embed.get("footer"):
        payload["embeds"][0]["footer"] = {"text": embed["footer"]}
    return payload


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if not valid_csrf():
            flash("Session de sécurité expirée, réessaie.", "error")
            return redirect(url_for("login"))
        locked, seconds = login_locked()
        if locked:
            flash(f"Trop de tentatives. Réessaie dans {seconds} secondes.", "error")
            return redirect(url_for("login"))
        if request.form.get("password") == os.getenv("DASHBOARD_SECRET", "MKL04"):
            session.permanent = True
            session["logged_in"] = True
            session["logged_at"] = time.time()
            clear_failed_logins()
            return redirect(url_for("index"))
        register_failed_login()
        flash("Mot de passe incorrect.", "error")
    return render_template("login.html", csrf_token=csrf_token())


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/", methods=["GET", "POST"])
def index():
    if not require_login():
        return redirect(url_for("login"))

    if request.method == "POST":
        if not valid_csrf():
            flash("Session de sécurité expirée, réessaie.", "error")
            return redirect(url_for("index"))
        current_config = load_config()
        action = request.form.get("action", "save")
        token = request.form.get("discord_token", "").strip()
        if token:
            update_env_values({"DISCORD_TOKEN": token})

        bot_profile = {
            "name": request.form["bot_name"],
            "avatar_url": request.form.get("bot_avatar_url", "").strip(),
            "banner_url": request.form.get("bot_banner_url", "").strip(),
            "bio": request.form.get("bot_bio", "").strip(),
            "ping_message": request.form.get("bot_ping_message", "").strip(),
            "activity_type": request.form["bot_activity_type"],
            "activity_text": request.form["bot_activity_text"],
            "status": request.form["bot_status"],
        }
        anti_raid = {
            "enabled": checkbox("enabled"),
            "antilink": checkbox("antilink"),
            "antieveryone": checkbox("antieveryone"),
            "antiban": checkbox("antiban"),
            "antiunban": checkbox("antiunban"),
            "antikick": checkbox("antikick"),
            "antiaddrole": checkbox("antiaddrole"),
            "antidelrole": checkbox("antidelrole"),
            "antichannel": checkbox("antichannel"),
            "log_channel_id": request.form.get("log_channel_id") or None,
        }
        sanctions = {
            "antilink": request.form["sanction_antilink"],
            "antieveryone": request.form["sanction_antieveryone"],
            "antiban": request.form["sanction_antiban"],
            "antiunban": request.form["sanction_antiunban"],
            "antikick": request.form["sanction_antikick"],
            "antiaddrole": request.form["sanction_antiaddrole"],
            "antidelrole": request.form["sanction_antidelrole"],
            "antichannel": request.form["sanction_antichannel"],
        }
        tickets = {
            "enabled": checkbox("tickets_enabled"),
            "category_id": request.form.get("ticket_category_id") or None,
            "category_name": request.form["ticket_category_name"],
            "support_role_id": request.form.get("support_role_id") or None,
            "required_role_ids": extract_id_list(request.form.get("ticket_required_role_ids", "")),
            "forbidden_role_ids": extract_id_list(request.form.get("ticket_forbidden_role_ids", "")),
            "panel_channel_id": request.form.get("ticket_panel_channel_id") or None,
            "channel_name_format": request.form["ticket_channel_name_format"],
            "panel_title": request.form["ticket_panel_title"],
            "panel_description": request.form["ticket_panel_description"],
            "welcome_message": request.form["ticket_welcome_message"],
            "embed_color": request.form["ticket_embed_color"],
            "panel_type": request.form.get("ticket_panel_type", "button"),
            "options": parse_ticket_options(request.form.get("ticket_options", "")),
            "max_per_user": max(1, min(int(request.form.get("ticket_max_per_user", 1)), 25)),
            "close_button": checkbox("ticket_close_button"),
            "claim_button": checkbox("ticket_claim_button"),
            "claim_lock_channel": checkbox("ticket_claim_lock_channel"),
            "claim_hide_channel": checkbox("ticket_claim_hide_channel"),
            "autoclaim": checkbox("ticket_autoclaim"),
            "auto_delete_closed": checkbox("ticket_auto_delete_closed"),
            "auto_close_on_leave": checkbox("ticket_auto_close_on_leave"),
            "transcript_dm": checkbox("ticket_transcript_dm"),
        }
        embed = {
            "title": request.form["embed_title"],
            "description": request.form["embed_description"],
            "color": request.form["embed_color"],
            "footer": request.form["embed_footer"],
            "target_channel_id": request.form.get("embed_target_channel_id") or None,
        }
        dashboard = {
            "site_name": request.form["site_name"],
            "owner_name": request.form["owner_name"],
            "support_url": request.form.get("support_url", "").strip(),
            "announcement": request.form["dashboard_announcement"],
            "theme_color": request.form["dashboard_theme_color"],
            "session_timeout_minutes": int(request.form["session_timeout_minutes"]),
        }
        access = apply_access_form(current_config)
        new_password = request.form.get("dashboard_password", "").strip()
        if new_password:
            if len(new_password) < 5:
                flash("Le nouveau mot de passe doit contenir au moins 5 caractères.", "error")
                return redirect(url_for("index"))
            update_env_values({"DASHBOARD_SECRET": new_password})
            os.environ["DASHBOARD_SECRET"] = new_password
            app.secret_key = new_password
        update_config(
            {
                "prefix": request.form["prefix"],
                "bot_profile": bot_profile,
                "anti_raid": anti_raid,
                "sanctions": sanctions,
                "access": access,
                "tickets": tickets,
                "embed": embed,
                "dashboard": dashboard,
            }
        )
        if action == "send_ticket_panel":
            ok, message = post_discord_message(tickets["panel_channel_id"], ticket_panel_payload(tickets))
            flash(message, "success" if ok else "error")
        elif action == "send_embed":
            ok, message = post_discord_message(embed["target_channel_id"], embed_payload(embed))
            flash(message, "success" if ok else "error")
        else:
            ok, message = apply_bot_profile_to_discord(bot_profile)
            flash(f"Configuration enregistree. {message}", "success" if ok else "error")
        return redirect(url_for("index"))

    config = load_config()
    return render_template(
        "index.html",
        config=config,
        token_status=token_status(),
        csrf_token=csrf_token(),
        stats=dashboard_stats(config),
    )


if __name__ == "__main__":
    host = os.getenv("DASHBOARD_HOST", "127.0.0.1")
    port = int(os.getenv("DASHBOARD_PORT", "5000"))
    app.run(host=host, port=port, debug=os.getenv("FLASK_DEBUG") == "1")
