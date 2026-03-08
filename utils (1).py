# ╔══════════════════════════════════════════════════════════════════════╗
# ║   ⚡ GADGET PREMIUM HOST  v4.0  ·  utils.py                         ║
# ╚══════════════════════════════════════════════════════════════════════╝

from __future__ import annotations

import ast
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import config

# ─────────────────────────────────────────────────────────────────────
# TEXT FORMATTING
# ─────────────────────────────────────────────────────────────────────

def bar(cur: int | float, total: int | float, length: int = 12, fill: str = "█", empty: str = "░") -> str:
    if total <= 0:
        total = 1
    pct   = min(cur / total, 1.0)
    done  = int(length * pct)
    return fill * done + empty * (length - done)


def pbar(cur: int | float, total: int | float, length: int = 10) -> str:
    """Returns [████░░░░░░] style string."""
    return f"[{bar(cur, total, length)}]"


def fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def fmt_uptime(secs: float) -> str:
    secs = int(secs)
    d, r = divmod(secs, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


def fmt_ts(ts: Optional[str], fmt: str = "%Y-%m-%d %H:%M") -> str:
    if not ts:
        return "Never"
    try:
        return datetime.fromisoformat(ts).strftime(fmt)
    except Exception:
        return str(ts)[:16]


def plan_label(plan: str) -> str:
    return config.PLANS.get(plan, config.PLANS["free"])["label"]


def plan_emoji(plan: str) -> str:
    return config.PLANS.get(plan, config.PLANS["free"])["emoji"]


def plan_slots(plan: str) -> int:
    return config.PLANS.get(plan, config.PLANS["free"])["slots"]


def status_icon(status: str) -> str:
    return {"running": "🟢", "stopped": "🔴", "error": "🟡", "deleted": "⬛"}.get(status, "⚪")


# ─────────────────────────────────────────────────────────────────────
# SECTION BOXES
# ─────────────────────────────────────────────────────────────────────

def box(title: str, width: int = 32) -> str:
    pad = max(0, width - len(title) - 4)
    left  = pad // 2
    right = pad - left
    return (
        f"╔{'═' * (width)}╗\n"
        f"║{' ' * left}  {title}  {' ' * right}║\n"
        f"╚{'═' * (width)}╝"
    )


def divider(width: int = 33) -> str:
    return "━" * width


# ─────────────────────────────────────────────────────────────────────
# SYNTAX GUARD
# ─────────────────────────────────────────────────────────────────────

def syntax_check(source: str) -> tuple[bool, str]:
    """
    Parses Python source with ast.
    Returns (ok, error_html).
    """
    try:
        tree = ast.parse(source)
        # Extra: warn on dangerous top-level calls
        warnings = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in ("system", "popen"):
                    warnings.append(f"⚠️ Possible shell call detected: <code>{func.attr}</code>")
        warn_block = ("\n\n" + "\n".join(warnings)) if warnings else ""
        return True, warn_block
    except SyntaxError as e:
        snippet = (e.text or "").rstrip()
        pointer = " " * (e.offset - 1) + "^" if e.offset else ""
        return False, (
            "🛡️ <b>Syntax Guard: REJECTED</b>\n\n"
            f"🔍 <b>Line {e.lineno}:</b> <code>{e.msg}</code>\n"
            f"<pre>{snippet}\n{pointer}</pre>\n"
            "<i>Fix the error and re-upload.</i>"
        )
    except Exception as e:
        return False, f"⚠️ <b>Parse Error:</b> <code>{e}</code>"


# ─────────────────────────────────────────────────────────────────────
# MAINTENANCE
# ─────────────────────────────────────────────────────────────────────

def is_maintenance() -> bool:
    return Path(config.MAINTENANCE_FILE).exists()


def set_maintenance(on: bool) -> None:
    p = Path(config.MAINTENANCE_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    if on:
        p.write_text(datetime.now().isoformat())
    else:
        p.unlink(missing_ok=True)


def maintenance_since() -> Optional[str]:
    p = Path(config.MAINTENANCE_FILE)
    if not p.exists():
        return None
    try:
        return p.read_text().strip()
    except Exception:
        return "unknown"


# ─────────────────────────────────────────────────────────────────────
# ADMIN CHECK
# ─────────────────────────────────────────────────────────────────────

def is_owner(uid: int) -> bool:
    return uid == config.OWNER_ID


def is_admin(uid: int) -> bool:
    return uid == config.OWNER_ID or uid in config.CO_ADMINS


# ─────────────────────────────────────────────────────────────────────
# SAFE FILENAME
# ─────────────────────────────────────────────────────────────────────

def safe_name(name: str) -> str:
    return re.sub(r"[^\w\-_.]", "_", name)


# ─────────────────────────────────────────────────────────────────────
# RATE LIMITER (in-memory, per user)
# ─────────────────────────────────────────────────────────────────────

_cooldowns: dict[int, float] = {}


def is_rate_limited(uid: int, cooldown: float = config.USER_CMD_COOLDOWN) -> bool:
    now = time.time()
    last = _cooldowns.get(uid, 0)
    if now - last < cooldown:
        return True
    _cooldowns[uid] = now
    return False


# ─────────────────────────────────────────────────────────────────────
# DASHBOARD TEXT BUILDER
# ─────────────────────────────────────────────────────────────────────

def build_dashboard(uid: int, full_name: str) -> str:
    import database as db
    row      = db.get_user(uid)
    used, mx = db.get_slot_counts(uid)
    refs     = db.referral_count(uid)
    plan     = row["plan"] if row else "free"
    coins    = row["coins"] if row else 0
    streak   = row["daily_streak"] if row else 0
    bots_row = db.get_user_bots(uid)
    running  = sum(1 for b in bots_row if b["status"] == "running")
    slot_bar = pbar(used, mx)

    lines = [
        "╔═══════════════════════════════╗",
        f"║   ⚡  <b>{config.BOT_NAME}</b>",
        f"║       v{config.BOT_VERSION}  ·  Premium Hosting",
        "╚═══════════════════════════════╝",
        "",
        f"👋  <b>Hello, {full_name}!</b>",
        "",
        divider(),
        f"📋  Plan:       {plan_label(plan)}",
        f"🤖  Slots:      {slot_bar} <code>{used}/{mx}</code>",
        f"🟢  Running:    <code>{running}</code>  bot(s)",
        f"🪙  Coins:      <code>{coins:,}</code>",
        f"🔥  Streak:     <code>{streak}</code> day(s)",
        f"🔗  Referrals:  <code>{refs}</code> friends",
        divider(),
        "<i>Deploy · Manage · Earn  🚀</i>",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────
# VALIDATION HELPERS
# ─────────────────────────────────────────────────────────────────────

def validate_bot_name(name: str) -> tuple[bool, str]:
    """Validate bot name."""
    if not name or len(name) < 2:
        return False, "Name must be at least 2 characters."
    if len(name) > 40:
        return False, "Name must be at most 40 characters."
    if not re.match(r"^[\w\s\-]+$", name):
        return False, "Name can only contain letters, numbers, spaces, and hyphens."
    return True, name


def validate_env_key(key: str) -> tuple[bool, str]:
    """Validate environment variable key."""
    if not key:
        return False, "Key cannot be empty."
    if not re.match(r"^[A-Z_][A-Z0-9_]*$", key.upper()):
        return False, "Key must be uppercase letters, digits, and underscores, starting with a letter or underscore."
    return True, key.upper()


def validate_schedule_time(time_str: str) -> tuple[bool, str]:
    """Validate schedule time format (HH:MM)."""
    if not time_str:
        return False, "Time cannot be empty."
    if not re.match(r"^\d{2}:\d{2}$", time_str):
        return False, "Time must be in HH:MM format (e.g., 09:30)."
    hours, minutes = map(int, time_str.split(":"))
    if hours < 0 or hours > 23:
        return False, "Hours must be between 00 and 23."
    if minutes < 0 or minutes > 59:
        return False, "Minutes must be between 00 and 59."
    return True, time_str


# ─────────────────────────────────────────────────────────────────────
# FORMATTING HELPERS
# ─────────────────────────────────────────────────────────────────────

def format_user_info(user) -> str:
    """Format user information for display."""
    return (
        f"👤  <b>{user['full_name']}</b>\n"
        f"🔗  @{user['username'] or 'N/A'}\n"
        f"🆔  <code>{user['user_id']}</code>"
    )


def format_bot_info(bot) -> str:
    """Format bot information for display."""
    status_emoji = status_icon(bot['status'])
    return (
        f"🤖  <b>{bot['bot_name']}</b>\n"
        f"📊  {status_emoji} {bot['status'].title()}\n"
        f"🆔  <code>{bot['bot_id']}</code>"
    )


def format_time_ago(timestamp: str) -> str:
    """Format timestamp as 'X ago'."""
    if not timestamp:
        return "Never"
    try:
        dt = datetime.fromisoformat(timestamp)
        diff = datetime.now() - dt
        
        if diff.days > 365:
            return f"{diff.days // 365}y ago"
        if diff.days > 30:
            return f"{diff.days // 30}mo ago"
        if diff.days > 0:
            return f"{diff.days}d ago"
        if diff.seconds > 3600:
            return f"{diff.seconds // 3600}h ago"
        if diff.seconds > 60:
            return f"{diff.seconds // 60}m ago"
        return "just now"
    except Exception:
        return timestamp[:16]
