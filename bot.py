"""HighschoolRP CrowBot — official family applications and private family spaces.

Python 3.11+ / discord.py 2.7.x. No message-content or members intent required.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

BASE = Path(__file__).resolve().parent
TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0") or "0")
DB_PATH = Path(os.getenv("DATABASE_PATH", str(BASE / "data" / "families.sqlite3")))
LOGO = BASE / "assets" / "highschoolrp-logo.png"
BRAND = 0x00DDE8
LOGGER = logging.getLogger("crowbot")

ALLOWED_RESOURCE_COLUMNS = {
    "member_role_id", "leader_role_id", "category_id", "announcement_channel_id",
    "chat_channel_id", "media_channel_id", "voice_channel_id",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=15)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        db.execute("PRAGMA foreign_keys=ON")
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize_database() -> None:
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS settings (
                guild_id INTEGER PRIMARY KEY,
                applications_channel_id INTEGER NOT NULL,
                reviews_channel_id INTEGER NOT NULL,
                head_role_id INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                owner_id INTEGER NOT NULL,
                family_name TEXT NOT NULL,
                declared_members INTEGER NOT NULL,
                server_group TEXT NOT NULL,
                age_group TEXT NOT NULL,
                color_hex TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                review_message_id INTEGER,
                member_role_id INTEGER,
                leader_role_id INTEGER,
                category_id INTEGER,
                announcement_channel_id INTEGER,
                chat_channel_id INTEGER,
                media_channel_id INTEGER,
                voice_channel_id INTEGER,
                decided_by INTEGER,
                decided_at TEXT,
                decline_reason TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_family_status ON applications (guild_id, status);
            CREATE INDEX IF NOT EXISTS ix_family_owner ON applications (guild_id, owner_id, status);
            CREATE TABLE IF NOT EXISTS whitelist_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                review_message_id INTEGER,
                reviewed_by INTEGER,
                reviewed_at TEXT,
                reason TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_whitelist_guild ON whitelist_requests (guild_id, status);
            CREATE UNIQUE INDEX IF NOT EXISTS ux_whitelist_active
                ON whitelist_requests(guild_id, user_id) WHERE status IN ('pending','approved');
            CREATE TABLE IF NOT EXISTS family_warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL REFERENCES applications(id),
                number INTEGER NOT NULL,
                reason TEXT NOT NULL,
                issued_by INTEGER NOT NULL,
                issued_at TEXT NOT NULL,
                revoked_by INTEGER,
                revoked_at TEXT,
                revoke_reason TEXT,
                UNIQUE(application_id, number)
            );
            CREATE TABLE IF NOT EXISTS blacklist_pages (
                guild_id INTEGER NOT NULL,
                page_index INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                PRIMARY KEY (guild_id, page_index)
            );
        """)
        # In-place migrations: keep the real live families.sqlite3, all approvals, and roles.
        for table, columns in {
            "settings": {
                "official_channel_id": "INTEGER",
                "blacklist_channel_id": "INTEGER",
            },
            "applications": {
                "official_message_id": "INTEGER",
                "moderation_action": "TEXT",
                "moderation_reason": "TEXT",
                "moderation_by": "INTEGER",
                "moderation_at": "TEXT",
            },
        }.items():
            existing = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            for name, definition in columns.items():
                if name not in existing:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def get_setting(guild_id: int) -> sqlite3.Row | None:
    with connect() as db:
        return db.execute("SELECT * FROM settings WHERE guild_id=?", (guild_id,)).fetchone()


def save_setting(guild_id: int, apps: int, reviews: int, head: int) -> None:
    with connect() as db:
        db.execute("""
            INSERT INTO settings (guild_id, applications_channel_id, reviews_channel_id,
                                  head_role_id, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                applications_channel_id=excluded.applications_channel_id,
                reviews_channel_id=excluded.reviews_channel_id,
                head_role_id=excluded.head_role_id, updated_at=excluded.updated_at
        """, (guild_id, apps, reviews, head, now()))


def save_board_channels(guild_id: int, official_id: int, blacklist_id: int) -> bool:
    with connect() as db:
        result = db.execute("""UPDATE settings SET official_channel_id=?, blacklist_channel_id=?,
                             updated_at=? WHERE guild_id=?""",
                            (official_id, blacklist_id, now(), guild_id))
        return result.rowcount == 1


def save_official_message(application_id: int, message_id: int | None) -> None:
    with connect() as db:
        db.execute("UPDATE applications SET official_message_id=? WHERE id=?",
                   (message_id, application_id))


def get_approved_families(guild_id: int) -> list[sqlite3.Row]:
    with connect() as db:
        return db.execute("""SELECT * FROM applications WHERE guild_id=? AND status='approved'
                             ORDER BY family_name COLLATE NOCASE, id""", (guild_id,)).fetchall()


def get_blacklisted_families(guild_id: int) -> list[sqlite3.Row]:
    with connect() as db:
        return db.execute("""SELECT * FROM applications WHERE guild_id=? AND status='blacklisted'
                             ORDER BY moderation_at DESC, id DESC""", (guild_id,)).fetchall()


def get_warnings(application_id: int, active_only: bool = False) -> list[sqlite3.Row]:
    with connect() as db:
        return db.execute("""SELECT * FROM family_warnings WHERE application_id=?"""
                          + (" AND revoked_at IS NULL" if active_only else "")
                          + " ORDER BY number", (application_id,)).fetchall()


def add_warning(guild_id: int, application_id: int, moderator_id: int, reason: str) -> int | None:
    with connect() as db:
        app = db.execute("SELECT status FROM applications WHERE id=? AND guild_id=?",
                         (application_id, guild_id)).fetchone()
        if not app or app["status"] != "approved":
            return None
        number = db.execute("SELECT COALESCE(MAX(number),0)+1 FROM family_warnings WHERE application_id=?",
                            (application_id,)).fetchone()[0]
        db.execute("""INSERT INTO family_warnings (application_id,number,reason,issued_by,issued_at)
                      VALUES (?,?,?,?,?)""", (application_id, number, reason, moderator_id, now()))
        return number


def revoke_warning(guild_id: int, application_id: int, number: int, moderator_id: int,
                   reason: str = '') -> bool:
    with connect() as db:
        result = db.execute("""UPDATE family_warnings SET revoked_by=?,revoked_at=?,revoke_reason=?
            WHERE application_id=? AND number=? AND revoked_at IS NULL
              AND EXISTS (SELECT 1 FROM applications WHERE id=? AND guild_id=? AND status='approved')""",
            (moderator_id, now(), reason, application_id, number, application_id, guild_id))
        return result.rowcount == 1


def create_whitelist_request(guild_id: int, user_id: int) -> tuple[int | None, str]:
    with connect() as db:
        existing = db.execute("""SELECT status FROM whitelist_requests WHERE guild_id=? AND user_id=?
                                 AND status IN ('pending','approved')""", (guild_id, user_id)).fetchone()
        if existing:
            return None, f"You already have an {existing['status']} whitelist request."
        cur = db.execute("""INSERT INTO whitelist_requests (guild_id,user_id,created_at)
                            VALUES (?,?,?)""", (guild_id, user_id, now()))
        return cur.lastrowid, "Whitelist request submitted."


def get_whitelist_request(request_id: int) -> sqlite3.Row | None:
    with connect() as db:
        return db.execute("SELECT * FROM whitelist_requests WHERE id=?", (request_id,)).fetchone()


def get_pending_whitelist_views() -> list[sqlite3.Row]:
    with connect() as db:
        return db.execute("""SELECT id, review_message_id FROM whitelist_requests
                             WHERE status='pending' AND review_message_id IS NOT NULL""").fetchall()


def set_whitelist_message(request_id: int, message_id: int | None) -> None:
    with connect() as db:
        db.execute("UPDATE whitelist_requests SET review_message_id=? WHERE id=?",
                   (message_id, request_id))


def decide_whitelist(guild_id: int, request_id: int, moderator_id: int,
                     approve: bool, reason: str) -> bool:
    with connect() as db:
        result = db.execute("""UPDATE whitelist_requests
           SET status=?, reviewed_by=?, reviewed_at=?, reason=?
           WHERE id=? AND guild_id=? AND status='pending'""",
           ('approved' if approve else 'declined', moderator_id, now(), reason or None, request_id, guild_id))
        return result.rowcount == 1


def is_whitelisted(guild_id: int, user_id: int) -> bool:
    with connect() as db:
        return db.execute("""SELECT 1 FROM whitelist_requests WHERE guild_id=? AND user_id=?
                            AND status='approved' LIMIT 1""", (guild_id, user_id)).fetchone() is not None


def revoke_whitelist(guild_id: int, user_id: int, moderator_id: int) -> bool:
    with connect() as db:
        result = db.execute("""UPDATE whitelist_requests SET status='revoked',
           reviewed_by=?, reviewed_at=? WHERE guild_id=? AND user_id=? AND status='approved'""",
           (moderator_id, now(), guild_id, user_id))
        return result.rowcount == 1


def start_family_removal(guild_id: int, application_id: int, action: str,
                         moderator_id: int, reason: str) -> bool:
    if action not in ('removed', 'blacklisted'):
        raise ValueError('Invalid family moderation action')
    with connect() as db:
        result = db.execute("""UPDATE applications SET status='removing', moderation_action=?,
              moderation_reason=?, moderation_by=?, moderation_at=?
              WHERE id=? AND guild_id=? AND status='approved'""",
              (action, reason, moderator_id, now(), application_id, guild_id))
        return result.rowcount == 1


def finish_family_removal(guild_id: int, application_id: int) -> bool:
    with connect() as db:
        result = db.execute("""UPDATE applications SET status=moderation_action,
             official_message_id=NULL, member_role_id=NULL, leader_role_id=NULL,
             category_id=NULL, announcement_channel_id=NULL, chat_channel_id=NULL,
             media_channel_id=NULL, voice_channel_id=NULL
             WHERE id=? AND guild_id=? AND status='removing'
               AND moderation_action IN ('removed','blacklisted')""", (application_id, guild_id))
        return result.rowcount == 1


def unblacklist_family(guild_id: int, application_id: int, moderator_id: int, reason: str) -> bool:
    with connect() as db:
        result = db.execute("""UPDATE applications SET status='removed', moderation_action='unblacklisted',
            moderation_by=?, moderation_reason=?, moderation_at=?
            WHERE id=? AND guild_id=? AND status='blacklisted'""",
            (moderator_id, reason, now(), application_id, guild_id))
        return result.rowcount == 1


def get_application(application_id: int) -> sqlite3.Row | None:
    with connect() as db:
        return db.execute("SELECT * FROM applications WHERE id=?", (application_id,)).fetchone()


def get_pending_views() -> list[sqlite3.Row]:
    with connect() as db:
        return db.execute("""
            SELECT id, review_message_id FROM applications
            WHERE status IN ('pending','processing') AND review_message_id IS NOT NULL
        """).fetchall()


def get_incomplete() -> list[sqlite3.Row]:
    with connect() as db:
        return db.execute("SELECT * FROM applications WHERE status='processing'").fetchall()


def get_official_for_leader(guild_id: int, user_id: int) -> sqlite3.Row | None:
    with connect() as db:
        return db.execute("""
            SELECT * FROM applications WHERE guild_id=? AND owner_id=?
             AND status='approved' ORDER BY id DESC LIMIT 1
        """, (guild_id, user_id)).fetchone()


def create_application(guild_id: int, owner_id: int, family_name: str,
                       declared_members: int, server_group: str, age_group: str,
                       color_hex: str) -> tuple[int | None, str]:
    with connect() as db:
        current = db.execute("""
            SELECT id, status FROM applications WHERE guild_id=? AND owner_id=?
              AND status IN ('pending','processing','approved','removing','blacklisted') LIMIT 1
        """, (guild_id, owner_id)).fetchone()
        if current:
            return None, f"You already have an {current['status']} family application (#{current['id']})."
        duplicate = db.execute("""
            SELECT id FROM applications WHERE guild_id=? AND family_name=? COLLATE NOCASE
              AND status IN ('pending','processing','approved','removing','blacklisted') LIMIT 1
        """, (guild_id, family_name)).fetchone()
        if duplicate:
            return None, "That family name is already reserved by another application."
        cur = db.execute("""
            INSERT INTO applications (guild_id, owner_id, family_name, declared_members,
                                      server_group, age_group, color_hex, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (guild_id, owner_id, family_name, declared_members, server_group,
              age_group, color_hex, now()))
        return cur.lastrowid, "Application submitted."


def set_review_message(application_id: int, message_id: int | None) -> None:
    with connect() as db:
        db.execute("UPDATE applications SET review_message_id=? WHERE id=?",
                   (message_id, application_id))


def claim(application_id: int, guild_id: int) -> bool:
    with connect() as db:
        cursor = db.execute("""
            UPDATE applications SET status='processing'
            WHERE id=? AND guild_id=? AND status='pending'
        """, (application_id, guild_id))
        return cursor.rowcount == 1


def save_resource(application_id: int, column: str, value: int) -> None:
    if column not in ALLOWED_RESOURCE_COLUMNS:
        raise ValueError("Invalid resource field")
    with connect() as db:
        db.execute(f"UPDATE applications SET {column}=? WHERE id=?", (value, application_id))


def finish_approval(application_id: int, moderator_id: int) -> None:
    with connect() as db:
        db.execute("""
            UPDATE applications SET status='approved', decided_by=?, decided_at=?
            WHERE id=? AND status='processing'
        """, (moderator_id, now(), application_id))


def restore_pending(application_id: int) -> None:
    with connect() as db:
        db.execute("""
            UPDATE applications SET status='pending', member_role_id=NULL,
            leader_role_id=NULL, category_id=NULL, announcement_channel_id=NULL,
            chat_channel_id=NULL, media_channel_id=NULL, voice_channel_id=NULL
            WHERE id=? AND status='processing'
        """, (application_id,))


def decline(application_id: int, guild_id: int, moderator_id: int, reason: str) -> bool:
    with connect() as db:
        result = db.execute("""
            UPDATE applications SET status='declined', decided_by=?, decided_at=?,
                   decline_reason=? WHERE id=? AND guild_id=? AND status='pending'
        """, (moderator_id, now(), reason or None, application_id, guild_id))
        return result.rowcount == 1


def sanitize_name(raw: str) -> str | None:
    clean = " ".join(raw.split())
    # Latin/Unicode letters, numbers, spaces and common punctuation only.
    if 2 <= len(clean) <= 32 and re.fullmatch(r"[\w][\w .'-]*", clean, re.UNICODE):
        return clean
    return None


def sanitize_server(raw: str) -> str | None:
    clean = " ".join(raw.split())
    if 2 <= len(clean) <= 40 and re.fullmatch(r"[\w][\w .'-]*", clean, re.UNICODE):
        return clean
    return None


def parse_color(raw: str) -> str | None:
    candidate = raw.strip().lstrip("#").upper()
    return f"#{candidate}" if re.fullmatch(r"[A-F0-9]{6}", candidate) else None


def safe(text: str) -> str:
    return discord.utils.escape_mentions(discord.utils.escape_markdown(str(text)))


def logo_file() -> discord.File:
    return discord.File(str(LOGO), filename="hsrp-logo.png")


def make_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="HIGH SCHOOL RP  |  OFFICIAL FAMILIES",
        description=(
            "Build your family and become an **Official HighschoolRP Family**.\n\n"
            "Use the button below to submit your application. Our **Head of Families** "
            "will review it before anything is created.\n\n"
            "**Required information**\n"
            "• Family name and current member count\n"
            "• Server / community (e.g. North America, Spanish)\n"
            "• Family age group: **13+** or **18+**\n"
            "• Role color (HEX, e.g. `#00FFFF`)\n\n"
            "**After approval**\n"
            "• `Leader [Family Name]` and `Member of [Family Name]` roles\n"
            "• Private announcements, chat, media and voice channels\n"
            "• The family leader can add or remove family members\n\n"
            "*Only one active family application is permitted per applicant.*"
        ),
        color=BRAND,
    )
    embed.set_thumbnail(url="attachment://hsrp-logo.png")
    embed.set_footer(text="HighschoolRP • Family Management")
    return embed


def review_embed(app: sqlite3.Row) -> discord.Embed:
    state = str(app["status"]).upper()
    embed = discord.Embed(
        title=f"Family Application #{app['id']}",
        description=f"**{safe(app['family_name'])}** | {state}",
        color=BRAND if state == "PENDING" else (0x32B77A if state == "APPROVED" else 0xE05656),
        timestamp=datetime.fromisoformat(app["created_at"]),
    )
    embed.add_field(name="Applicant / Leader", value=f"<@{app['owner_id']}>", inline=True)
    embed.add_field(name="Declared members", value=str(app["declared_members"]), inline=True)
    embed.add_field(name="Server / community", value=safe(app["server_group"]), inline=True)
    embed.add_field(name="Age group", value=app["age_group"], inline=True)
    embed.add_field(name="Role color", value=f"`{app['color_hex']}`", inline=True)
    embed.add_field(name="Application ID", value=f"`{app['id']}`", inline=True)
    if app["decided_by"]:
        embed.add_field(name="Reviewed by", value=f"<@{app['decided_by']}>", inline=False)
    if app["decline_reason"]:
        embed.add_field(name="Reason", value=safe(app["decline_reason"]), inline=False)
    embed.set_thumbnail(url="attachment://hsrp-logo.png")
    embed.set_footer(text="HighschoolRP • Head of Families Review")
    return embed


def official_embed(app: sqlite3.Row) -> discord.Embed:
    warn_count = len(get_warnings(app["id"], active_only=True))
    color = discord.Color(int(app["color_hex"][1:], 16))
    embed = discord.Embed(
        title=f"🏫 OFFICIAL FAMILY | {safe(app['family_name'])}",
        description="**Officially approved by HighschoolRP Family Management.**\n"
                    "Welcome to our official family directory!",
        color=color,
    )
    embed.add_field(name="👑 Family Leader", value=f"<@{app['owner_id']}>", inline=True)
    embed.add_field(name="👥 Members at Application", value=str(app["declared_members"]), inline=True)
    embed.add_field(name="🌐 Community", value=safe(app["server_group"]), inline=True)
    embed.add_field(name="🔞 Age Group", value=app["age_group"], inline=True)
    embed.add_field(name="🎨 Family Color", value=f"`{app['color_hex']}`", inline=True)
    embed.add_field(name="⚠️ Active Warnings", value=f"**{warn_count}**", inline=True)
    if app["chat_channel_id"]:
        embed.add_field(name="🔒 Private Family Space", value=f"<#{app['chat_channel_id']}>", inline=False)
    embed.set_thumbnail(url="attachment://hsrp-logo.png")
    embed.set_footer(text=f"HighschoolRP • Official Families • Family #{app['id']}")
    return embed


def whitelist_review_embed(request: sqlite3.Row) -> discord.Embed:
    embed = discord.Embed(
        title=f"🛡️ Family Management Whitelist • #{request['id']}",
        description=(f"**Applicant:** <@{request['user_id']}>\n"
                     f"**Status:** {request['status'].upper()}\n\n"
                     "If approved, this person may **remove official families**. "
                     "Approval does not grant Discord Administrator permissions."),
        color=0xFF77B7 if request["status"] == "pending" else BRAND,
    )
    if request["reason"]:
        embed.add_field(name="Review Reason", value=safe(request["reason"]), inline=False)
    embed.set_footer(text="HighschoolRP • Head of Families only")
    return embed


def blacklist_embeds(guild_id: int) -> list[discord.Embed]:
    families = get_blacklisted_families(guild_id)
    chunks = [families[i:i + 8] for i in range(0, len(families), 8)] or [[]]
    results = []
    for idx, chunk in enumerate(chunks):
        embed = discord.Embed(
            title="🚫 HIGHSCHOOLRP | BLACKLISTED FAMILIES",
            description="Families listed here are **not permitted to apply again** under "
                        "the same leader or family name until a Head of Families lifts the blacklist."
                        if idx == 0 else "Continuation of the official blacklist.",
            color=0xDC3D6E,
        )
        if not chunk:
            embed.add_field(name="Current Blacklist", value="No blacklisted families.", inline=False)
        for app in chunk:
            embed.add_field(
                name=f"🚫 {safe(app['family_name'])}  •  #{app['id']}",
                value=(f"**Former Leader:** <@{app['owner_id']}>\n"
                       f"**Reason:** {safe((app['moderation_reason'] or 'Not provided')[:450])}\n"
                       f"**Blacklisted:** {app['moderation_at'][:10] if app['moderation_at'] else 'Unknown'}"),
                inline=False,
            )
        embed.set_thumbnail(url="attachment://hsrp-logo.png")
        embed.set_footer(text=f"HighschoolRP • Family Blacklist • Page {idx+1}/{len(chunks)}")
        results.append(embed)
    return results


def is_head(member: discord.Member, setting: sqlite3.Row | None) -> bool:
    if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
        return True
    return bool(setting and any(role.id == setting["head_role_id"] for role in member.roles))


def is_admin(member: discord.Member) -> bool:
    return member.guild_permissions.administrator or member.guild_permissions.manage_guild


async def fetch_member(guild: discord.Guild, member_id: int) -> discord.Member:
    return guild.get_member(member_id) or await guild.fetch_member(member_id)


async def send_private(user: discord.abc.User, embed: discord.Embed) -> None:
    try:
        await user.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        pass


async def find_text_channel(guild: discord.Guild, channel_id: int) -> discord.TextChannel | None:
    channel = guild.get_channel(channel_id)
    if channel is None:
        try:
            channel = await guild.fetch_channel(channel_id)
        except (discord.HTTPException, discord.NotFound):
            return None
    return channel if isinstance(channel, discord.TextChannel) else None


async def publish_official_family(guild: discord.Guild, app: sqlite3.Row) -> bool:
    setting = get_setting(guild.id)
    if not setting or not setting["official_channel_id"] or app["status"] != "approved":
        return False
    channel = await find_text_channel(guild, setting["official_channel_id"])
    if not channel:
        LOGGER.warning("Official families channel unavailable for guild %s", guild.id)
        return False
    try:
        if app["official_message_id"]:
            try:
                old = await channel.fetch_message(app["official_message_id"])
                await old.edit(embed=official_embed(app), allowed_mentions=discord.AllowedMentions.none())
                return True
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                # Re-post if a moderator deleted the original card or moved channels.
                pass
        message = await channel.send(embed=official_embed(app), file=logo_file(),
                                     allowed_mentions=discord.AllowedMentions.none())
        save_official_message(app["id"], message.id)
        return True
    except (discord.Forbidden, discord.HTTPException) as exc:
        LOGGER.warning("Could not publish official family #%s: %s", app["id"], exc)
        return False


async def remove_official_family_message(guild: discord.Guild, app: sqlite3.Row) -> bool:
    if not app["official_message_id"]:
        return True
    setting = get_setting(guild.id)
    channel = (await find_text_channel(guild, setting["official_channel_id"])
               if setting and setting["official_channel_id"] else None)
    if not channel:
        LOGGER.warning("Cannot find official-family channel for #%s", app["id"])
        return False
    try:
        msg = await channel.fetch_message(app["official_message_id"])
        await msg.delete()
    except discord.NotFound:
        pass
    except (discord.Forbidden, discord.HTTPException) as exc:
        LOGGER.warning("Cannot delete official-family card for #%s: %s", app["id"], exc)
        return False
    save_official_message(app["id"], None)
    return True


async def refresh_blacklist_board(guild: discord.Guild) -> bool:
    setting = get_setting(guild.id)
    if not setting or not setting["blacklist_channel_id"]:
        return False
    channel = await find_text_channel(guild, setting["blacklist_channel_id"])
    if not channel:
        return False
    embeds = blacklist_embeds(guild.id)
    with connect() as db:
        existing = {row["page_index"]: row for row in db.execute(
            "SELECT * FROM blacklist_pages WHERE guild_id=?", (guild.id,)).fetchall()}
    all_ok = True
    for index, embed in enumerate(embeds):
        prior = existing.get(index)
        updated = False
        if prior and prior["channel_id"] == channel.id:
            try:
                msg = await channel.fetch_message(prior["message_id"])
                await msg.edit(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                updated = True
            except discord.NotFound:
                pass
            except (discord.Forbidden, discord.HTTPException):
                LOGGER.exception("Cannot update blacklist board page %s", index)
                all_ok = False
                continue
        if not updated:
            try:
                msg = await channel.send(embed=embed, file=logo_file(),
                                         allowed_mentions=discord.AllowedMentions.none())
            except (discord.Forbidden, discord.HTTPException):
                LOGGER.exception("Cannot publish blacklist board page %s", index)
                all_ok = False
                continue
            with connect() as db:
                db.execute("""INSERT INTO blacklist_pages(guild_id,page_index,channel_id,message_id)
                     VALUES(?,?,?,?) ON CONFLICT(guild_id,page_index) DO UPDATE SET
                     channel_id=excluded.channel_id, message_id=excluded.message_id""",
                     (guild.id, index, channel.id, msg.id))
    # Delete obsolete pages and previously configured channel's old board messages.
    for index, prior in existing.items():
        if index < len(embeds) and prior["channel_id"] == channel.id:
            continue
        old_channel = await find_text_channel(guild, prior["channel_id"])
        if old_channel:
            try:
                await (await old_channel.fetch_message(prior["message_id"])).delete()
            except discord.NotFound:
                pass
            except (discord.Forbidden, discord.HTTPException):
                LOGGER.warning("Could not clean old blacklist page %s", index)
                all_ok = False
        with connect() as db:
            # Delete only the OLD row; a moved board has already upserted a new message.
            db.execute("""DELETE FROM blacklist_pages WHERE guild_id=? AND page_index=?
                       AND channel_id=? AND message_id=?""",
                       (guild.id, index, prior['channel_id'], prior['message_id']))
    return all_ok


async def publish_whitelist_review(guild: discord.Guild, req: sqlite3.Row) -> bool:
    setting = get_setting(guild.id)
    if not setting:
        return False
    channel = await find_text_channel(guild, setting["reviews_channel_id"])
    if not channel:
        return False
    try:
        msg = await channel.send(embed=whitelist_review_embed(req),
                                 view=WhitelistReviewView(req["id"]),
                                 allowed_mentions=discord.AllowedMentions.none())
        set_whitelist_message(req["id"], msg.id)
        return True
    except (discord.Forbidden, discord.HTTPException):
        LOGGER.exception("Could not publish whitelist request #%s", req["id"])
        return False


async def update_whitelist_review(guild: discord.Guild, req: sqlite3.Row) -> None:
    setting = get_setting(guild.id)
    if not setting or not req["review_message_id"]:
        return
    channel = await find_text_channel(guild, setting["reviews_channel_id"])
    if not channel:
        return
    try:
        msg = await channel.fetch_message(req["review_message_id"])
        await msg.edit(embed=whitelist_review_embed(req), view=None)
    except (discord.Forbidden, discord.HTTPException):
        LOGGER.warning("Could not update whitelist review #%s", req["id"])


async def decide_whitelist_request(guild: discord.Guild, request_id: int,
                                   moderator: discord.Member, approve: bool,
                                   reason: str) -> tuple[bool,str]:
    req = get_whitelist_request(request_id)
    if not req or req["guild_id"] != guild.id:
        return False, "Whitelist request not found."
    if not decide_whitelist(guild.id, request_id, moderator.id, approve, reason):
        return False, "Whitelist request was already reviewed."
    updated = get_whitelist_request(request_id)
    await update_whitelist_review(guild, updated)
    try:
        user = await fetch_member(guild, req["user_id"])
    except discord.HTTPException:
        user = None
    if user:
        await send_private(user, discord.Embed(
            title="Family Management Whitelist • " + ("Approved" if approve else "Declined"),
            description=("You can now use `/family-remove` on approved families."
                         if approve else "Your whitelist request was declined.")
                        + (f"\n**Reason:** {safe(reason)}" if reason else ""),
            color=0x32B77A if approve else 0xE05656,
        ))
    return True, (f"Whitelist {'approved' if approve else 'declined'} for <@{req['user_id']}>.")


async def remove_family(guild: discord.Guild, application_id: int, moderator: discord.Member,
                        action: str, reason: str, retry: bool = False) -> tuple[bool, str]:
    app = get_application(application_id)
    if not app or app["guild_id"] != guild.id:
        return False, "Family application not found in this server."
    if retry:
        if app["status"] != "removing" or app["moderation_action"] != action:
            return False, "No interrupted removal with that action exists."
    elif not start_family_removal(guild.id, application_id, action, moderator.id, reason):
        return False, "Only an approved family can be removed or blacklisted."
    app = get_application(application_id)
    cleaned = await cleanup_resources(
        guild, app, audit_reason=f"HighschoolRP family #{application_id} {action} by {moderator.id}: {reason[:120]}",
    )
    if not cleaned:
        return False, ("Some family roles or channels could not be deleted. Family is locked "
                       "in REMOVING status. Fix bot permissions, then use "
                       f"`/family-remove-retry application_id:{application_id}`.")
    if not await remove_official_family_message(guild, app):
        return False, ("Private resources were deleted, but the official announcement could not "
                       "be removed. Fix channel permissions and use "
                       f"`/family-remove-retry application_id:{application_id}`.")
    finish_family_removal(guild.id, application_id)
    board_ok = True
    if action == 'blacklisted':
        board_ok = await refresh_blacklist_board(guild)
    await send_private_if_possible(guild, app["owner_id"], discord.Embed(
        title="HighschoolRP Family " + ("Blacklisted" if action == 'blacklisted' else "Removed"),
        description=(f"**{safe(app['family_name'])}** was {action} by Family Management.\n"
                     f"**Reason:** {safe(reason or app['moderation_reason'] or 'Not provided')}"),
        color=0xD9445B,
    ))
    return True, (f"**{safe(app['family_name'])}** was {action}. Its private channels, "
                  "roles and official announcement were removed."
                  + (" ⚠️ The blacklist channel could not be updated; run `/family-sync-boards` "
                     "after checking `/family-channels`." if not board_ok else ""))


async def send_private_if_possible(guild: discord.Guild, member_id: int, embed: discord.Embed) -> None:
    try:
        member = await fetch_member(guild, member_id)
        await send_private(member, embed)
    except discord.HTTPException:
        pass


async def post_review(guild: discord.Guild, app: sqlite3.Row) -> bool:
    setting = get_setting(guild.id)
    if setting is None:
        return False
    channel = await find_text_channel(guild, setting["reviews_channel_id"])
    if channel is None:
        return False
    if app["review_message_id"]:
        return True
    try:
        message = await channel.send(
            embed=review_embed(app),
            file=logo_file(),
            view=ReviewView(app["id"]),
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except (discord.Forbidden, discord.HTTPException) as exc:
        LOGGER.warning("Could not publish application %s for review: %s", app["id"], exc)
        return False
    set_review_message(app["id"], message.id)
    return True


async def update_review_message(guild: discord.Guild, app: sqlite3.Row) -> None:
    if not app["review_message_id"]:
        return
    setting = get_setting(guild.id)
    if setting is None:
        return
    channel = await find_text_channel(guild, setting["reviews_channel_id"])
    if channel is None:
        return
    try:
        message = await channel.fetch_message(app["review_message_id"])
        await message.edit(embed=review_embed(app), view=None,
                           allowed_mentions=discord.AllowedMentions.none())
    except (discord.HTTPException, discord.NotFound, discord.Forbidden):
        LOGGER.warning("Cannot update review message for application %s", app["id"])


async def cleanup_resources(guild: discord.Guild, app: sqlite3.Row,
                            audit_reason: str | None = None) -> bool:
    # Deletes only resources recorded under THIS application, in reverse creation order.
    audit_reason = audit_reason or f"Failed family provision #{app['id']}"
    success = True
    for key in ("voice_channel_id", "media_channel_id", "chat_channel_id",
                "announcement_channel_id", "category_id"):
        resource_id = app[key]
        if not resource_id:
            continue
        channel = guild.get_channel(resource_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(resource_id)
            except discord.NotFound:
                continue
            except (discord.Forbidden, discord.HTTPException):
                LOGGER.exception("Unable to inspect recorded channel %s during cleanup", resource_id)
                success = False
                continue
        try:
            await channel.delete(reason=audit_reason)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            LOGGER.exception("Failed to delete partially created channel %s", resource_id)
            success = False
    for key in ("leader_role_id", "member_role_id"):
        role = guild.get_role(app[key]) if app[key] else None
        if role:
            try:
                await role.delete(reason=audit_reason)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                LOGGER.exception("Failed to delete partially created role %s", app[key])
                success = False
    return success


async def approve_application(guild: discord.Guild, application_id: int,
                              moderator: discord.Member) -> tuple[bool, str]:
    app = get_application(application_id)
    if not app or app["guild_id"] != guild.id:
        return False, "That application does not exist in this server."
    if not claim(application_id, guild.id):
        return False, "This application is no longer pending or is already being reviewed."

    created_role_member = None
    created_role_leader = None
    announcement = None
    try:
        me = await fetch_member(guild, guild.me.id if guild.me else bot.user.id)
        if not (me.guild_permissions.manage_roles and me.guild_permissions.manage_channels):
            raise RuntimeError("The bot needs Manage Roles and Manage Channels permissions.")
        founder = await fetch_member(guild, app["owner_id"])
        color = discord.Color(int(app["color_hex"][1:], 16))
        name = app["family_name"]
        # Members and leaders are both hoisted, creating distinct member-list groups.
        created_role_member = await guild.create_role(
            name=f"Member of {name}", color=color, hoist=True,
            mentionable=False, reason=f"Official family #{application_id} approved by {moderator}",
        )
        save_resource(application_id, "member_role_id", created_role_member.id)
        created_role_leader = await guild.create_role(
            name=f"Leader {name}", color=color, hoist=True,
            mentionable=False, reason=f"Official family #{application_id} approved by {moderator}",
        )
        save_resource(application_id, "leader_role_id", created_role_leader.id)

        setting = get_setting(guild.id)
        if setting is None:
            raise RuntimeError("Run /family-setup before approving applications.")
        head_role = guild.get_role(setting["head_role_id"])
        if head_role is None:
            raise RuntimeError("Head of Families role is missing. Reconfigure /family-setup.")

        view_perms = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True,
            connect=True, speak=True,
        )
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            created_role_member: view_perms,
            created_role_leader: view_perms,
            head_role: view_perms,
            me: view_perms,
        }
        category = await guild.create_category(
            name=f"FAMILY | {name}", overwrites=overwrites,
            reason=f"Private category for approved family #{application_id}",
        )
        save_resource(application_id, "category_id", category.id)

        announcement = await guild.create_text_channel(
            name="announcements", category=category,
            topic=f"Official announcements for {name}",
            reason=f"Official family #{application_id}",
        )
        save_resource(application_id, "announcement_channel_id", announcement.id)
        # Members can read announcements but only leaders / Heads can write them.
        await announcement.set_permissions(
            created_role_member, view_channel=True, send_messages=False,
            read_message_history=True, add_reactions=False,
            reason="Family announcements are read-only for members",
        )
        chat = await guild.create_text_channel(
            name="chat", category=category, topic=f"Private chat for {name}",
            reason=f"Official family #{application_id}",
        )
        save_resource(application_id, "chat_channel_id", chat.id)
        media = await guild.create_text_channel(
            name="media", category=category, topic=f"Images and videos for {name}",
            reason=f"Official family #{application_id}",
        )
        save_resource(application_id, "media_channel_id", media.id)
        voice = await guild.create_voice_channel(
            name="Family Voice", category=category,
            reason=f"Official family #{application_id}",
        )
        save_resource(application_id, "voice_channel_id", voice.id)
        await founder.add_roles(created_role_leader,
                                reason=f"Official family #{application_id} leader")
        finish_approval(application_id, moderator.id)
    except (discord.HTTPException, RuntimeError, sqlite3.Error) as exc:
        LOGGER.exception("Failed to provision family #%s", application_id)
        latest = get_application(application_id)
        cleaned = await cleanup_resources(guild, latest) if latest else False
        if cleaned:
            restore_pending(application_id)
            return False, f"Could not create the family: {str(exc)[:170]}. Check permissions and try again."
        return False, ("Provisioning failed and some resources could not be cleaned up. "
                       f"Ask a Head of Families to use `/family-recover application_id:{application_id}` "
                       "after fixing the bot's permissions.")

    latest = get_application(application_id)
    await update_review_message(guild, latest)
    await publish_official_family(guild, latest)
    welcome = discord.Embed(
        title=f"Welcome, {safe(app['family_name'])}!",
        description=(
            f"Your family is now **official** in HighschoolRP.\n\n"
            f"**Family Leader:** <@{app['owner_id']}>\n"
            f"**Community:** {safe(app['server_group'])}\n"
            f"**Age Group:** {app['age_group']}\n\n"
            "Use `/family-add` to invite family members and `/family-kick` to remove them.\n"
            "Only your family and the Head of Families can access these channels."
        ), color=BRAND,
    )
    try:
        await announcement.send(embed=welcome, file=logo_file(),
                                allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        LOGGER.warning("Welcome message could not be sent for #%s", application_id)
    await send_private(founder, discord.Embed(
        title="Your Family Has Been Approved!",
        description=f"**{safe(app['family_name'])}** is now official in **{guild.name}**. "
                    f"Your private channels are ready: <#{latest['chat_channel_id']}>.",
        color=0x32B77A,
    ))
    return True, (f"Approved **{safe(app['family_name'])}**. Roles and four private channels "
                  f"were created. Family chat: <#{latest['chat_channel_id']}>")


async def decline_application(guild: discord.Guild, application_id: int,
                              moderator: discord.Member, reason: str) -> tuple[bool, str]:
    app = get_application(application_id)
    if not app or app["guild_id"] != guild.id:
        return False, "Application not found in this server."
    if not decline(application_id, guild.id, moderator.id, reason):
        return False, "This application has already been handled or is processing."
    latest = get_application(application_id)
    await update_review_message(guild, latest)
    try:
        founder = await fetch_member(guild, app["owner_id"])
    except discord.HTTPException:
        founder = None
    if founder:
        await send_private(founder, discord.Embed(
            title="Family Application Declined",
            description=(f"Your application for **{safe(app['family_name'])}** was declined."
                         + (f"\n**Reason:** {safe(reason)}" if reason else "")
                         + "\nYou may submit a new application."),
            color=0xE05656,
        ))
    return True, f"Application #{application_id} was declined."


class FamilyModal(discord.ui.Modal, title="Official Family Application"):
    family_name = discord.ui.TextInput(
        label="Family name", placeholder="Example: Sakura", min_length=2, max_length=32,
    )
    members = discord.ui.TextInput(
        label="Current number of members", placeholder="Example: 12", max_length=4,
    )
    community = discord.ui.TextInput(
        label="Server / community", placeholder="North America / Spanish / Europe", max_length=40,
    )
    age = discord.ui.TextInput(
        label="Age group (13+ or 18+)", placeholder="13+", max_length=3,
    )
    color = discord.ui.TextInput(
        label="Family role color (HEX)", placeholder="#00FFFF", max_length=7,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Applications must be submitted in a server.", ephemeral=True)
            return
        family_name = sanitize_name(str(self.family_name))
        community = sanitize_server(str(self.community))
        age = str(self.age).strip()
        color = parse_color(str(self.color))
        try:
            member_count = int(str(self.members).strip())
        except ValueError:
            member_count = 0
        errors = []
        if not family_name:
            errors.append("Family names must contain 2–32 letters, numbers, spaces, hyphens or apostrophes.")
        if not community:
            errors.append("Enter a valid server/community name (2–40 characters).")
        if not 1 <= member_count <= 9999:
            errors.append("Member count must be a number between 1 and 9,999.")
        if age not in ("13+", "18+"):
            errors.append("Age group must be exactly `13+` or `18+`.")
        if not color:
            errors.append("Color must be a 6-digit HEX value such as `#00FFFF`.")
        if errors:
            await interaction.response.send_message("\n".join(errors), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        setting = get_setting(interaction.guild.id)
        if setting is None:
            await interaction.followup.send("Family applications are not configured yet.", ephemeral=True)
            return
        application_id, message = create_application(
            interaction.guild.id, interaction.user.id, family_name,
            member_count, community, age, color,
        )
        if not application_id:
            await interaction.followup.send(message, ephemeral=True)
            return
        posted = await post_review(interaction.guild, get_application(application_id))
        if posted:
            await interaction.followup.send(
                f"**Your family application has been submitted!**\n"
                f"**Family:** {safe(family_name)}\n**Application ID:** `#{application_id}`\n"
                "The **Head of Families** will approve or decline your request. "
                "No roles or channels will be created until approval.", ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"Your application `#{application_id}` was saved, but the review channel "
                "could not receive it. Contact the Head of Families and ask them to "
                f"use `/family-review application_id:{application_id}`.", ephemeral=True,
            )


class PanelView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Apply for an Official Family", style=discord.ButtonStyle.primary,
                       emoji="🏫", custom_id="hsrp:apply:v1")
    async def apply_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(FamilyModal())


class DeclineModal(discord.ui.Modal, title="Decline Family Application"):
    reason = discord.ui.TextInput(
        label="Reason for declining (optional)", placeholder="Explain why the application was declined",
        style=discord.TextStyle.paragraph, max_length=250, required=False,
    )

    def __init__(self, application_id: int):
        super().__init__()
        self.application_id = application_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member) or not is_head(
            interaction.user, get_setting(guild.id)
        ):
            await interaction.response.send_message("Only the Head of Families can review applications.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        success, message = await decline_application(
            guild, self.application_id, interaction.user, str(self.reason).strip(),
        )
        await interaction.followup.send(message, ephemeral=True)


class ReviewView(discord.ui.View):
    def __init__(self, application_id: int):
        super().__init__(timeout=None)
        self.application_id = application_id
        approve_button = discord.ui.Button(
            label="Approve Family", style=discord.ButtonStyle.success,
            custom_id=f"hsrp:approve:{application_id}", emoji="✅",
        )
        decline_button = discord.ui.Button(
            label="Decline Family", style=discord.ButtonStyle.danger,
            custom_id=f"hsrp:decline:{application_id}", emoji="❌",
        )
        approve_button.callback = self.approve_callback
        decline_button.callback = self.decline_callback
        self.add_item(approve_button)
        self.add_item(decline_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if (interaction.guild is None or not isinstance(interaction.user, discord.Member)
                or not is_head(interaction.user, get_setting(interaction.guild.id))):
            await interaction.response.send_message(
                "Only the **Head of Families** or a server manager can review applications.",
                ephemeral=True,
            )
            return False
        return True

    async def approve_callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        success, message = await approve_application(
            interaction.guild, self.application_id, interaction.user,
        )
        await interaction.followup.send(message, ephemeral=True)

    async def decline_callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(DeclineModal(self.application_id))


class WhitelistDeclineModal(discord.ui.Modal, title="Decline Whitelist Request"):
    reason = discord.ui.TextInput(label="Reason for declining", max_length=300,
                                  style=discord.TextStyle.paragraph, required=True)

    def __init__(self, request_id: int):
        super().__init__()
        self.request_id = request_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if (not interaction.guild or not isinstance(interaction.user, discord.Member)
            or not is_head(interaction.user, get_setting(interaction.guild.id))):
            await interaction.response.send_message("Only the Head of Families can review the whitelist.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        ok, message = await decide_whitelist_request(interaction.guild, self.request_id,
                                                     interaction.user, False, str(self.reason).strip())
        await interaction.followup.send(message, ephemeral=True)


class WhitelistReviewView(discord.ui.View):
    def __init__(self, request_id: int):
        super().__init__(timeout=None)
        self.request_id = request_id
        yes = discord.ui.Button(label="Whitelist • Approve", style=discord.ButtonStyle.success,
                                emoji="✅", custom_id=f"hsrp:wlapprove:{request_id}")
        no = discord.ui.Button(label="Whitelist • Decline", style=discord.ButtonStyle.danger,
                               emoji="❌", custom_id=f"hsrp:wldecline:{request_id}")
        yes.callback = self.approve
        no.callback = self.decline
        self.add_item(yes)
        self.add_item(no)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if (not interaction.guild or not isinstance(interaction.user, discord.Member)
            or not is_head(interaction.user, get_setting(interaction.guild.id))):
            await interaction.response.send_message("Head of Families permissions required.", ephemeral=True)
            return False
        return True

    async def approve(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        ok, message = await decide_whitelist_request(interaction.guild, self.request_id,
                                                     interaction.user, True, "Approved by Family Management")
        await interaction.followup.send(message, ephemeral=True)

    async def decline(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(WhitelistDeclineModal(self.request_id))


class HighschoolCrowBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = False
        intents.members = False  # Guild REST fetching + slash option resolution are enough.
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.recovered = False

    async def setup_hook(self) -> None:
        initialize_database()
        self.add_view(PanelView())
        for row in get_pending_views():
            self.add_view(ReviewView(row["id"]), message_id=row["review_message_id"])
        for row in get_pending_whitelist_views():
            self.add_view(WhitelistReviewView(row["id"]), message_id=row["review_message_id"])
        if GUILD_ID:
            target = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=target)
            synced = await self.tree.sync(guild=target)
            LOGGER.info("Registered %d slash commands in test guild %s", len(synced), GUILD_ID)
        else:
            synced = await self.tree.sync()
            LOGGER.info("Registered %d global slash commands", len(synced))

    async def on_ready(self) -> None:
        LOGGER.info("CrowBot ready as %s (%s)", self.user, self.user.id)
        if self.recovered:
            return
        self.recovered = True
        # An interrupted approval should not get stuck in 'processing' forever.
        for app in get_incomplete():
            guild = self.get_guild(app["guild_id"])
            if guild is None:
                LOGGER.error("Could not recover application #%s: guild unavailable", app["id"])
                continue
            LOGGER.warning("Recovering interrupted provisioning for family #%s", app["id"])
            if await cleanup_resources(guild, app):
                restore_pending(app["id"])
            else:
                LOGGER.error("Cleanup failed for application #%s: use /family-recover", app["id"])


bot = HighschoolCrowBot()


async def require_guild(interaction: discord.Interaction) -> discord.Guild | None:
    if interaction.guild is None:
        await interaction.response.send_message("This command is only available in a server.", ephemeral=True)
        return None
    return interaction.guild


async def check_head(interaction: discord.Interaction) -> bool:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member) or not is_head(
        interaction.user, get_setting(interaction.guild.id)
    ):
        await interaction.response.send_message(
            "You need the **Head of Families** role or server management permissions.", ephemeral=True,
        )
        return False
    return True


@bot.tree.command(name="family-setup", description="Configure official family applications and review permissions.")
@app_commands.describe(applications="Public channel for the family application panel",
                       reviews="Private channel for Heads of Families to review requests",
                       head_of_families="The Head of Families Discord role")
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
async def family_setup(interaction: discord.Interaction, applications: discord.TextChannel,
                       reviews: discord.TextChannel, head_of_families: discord.Role) -> None:
    guild = await require_guild(interaction)
    if guild is None:
        return
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("Only server managers can run setup.", ephemeral=True)
        return
    if head_of_families.is_default() or applications.id == reviews.id:
        await interaction.response.send_message(
            "Choose a real Head of Families role and two different text channels.", ephemeral=True)
        return
    me = await fetch_member(guild, guild.me.id if guild.me else bot.user.id)
    needed = ("manage_roles", "manage_channels", "view_channel", "send_messages", "embed_links", "attach_files")
    missing = [p.replace("_", " ") for p in needed if not getattr(me.guild_permissions, p)]
    for channel in (applications, reviews):
        perms = channel.permissions_for(me)
        for permission in ("view_channel", "send_messages", "embed_links", "attach_files"):
            if not getattr(perms, permission) and permission.replace("_", " ") not in missing:
                missing.append(f"{permission.replace('_', ' ')} in #{channel.name}")
    if missing:
        await interaction.response.send_message("Missing bot permissions: " + ", ".join(missing), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        message = await applications.send(
            embed=make_panel_embed(), file=logo_file(), view=PanelView(),
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except discord.HTTPException as exc:
        await interaction.followup.send(f"Could not post the application panel: {exc}", ephemeral=True)
        return
    save_setting(guild.id, applications.id, reviews.id, head_of_families.id)
    await interaction.followup.send(
        f"**Family system configured.**\n"
        f"Application panel: {message.jump_url}\n"
        f"Review channel: {reviews.mention}\n"
        f"Approving role: {head_of_families.mention}\n"
        "Move the bot role **above all family roles** in Server Settings → Roles.", ephemeral=True,
    )


@bot.tree.command(name="family-panel", description="Post a fresh family application panel.")
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
async def family_panel(interaction: discord.Interaction) -> None:
    guild = await require_guild(interaction)
    if guild is None:
        return
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("Only server managers can post the panel.", ephemeral=True)
        return
    setting = get_setting(guild.id)
    if not setting:
        await interaction.response.send_message("Run `/family-setup` first.", ephemeral=True)
        return
    channel = await find_text_channel(guild, setting["applications_channel_id"])
    if channel is None:
        await interaction.response.send_message("Configured application channel is missing.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        message = await channel.send(embed=make_panel_embed(), file=logo_file(),
                                     view=PanelView(), allowed_mentions=discord.AllowedMentions.none())
        await interaction.followup.send(f"Panel posted: {message.jump_url}", ephemeral=True)
    except discord.HTTPException as exc:
        await interaction.followup.send(f"Failed to post panel: {exc}", ephemeral=True)


@bot.tree.command(name="family-review", description="Repost an application to the Head of Families review channel.")
@app_commands.describe(application_id="The application number shown in /family-pending")
@app_commands.guild_only()
async def family_review(interaction: discord.Interaction, application_id: int) -> None:
    if not await check_head(interaction):
        return
    app = get_application(application_id)
    if not app or app["guild_id"] != interaction.guild.id or app["status"] != "pending":
        await interaction.response.send_message("That application is not pending here.", ephemeral=True)
        return
    if app["review_message_id"]:
        # Confirm the existing review message can still be fetched.
        setting = get_setting(interaction.guild.id)
        channel = await find_text_channel(interaction.guild, setting["reviews_channel_id"])
        try:
            if channel:
                await channel.fetch_message(app["review_message_id"])
                await interaction.response.send_message("This application already has a review message.", ephemeral=True)
                return
        except discord.HTTPException:
            pass
        set_review_message(application_id, None)
    await interaction.response.defer(ephemeral=True, thinking=True)
    posted = await post_review(interaction.guild, get_application(application_id))
    await interaction.followup.send("Review card posted." if posted else "Failed to post review card. Check the review channel and permissions.", ephemeral=True)


@bot.tree.command(name="family-pending", description="List applications waiting for a family review.")
@app_commands.guild_only()
async def family_pending(interaction: discord.Interaction) -> None:
    if not await check_head(interaction):
        return
    with connect() as db:
        rows = db.execute("""
            SELECT id, family_name, owner_id, created_at, status
            FROM applications WHERE guild_id=? AND status IN ('pending','processing')
            ORDER BY id DESC LIMIT 20
        """, (interaction.guild.id,)).fetchall()
    if not rows:
        await interaction.response.send_message("No pending applications.", ephemeral=True)
        return
    lines = [f"`#{row['id']}` • **{safe(row['family_name'])}** • <@{row['owner_id']}> • {row['status']}"
             for row in rows]
    await interaction.response.send_message("**Pending applications**\n" + "\n".join(lines),
                                            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="family-recover", description="Clean up an interrupted family approval and restore the request.")
@app_commands.describe(application_id="Application number stuck in processing")
@app_commands.guild_only()
async def family_recover(interaction: discord.Interaction, application_id: int) -> None:
    if not await check_head(interaction):
        return
    app = get_application(application_id)
    if not app or app["guild_id"] != interaction.guild.id or app["status"] != "processing":
        await interaction.response.send_message(
            "This family is not in interrupted processing status.", ephemeral=True,
        )
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    if await cleanup_resources(interaction.guild, app):
        restore_pending(application_id)
        await interaction.followup.send(
            f"Recovered application `#{application_id}`. It is pending again and can be approved.",
            ephemeral=True,
        )
    else:
        await interaction.followup.send(
            "Some resources could not be removed. Check the bot's Manage Roles / Manage "
            "Channels permissions, then run `/family-recover` again.", ephemeral=True,
        )


@bot.tree.command(name="family-approve", description="Approve a pending family by its application ID.")
@app_commands.describe(application_id="Application number")
@app_commands.guild_only()
async def family_approve(interaction: discord.Interaction, application_id: int) -> None:
    if not await check_head(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    success, message = await approve_application(interaction.guild, application_id, interaction.user)
    await interaction.followup.send(message, ephemeral=True)


@bot.tree.command(name="family-decline", description="Decline a pending family by application ID.")
@app_commands.describe(application_id="Application number", reason="Optional explanation for the applicant")
@app_commands.guild_only()
async def family_decline(interaction: discord.Interaction, application_id: int,
                         reason: str = "") -> None:
    if not await check_head(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    success, message = await decline_application(interaction.guild, application_id,
                                                  interaction.user, reason[:250].strip())
    await interaction.followup.send(message, ephemeral=True)


@bot.tree.command(name="family-status", description="Check the status of your family application.")
@app_commands.guild_only()
async def family_status(interaction: discord.Interaction) -> None:
    guild = await require_guild(interaction)
    if guild is None:
        return
    with connect() as db:
        app = db.execute("""
            SELECT * FROM applications WHERE guild_id=? AND owner_id=?
            ORDER BY id DESC LIMIT 1
        """, (guild.id, interaction.user.id)).fetchone()
    if not app:
        await interaction.response.send_message("You haven't submitted a family application yet.", ephemeral=True)
        return
    response = (f"**{safe(app['family_name'])}** • Application `#{app['id']}`\n"
                f"**Status:** {app['status'].upper()}\n"
                f"**Server:** {safe(app['server_group'])} • **Age group:** {app['age_group']}")
    if app["status"] == "approved":
        response += f"\n**Family chat:** <#{app['chat_channel_id']}>"
    if app["decline_reason"]:
        response += f"\n**Reason:** {safe(app['decline_reason'])}"
    if app["status"] in ("blacklisted", "removed", "removing"):
        response += f"\n**Moderation reason:** {safe(app['moderation_reason'] or 'Not provided')}"
    await interaction.response.send_message(response, ephemeral=True,
                                            allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="family-directory", description="See currently approved HighschoolRP families.")
@app_commands.guild_only()
async def family_directory(interaction: discord.Interaction) -> None:
    guild = await require_guild(interaction)
    if guild is None:
        return
    with connect() as db:
        rows = db.execute("""
            SELECT id, family_name, owner_id, server_group, age_group FROM applications
            WHERE guild_id=? AND status='approved' ORDER BY family_name LIMIT 25
        """, (guild.id,)).fetchall()
    if not rows:
        await interaction.response.send_message("There are no official families yet.", ephemeral=True)
        return
    embed = discord.Embed(title="HighschoolRP | Official Families", color=BRAND)
    for app in rows:
        embed.add_field(name=f"{safe(app['family_name'])} • #{app['id']}",
                        value=f"Leader: <@{app['owner_id']}>\n{safe(app['server_group'])} • {app['age_group']}\nActive warns: {len(get_warnings(app['id'], True))}",
                        inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True,
                                            allowed_mentions=discord.AllowedMentions.none())


def member_has_another_family(guild_id: int, member: discord.Member,
                              excluding_application: int) -> bool:
    role_ids = {r.id for r in member.roles}
    with connect() as db:
        rows = db.execute("""
            SELECT member_role_id, leader_role_id FROM applications
            WHERE guild_id=? AND status='approved' AND id<>?
        """, (guild_id, excluding_application)).fetchall()
    return any(app["member_role_id"] in role_ids or app["leader_role_id"] in role_ids
               for app in rows)


@bot.tree.command(name="family-add", description="As a family leader, add someone to your official family.")
@app_commands.describe(member="Server member to invite to your family")
@app_commands.guild_only()
async def family_add(interaction: discord.Interaction, member: discord.Member) -> None:
    guild = await require_guild(interaction)
    if guild is None:
        return
    app = get_official_for_leader(guild.id, interaction.user.id)
    if not app:
        await interaction.response.send_message("Only an official family leader can use this command.", ephemeral=True)
        return
    role = guild.get_role(app["member_role_id"])
    if not role:
        await interaction.response.send_message("Your family member role is missing. Contact a server administrator.", ephemeral=True)
        return
    if member.bot or member.id == interaction.user.id:
        await interaction.response.send_message("Select a different human member.", ephemeral=True)
        return
    if role in member.roles:
        await interaction.response.send_message("That user is already in your family.", ephemeral=True)
        return
    if member_has_another_family(guild.id, member, app["id"]):
        await interaction.response.send_message("That person already belongs to another official family.", ephemeral=True)
        return
    try:
        await member.add_roles(role, reason=f"Added by {interaction.user} to official family #{app['id']}")
    except discord.HTTPException as exc:
        await interaction.response.send_message(f"Couldn't assign the member role: {exc}", ephemeral=True)
        return
    await interaction.response.send_message(
        f"{member.mention} has joined **{safe(app['family_name'])}**!", ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


@bot.tree.command(name="family-kick", description="As a family leader, remove someone from your official family.")
@app_commands.describe(member="Family member to remove")
@app_commands.guild_only()
async def family_kick(interaction: discord.Interaction, member: discord.Member) -> None:
    guild = await require_guild(interaction)
    if guild is None:
        return
    app = get_official_for_leader(guild.id, interaction.user.id)
    if not app:
        await interaction.response.send_message("Only an official family leader can use this command.", ephemeral=True)
        return
    role = guild.get_role(app["member_role_id"])
    if not role or role not in member.roles:
        await interaction.response.send_message("That person doesn't have your family member role.", ephemeral=True)
        return
    try:
        await member.remove_roles(role, reason=f"Removed by {interaction.user} from family #{app['id']}")
    except discord.HTTPException as exc:
        await interaction.response.send_message(f"Couldn't remove the member role: {exc}", ephemeral=True)
        return
    await interaction.response.send_message(
        f"Removed {member.mention} from **{safe(app['family_name'])}**.", ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


@bot.tree.command(name="family-channels", description="Configure official family and blacklist announcement channels.")
@app_commands.describe(official_families="Public channel for approved family cards",
                       family_blacklist="Public read-only channel listing blacklisted families")
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
async def family_channels(interaction: discord.Interaction, official_families: discord.TextChannel,
                          family_blacklist: discord.TextChannel) -> None:
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("Server management permissions required.", ephemeral=True)
        return
    guild = interaction.guild
    setting = get_setting(guild.id)
    if not setting:
        await interaction.response.send_message("Run `/family-setup` first.", ephemeral=True)
        return
    if official_families.id == family_blacklist.id:
        await interaction.response.send_message("Choose two different channels.", ephemeral=True)
        return
    me = await fetch_member(guild, guild.me.id if guild.me else bot.user.id)
    for channel in (official_families, family_blacklist):
        perms = channel.permissions_for(me)
        if not all((perms.view_channel, perms.send_messages, perms.embed_links, perms.read_message_history)):
            await interaction.response.send_message(
                f"CrowBot needs View Channel, Send Messages, Embed Links and Read Message History in {channel.mention}.",
                ephemeral=True)
            return
    if not official_families.permissions_for(me).attach_files:
        await interaction.response.send_message("CrowBot needs Attach Files in the official families channel.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    if setting["official_channel_id"] and setting["official_channel_id"] != official_families.id:
        # Delete old cards before republishing in a new channel.
        for app in get_approved_families(guild.id):
            if app["official_message_id"]:
                old_channel = await find_text_channel(guild, setting["official_channel_id"])
                if old_channel:
                    try:
                        await (await old_channel.fetch_message(app["official_message_id"])).delete()
                    except discord.NotFound:
                        pass
                    except discord.HTTPException:
                        LOGGER.warning("Could not delete moved official card #%s", app["id"])
                save_official_message(app["id"], None)
    save_board_channels(guild.id, official_families.id, family_blacklist.id)
    updated = 0
    for app in get_approved_families(guild.id):
        updated += int(await publish_official_family(guild, app))
    listed = await refresh_blacklist_board(guild)
    await interaction.followup.send(
        f"✅ Official family cards: {official_families.mention} ({updated} published/updated).\n"
        f"🚫 Blacklist dashboard: {family_blacklist.mention} "
        f"({'updated' if listed else 'failed — check channel permissions'}).",
        ephemeral=True)


@bot.tree.command(name="family-sync-boards", description="Refresh official families and the blacklist dashboard.")
@app_commands.guild_only()
async def family_sync_boards(interaction: discord.Interaction) -> None:
    if not await check_head(interaction):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    approved = get_approved_families(interaction.guild.id)
    updated = sum([int(await publish_official_family(interaction.guild, app)) for app in approved])
    listed = await refresh_blacklist_board(interaction.guild)
    await interaction.followup.send(
        f"Published/updated {updated}/{len(approved)} official family cards. "
        + ("Blacklist dashboard refreshed." if listed else "Blacklist dashboard unavailable. Check /family-channels."),
        ephemeral=True)


@bot.tree.command(name="family-whitelist-request", description="Ask to join the family management removal whitelist.")
@app_commands.guild_only()
async def family_whitelist_request(interaction: discord.Interaction) -> None:
    if not isinstance(interaction.user, discord.Member):
        return
    if not get_setting(interaction.guild.id):
        await interaction.response.send_message("Family system is not configured.", ephemeral=True)
        return
    request_id, result = create_whitelist_request(interaction.guild.id, interaction.user.id)
    if request_id is None:
        await interaction.response.send_message(result, ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    success = await publish_whitelist_review(interaction.guild, get_whitelist_request(request_id))
    await interaction.followup.send(
        f"Whitelist request `#{request_id}` submitted. "
        + ("The Head of Families will review it." if success else
           "The review card could not be posted; ask the Head of Families to use `/family-whitelist-repost`."),
        ephemeral=True)


@bot.tree.command(name="family-whitelist-repost", description="Repost a pending whitelist request to the review channel.")
@app_commands.guild_only()
async def family_whitelist_repost(interaction: discord.Interaction, request_id: int) -> None:
    if not await check_head(interaction):
        return
    req = get_whitelist_request(request_id)
    if not req or req["guild_id"] != interaction.guild.id or req["status"] != 'pending':
        await interaction.response.send_message("No pending whitelist request with that ID.", ephemeral=True)
        return
    set_whitelist_message(request_id, None)
    await interaction.response.defer(ephemeral=True, thinking=True)
    ok = await publish_whitelist_review(interaction.guild, get_whitelist_request(request_id))
    await interaction.followup.send("Request reposted." if ok else "Could not post the request.", ephemeral=True)


@bot.tree.command(name="family-whitelist-list", description="Show whitelist requests and approved users.")
@app_commands.guild_only()
async def family_whitelist_list(interaction: discord.Interaction) -> None:
    if not await check_head(interaction):
        return
    with connect() as db:
        rows = db.execute("""SELECT * FROM whitelist_requests WHERE guild_id=?
                             AND status IN ('pending','approved') ORDER BY id DESC LIMIT 20""",
                          (interaction.guild.id,)).fetchall()
    message = "\n".join(f"`#{r['id']}` • <@{r['user_id']}> • **{r['status']}**" for r in rows)
    await interaction.response.send_message("**Family Management Whitelist**\n" + (message or "No requests."),
                                            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="family-whitelist-revoke", description="Revoke access to remove families.")
@app_commands.guild_only()
async def family_whitelist_revoke(interaction: discord.Interaction, member: discord.Member) -> None:
    if not await check_head(interaction):
        return
    ok = revoke_whitelist(interaction.guild.id, member.id, interaction.user.id)
    await interaction.response.send_message("Whitelist access revoked." if ok else "User is not whitelisted.", ephemeral=True)


@bot.tree.command(name="family-remove", description="Remove an official family (WHITELIST required). Irreversible.")
@app_commands.describe(application_id="Official family application ID", reason="Reason for removal",
                       confirm="Must be True: deletes the family's roles and four private channels")
@app_commands.guild_only()
async def family_remove(interaction: discord.Interaction, application_id: int, reason: str, confirm: bool) -> None:
    if not isinstance(interaction.user, discord.Member) or not (
            is_head(interaction.user, get_setting(interaction.guild.id))
            or is_whitelisted(interaction.guild.id, interaction.user.id)):
        await interaction.response.send_message("You must be on the approved family removal whitelist.", ephemeral=True)
        return
    if not confirm:
        await interaction.response.send_message("Set `confirm:True` to permanently delete family roles and channels.", ephemeral=True)
        return
    if not reason.strip():
        await interaction.response.send_message("A removal reason is required.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    ok, msg = await remove_family(interaction.guild, application_id, interaction.user,
                                  'removed', reason.strip()[:350])
    await interaction.followup.send(msg, ephemeral=True)


@bot.tree.command(name="family-remove-retry", description="Continue cleanup after interrupted family removal or blacklist.")
@app_commands.guild_only()
async def family_remove_retry(interaction: discord.Interaction, application_id: int) -> None:
    app = get_application(application_id)
    if not app or app["guild_id"] != interaction.guild.id or app["status"] != 'removing':
        await interaction.response.send_message("No interrupted family removal found.", ephemeral=True)
        return
    has_head = isinstance(interaction.user, discord.Member) and is_head(
        interaction.user, get_setting(interaction.guild.id))
    whitelisted_remove = (app["moderation_action"] == 'removed'
                          and isinstance(interaction.user, discord.Member)
                          and is_whitelisted(interaction.guild.id, interaction.user.id))
    if not (has_head or whitelisted_remove):
        await interaction.response.send_message("You do not have permission to retry this cleanup.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    ok, msg = await remove_family(interaction.guild, application_id, interaction.user,
                                  app["moderation_action"], app["moderation_reason"] or "", retry=True)
    await interaction.followup.send(msg, ephemeral=True)


@bot.tree.command(name="family-warn", description="Give an official family a numbered warning (Head only).")
@app_commands.guild_only()
async def family_warn(interaction: discord.Interaction, application_id: int, reason: str) -> None:
    if not await check_head(interaction):
        return
    if not reason.strip():
        await interaction.response.send_message("Please include a warning reason.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    number = add_warning(interaction.guild.id, application_id, interaction.user.id, reason.strip()[:350])
    if number is None:
        await interaction.followup.send("Family not found or not currently approved.", ephemeral=True)
        return
    app = get_application(application_id)
    await publish_official_family(interaction.guild, app)
    embed = discord.Embed(title=f"⚠️ {safe(app['family_name'])} — Warn {number}",
        description=f"**Reason:** {safe(reason.strip()[:350])}\n**Issued by:** {interaction.user.mention}",
        color=0xFFAE42)
    setting = get_setting(interaction.guild.id)
    channel = (await find_text_channel(interaction.guild, setting['official_channel_id'])
               if setting and setting['official_channel_id'] else None)
    if channel:
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            LOGGER.warning("Could not post public warning #%s for family #%s", number, app['id'])
    await send_private_if_possible(interaction.guild, app['owner_id'], embed)
    await interaction.followup.send(f"Warn **{number}** issued to **{safe(app['family_name'])}**.", ephemeral=True)


@bot.tree.command(name="family-warns", description="View a family's warning history.")
@app_commands.guild_only()
async def family_warns(interaction: discord.Interaction, application_id: int) -> None:
    app = get_application(application_id)
    if not app or app['guild_id'] != interaction.guild.id:
        await interaction.response.send_message("Family not found.", ephemeral=True)
        return
    warnings = get_warnings(application_id)
    if not warnings:
        await interaction.response.send_message(f"**{safe(app['family_name'])}** has no warnings.", ephemeral=True)
        return
    output = [f"**Warn {w['number']}** {'(revoked)' if w['revoked_at'] else '(active)'}: "
              f"{safe(w['reason'][:150])} • <@{w['issued_by']}>" for w in warnings[-20:]]
    await interaction.response.send_message(
        f"**Warnings — {safe(app['family_name'])}**\n" + "\n".join(output),
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="family-unwarn", description="Revoke an active family warning (Head only).")
@app_commands.guild_only()
async def family_unwarn(interaction: discord.Interaction, application_id: int,
                        warn_number: int, reason: str) -> None:
    if not await check_head(interaction):
        return
    if not reason.strip():
        await interaction.response.send_message("A reason is required to revoke a warning.", ephemeral=True)
        return
    if not revoke_warning(interaction.guild.id, application_id, warn_number,
                          interaction.user.id, reason.strip()[:350]):
        await interaction.response.send_message("Warning not found, already revoked or family not approved.", ephemeral=True)
        return
    app = get_application(application_id)
    await interaction.response.defer(ephemeral=True, thinking=True)
    await publish_official_family(interaction.guild, app)
    await interaction.followup.send(
        f"Warn {warn_number} revoked from **{safe(app['family_name'])}**. "
        f"Reason: {safe(reason[:200])}", ephemeral=True)


@bot.tree.command(name="family-blacklist", description="Blacklist an official family (Head only). Irreversible channels/roles deletion.")
@app_commands.describe(confirm="Must be True: deletes the family's roles and four private channels")
@app_commands.guild_only()
async def family_blacklist(interaction: discord.Interaction, application_id: int,
                           reason: str, confirm: bool) -> None:
    if not await check_head(interaction):
        return
    if not confirm or not reason.strip():
        await interaction.response.send_message("Provide a reason and set `confirm:True` to delete family channels and roles.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    ok, msg = await remove_family(interaction.guild, application_id, interaction.user,
                                  'blacklisted', reason.strip()[:350])
    await interaction.followup.send(msg, ephemeral=True)


@bot.tree.command(name="family-unblacklist", description="Lift a family's blacklist status (Head only).")
@app_commands.guild_only()
async def family_unblacklist(interaction: discord.Interaction, application_id: int, reason: str) -> None:
    if not await check_head(interaction):
        return
    if not reason.strip():
        await interaction.response.send_message("A reason is required.", ephemeral=True)
        return
    if not unblacklist_family(interaction.guild.id, application_id,
                              interaction.user.id, reason.strip()[:350]):
        await interaction.response.send_message("That application is not blacklisted.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    await refresh_blacklist_board(interaction.guild)
    await interaction.followup.send("Blacklist removed. This does not recreate roles or private channels; the former leader may apply again.", ephemeral=True)


@bot.tree.command(name="family-blacklist-list", description="Show all blacklisted family names and IDs.")
@app_commands.guild_only()
async def family_blacklist_list(interaction: discord.Interaction) -> None:
    rows = get_blacklisted_families(interaction.guild.id)
    if not rows:
        await interaction.response.send_message("No blacklisted families.", ephemeral=True)
        return
    # Discord's 2000-character limit for ephemeral text: show a concise first page.
    lines = [f"`#{a['id']}` • **{safe(a['family_name'])}** • former leader <@{a['owner_id']}>"
             for a in rows[:15]]
    await interaction.response.send_message(
        "**HighschoolRP Blacklist**\n" + "\n".join(lines)
        + ("\nSee the configured blacklist channel for the full register." if len(rows) > 15 else ""),
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="family-ping", description="Check CrowBot's connection to Discord.")
@app_commands.guild_only()
async def family_ping(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        f"CrowBot is online. Gateway latency: **{round(bot.latency * 1000)} ms**.",
        ephemeral=True,
    )


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction,
                               error: app_commands.AppCommandError) -> None:
    LOGGER.error("Slash command failed: %s", error, exc_info=(type(error), error, error.__traceback__))
    message = "Something went wrong. Check CrowBot's logs or contact a server administrator."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    if not TOKEN or TOKEN.lower().startswith("paste"):
        raise SystemExit("Missing DISCORD_TOKEN. Create .env from .env.example or set a hosting variable.")
    bot.run(TOKEN, log_handler=None)
