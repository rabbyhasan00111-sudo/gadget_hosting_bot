# ╔══════════════════════════════════════════════════════════════════════╗
# ║   ⚡ GADGET PREMIUM HOST  v4.0  ·  database.py                      ║
# ╚══════════════════════════════════════════════════════════════════════╝

from __future__ import annotations

import sqlite3
import time
import logging
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

import config

log = logging.getLogger("GPH.db")
_conn: Optional[sqlite3.Connection] = None


# ─────────────────────────────────────────────────────────────────────
# CONNECTION
# ─────────────────────────────────────────────────────────────────────

def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
        _conn.execute("PRAGMA synchronous=NORMAL")
    return _conn


# ─────────────────────────────────────────────────────────────────────
# SCHEMA
# ─────────────────────────────────────────────────────────────────────

def init() -> None:
    conn().executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id          INTEGER PRIMARY KEY,
            username         TEXT    DEFAULT '',
            full_name        TEXT    DEFAULT '',
            lang             TEXT    DEFAULT 'en',
            is_banned        INTEGER DEFAULT 0,
            ban_reason       TEXT    DEFAULT '',
            plan             TEXT    DEFAULT 'free',
            bonus_slots      INTEGER DEFAULT 0,
            coins            INTEGER DEFAULT 0,
            total_earned     INTEGER DEFAULT 0,
            daily_streak     INTEGER DEFAULT 0,
            last_daily       TEXT    DEFAULT NULL,
            weekly_claimed   INTEGER DEFAULT 0,
            monthly_claimed  INTEGER DEFAULT 0,
            admin_note       TEXT    DEFAULT '',
            referrer_id      INTEGER DEFAULT NULL,
            joined_at        TEXT    DEFAULT (datetime('now')),
            last_seen        TEXT    DEFAULT (datetime('now')),
            message_count    INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS bots (
            bot_id           INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id         INTEGER NOT NULL,
            bot_name         TEXT    NOT NULL,
            file_path        TEXT    NOT NULL,
            pid              INTEGER DEFAULT NULL,
            status           TEXT    DEFAULT 'stopped',
            auto_restart     INTEGER DEFAULT 1,
            restart_count    INTEGER DEFAULT 0,
            total_restarts   INTEGER DEFAULT 0,
            crash_count      INTEGER DEFAULT 0,
            total_uptime     INTEGER DEFAULT 0,
            start_ts         REAL    DEFAULT NULL,
            memory_usage     INTEGER DEFAULT 0,
            cpu_usage        REAL    DEFAULT 0.0,
            schedule_start   TEXT    DEFAULT NULL,
            schedule_stop    TEXT    DEFAULT NULL,
            created_at       TEXT    DEFAULT (datetime('now')),
            last_started     TEXT    DEFAULT NULL,
            FOREIGN KEY (owner_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS bot_envvars (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id  INTEGER NOT NULL,
            key     TEXT    NOT NULL,
            value   TEXT    NOT NULL,
            UNIQUE (bot_id, key),
            FOREIGN KEY (bot_id) REFERENCES bots(bot_id)
        );

        CREATE TABLE IF NOT EXISTS referrals (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id  INTEGER NOT NULL,
            referee_id   INTEGER NOT NULL UNIQUE,
            created_at   TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS coin_tx (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            amount      INTEGER NOT NULL,
            balance     INTEGER DEFAULT 0,
            reason      TEXT    DEFAULT '',
            created_at  TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS admin_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id    INTEGER NOT NULL,
            action      TEXT    NOT NULL,
            target_id   INTEGER DEFAULT NULL,
            detail      TEXT    DEFAULT '',
            created_at  TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS broadcasts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id    INTEGER NOT NULL,
            preview     TEXT    DEFAULT '',
            sent        INTEGER DEFAULT 0,
            failed      INTEGER DEFAULT 0,
            pinned      INTEGER DEFAULT 0,
            created_at  TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS system_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type  TEXT NOT NULL,
            detail      TEXT DEFAULT '',
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS user_activity (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            action      TEXT NOT NULL,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS api_keys (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            key_hash    TEXT    NOT NULL,
            name        TEXT    DEFAULT '',
            permissions TEXT    DEFAULT 'read',
            last_used   TEXT    DEFAULT NULL,
            created_at  TEXT    DEFAULT (datetime('now')),
            UNIQUE (user_id, key_hash)
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            type        TEXT    NOT NULL,
            title       TEXT    NOT NULL,
            message     TEXT    DEFAULT '',
            read        INTEGER DEFAULT 0,
            created_at  TEXT    DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_bots_owner ON bots(owner_id);
        CREATE INDEX IF NOT EXISTS idx_bots_status ON bots(status);
        CREATE INDEX IF NOT EXISTS idx_coin_tx_user ON coin_tx(user_id);
        CREATE INDEX IF NOT EXISTS idx_admin_log_time ON admin_log(created_at);
        CREATE INDEX IF NOT EXISTS idx_system_events_time ON system_events(created_at);
        CREATE INDEX IF NOT EXISTS idx_user_activity_user ON user_activity(user_id);
    """)
    conn().commit()
    log.info("Database ready ✔")


# ─────────────────────────────────────────────────────────────────────
# USER CRUD
# ─────────────────────────────────────────────────────────────────────

def get_user(uid: int) -> Optional[sqlite3.Row]:
    return conn().execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()


def upsert_user(uid: int, username: str, full_name: str,
                referrer_id: Optional[int] = None) -> bool:
    """True = new user."""
    existing = get_user(uid)
    if existing is None:
        conn().execute(
            "INSERT INTO users (user_id,username,full_name,referrer_id) VALUES(?,?,?,?)",
            (uid, username or "", full_name or "", referrer_id),
        )
        if referrer_id and referrer_id != uid:
            _credit_referral(referrer_id, uid)
        conn().commit()
        return True
    conn().execute(
        "UPDATE users SET username=?,full_name=?,last_seen=datetime('now'),"
        "message_count=message_count+1 WHERE user_id=?",
        (username or "", full_name or "", uid),
    )
    conn().commit()
    return False


def _credit_referral(referrer: int, referee: int) -> None:
    exists = conn().execute(
        "SELECT id FROM referrals WHERE referee_id=?", (referee,)
    ).fetchone()
    if exists:
        return
    conn().execute(
        "INSERT INTO referrals (referrer_id,referee_id) VALUES(?,?)", (referrer, referee)
    )
    _add_coins(referrer, config.REFERRAL_COINS, "referral reward")
    conn().commit()


def ban_user(uid: int, reason: str = "") -> None:
    conn().execute(
        "UPDATE users SET is_banned=1,ban_reason=? WHERE user_id=?", (reason, uid)
    )
    conn().commit()


def unban_user(uid: int) -> None:
    conn().execute(
        "UPDATE users SET is_banned=0,ban_reason='' WHERE user_id=?", (uid,)
    )
    conn().commit()


def set_plan(uid: int, plan: str) -> None:
    conn().execute("UPDATE users SET plan=? WHERE user_id=?", (plan, uid))
    conn().commit()


def set_note(uid: int, note: str) -> None:
    conn().execute("UPDATE users SET admin_note=? WHERE user_id=?", (note, uid))
    conn().commit()


def add_bonus_slots(uid: int, n: int) -> None:
    conn().execute(
        "UPDATE users SET bonus_slots=bonus_slots+? WHERE user_id=?", (n, uid)
    )
    conn().commit()


def set_bonus_slots(uid: int, n: int) -> None:
    conn().execute("UPDATE users SET bonus_slots=? WHERE user_id=?", (n, uid))
    conn().commit()


def get_slot_counts(uid: int) -> tuple[int, int]:
    """(used, max)"""
    row = get_user(uid)
    if not row:
        return 0, config.PLANS["free"]["slots"]
    plan_max = config.PLANS.get(row["plan"], config.PLANS["free"])["slots"]
    total_max = plan_max + (row["bonus_slots"] or 0)
    used = conn().execute(
        "SELECT COUNT(*) FROM bots WHERE owner_id=? AND status!='deleted'", (uid,)
    ).fetchone()[0]
    return used, total_max


def all_users() -> List[sqlite3.Row]:
    return conn().execute(
        "SELECT * FROM users ORDER BY joined_at DESC"
    ).fetchall()


def search_users(query: str) -> List[sqlite3.Row]:
    q = f"%{query}%"
    return conn().execute(
        "SELECT * FROM users WHERE username LIKE ? OR full_name LIKE ? "
        "OR CAST(user_id AS TEXT) LIKE ? LIMIT 20",
        (q, q, q),
    ).fetchall()


def user_stats() -> dict:
    c = conn()
    return {
        "total":   c.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "banned":  c.execute("SELECT COUNT(*) FROM users WHERE is_banned=1").fetchone()[0],
        "premium": c.execute("SELECT COUNT(*) FROM users WHERE plan!='free'").fetchone()[0],
        "today":   c.execute(
            "SELECT COUNT(*) FROM users WHERE date(joined_at)=date('now')"
        ).fetchone()[0],
        "active_7d": c.execute(
            "SELECT COUNT(*) FROM users WHERE last_seen >= datetime('now','-7 days')"
        ).fetchone()[0],
    }


def referral_count(uid: int) -> int:
    return conn().execute(
        "SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (uid,)
    ).fetchone()[0]


def top_referrers(limit: int = 10) -> List[sqlite3.Row]:
    return conn().execute(
        """SELECT u.user_id,u.full_name,u.username,COUNT(r.id) rc
           FROM referrals r JOIN users u ON u.user_id=r.referrer_id
           GROUP BY r.referrer_id ORDER BY rc DESC LIMIT ?""",
        (limit,),
    ).fetchall()


def top_coins(limit: int = 10) -> List[sqlite3.Row]:
    return conn().execute(
        "SELECT user_id,full_name,username,coins FROM users ORDER BY coins DESC LIMIT ?",
        (limit,),
    ).fetchall()


# ─────────────────────────────────────────────────────────────────────
# DAILY / WEEKLY / MONTHLY
# ─────────────────────────────────────────────────────────────────────

def claim_daily(uid: int) -> tuple[bool, int, int, str]:
    """(ok, coins, streak, bonus_msg)"""
    row = get_user(uid)
    if not row:
        return False, 0, 0, ""
    today = date.today().isoformat()
    last  = row["last_daily"]
    streak = row["daily_streak"] or 0

    if last == today:
        return False, 0, streak, ""

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    streak = (streak + 1) if last == yesterday else 1

    streak_bonus = min((streak - 1) * config.DAILY_STREAK_BONUS, config.MAX_STREAK_BONUS)
    earned = config.DAILY_BASE_COINS + streak_bonus
    bonus_msg = ""

    if streak == 7 and not row["weekly_claimed"]:
        earned += config.WEEKLY_BONUS_COINS
        bonus_msg = f"🎉 7-Day Streak Bonus! +{config.WEEKLY_BONUS_COINS} coins!"
        conn().execute("UPDATE users SET weekly_claimed=1 WHERE user_id=?", (uid,))
    elif streak == 30 and not row["monthly_claimed"]:
        earned += config.MONTHLY_BONUS_COINS
        bonus_msg = f"🏆 30-Day Legend Bonus! +{config.MONTHLY_BONUS_COINS} coins!"
        conn().execute("UPDATE users SET monthly_claimed=1 WHERE user_id=?", (uid,))

    _add_coins(uid, earned, f"daily reward streak={streak}")
    conn().execute(
        "UPDATE users SET daily_streak=?,last_daily=? WHERE user_id=?",
        (streak, today, uid),
    )
    conn().commit()
    return True, earned, streak, bonus_msg


# ─────────────────────────────────────────────────────────────────────
# COINS
# ─────────────────────────────────────────────────────────────────────

def _add_coins(uid: int, amount: int, reason: str = "") -> None:
    conn().execute("UPDATE users SET coins=coins+?,total_earned=total_earned+? WHERE user_id=?",
                   (amount, max(amount, 0), uid))
    row = get_user(uid)
    bal = row["coins"] if row else 0
    conn().execute(
        "INSERT INTO coin_tx(user_id,amount,balance,reason) VALUES(?,?,?,?)",
        (uid, amount, bal, reason),
    )


def add_coins(uid: int, amount: int, reason: str = "") -> None:
    _add_coins(uid, amount, reason)
    conn().commit()


def spend_coins(uid: int, amount: int, reason: str = "") -> bool:
    row = get_user(uid)
    if not row or (row["coins"] or 0) < amount:
        return False
    _add_coins(uid, -amount, reason)
    conn().commit()
    return True


def coin_history(uid: int, limit: int = 15) -> List[sqlite3.Row]:
    return conn().execute(
        "SELECT * FROM coin_tx WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (uid, limit),
    ).fetchall()


def economy_stats() -> dict:
    c = conn()
    return {
        "total_coins":    c.execute("SELECT SUM(coins) FROM users").fetchone()[0] or 0,
        "total_earned":   c.execute("SELECT SUM(total_earned) FROM users").fetchone()[0] or 0,
        "tx_count":       c.execute("SELECT COUNT(*) FROM coin_tx").fetchone()[0],
        "slots_bought":   c.execute(
            "SELECT COUNT(*) FROM coin_tx WHERE reason LIKE '%slot%'"
        ).fetchone()[0],
    }


# ─────────────────────────────────────────────────────────────────────
# BOT CRUD
# ─────────────────────────────────────────────────────────────────────

def get_bot(bid: int) -> Optional[sqlite3.Row]:
    return conn().execute("SELECT * FROM bots WHERE bot_id=?", (bid,)).fetchone()


def get_user_bots(uid: int) -> List[sqlite3.Row]:
    return conn().execute(
        "SELECT * FROM bots WHERE owner_id=? AND status!='deleted' ORDER BY bot_id",
        (uid,),
    ).fetchall()


def get_all_active_bots() -> List[sqlite3.Row]:
    return conn().execute(
        "SELECT b.*,u.full_name owner_name FROM bots b "
        "JOIN users u ON u.user_id=b.owner_id "
        "WHERE b.status!='deleted' ORDER BY b.status DESC,b.bot_id"
    ).fetchall()


def create_bot(uid: int, name: str, file_path: str) -> int:
    cur = conn().execute(
        "INSERT INTO bots(owner_id,bot_name,file_path) VALUES(?,?,?)",
        (uid, name, file_path),
    )
    conn().commit()
    return cur.lastrowid


def update_bot_status(bid: int, status: str, pid: Optional[int] = None) -> None:
    now_ts = time.time()
    c = conn()
    if status == "running":
        c.execute(
            "UPDATE bots SET status=?,pid=?,last_started=datetime('now'),start_ts=? WHERE bot_id=?",
            (status, pid, now_ts, bid),
        )
    elif status in ("stopped", "error", "deleted"):
        row = get_bot(bid)
        uptime_add = 0
        if row and row["start_ts"]:
            uptime_add = max(0, int(now_ts - row["start_ts"]))
        c.execute(
            "UPDATE bots SET status=?,pid=NULL,start_ts=NULL,total_uptime=total_uptime+? WHERE bot_id=?",
            (status, uptime_add, bid),
        )
    else:
        c.execute("UPDATE bots SET status=?,pid=? WHERE bot_id=?", (status, pid, bid))
    c.commit()


def update_bot_resources(bid: int, cpu: float, mem_bytes: int) -> None:
    conn().execute(
        "UPDATE bots SET cpu_usage=?,memory_usage=? WHERE bot_id=?",
        (cpu, mem_bytes, bid),
    )
    conn().commit()


def rename_bot(bid: int, name: str) -> None:
    conn().execute("UPDATE bots SET bot_name=? WHERE bot_id=?", (name, bid))
    conn().commit()


def toggle_auto_restart(bid: int) -> bool:
    row = get_bot(bid)
    if not row:
        return False
    new = 0 if row["auto_restart"] else 1
    conn().execute("UPDATE bots SET auto_restart=? WHERE bot_id=?", (new, bid))
    conn().commit()
    return bool(new)


def inc_restart_count(bid: int) -> int:
    conn().execute(
        "UPDATE bots SET restart_count=restart_count+1,total_restarts=total_restarts+1 WHERE bot_id=?",
        (bid,),
    )
    conn().commit()
    return get_bot(bid)["restart_count"]


def inc_crash_count(bid: int) -> None:
    conn().execute("UPDATE bots SET crash_count=crash_count+1 WHERE bot_id=?", (bid,))
    conn().commit()


def reset_restart_count(bid: int) -> None:
    conn().execute("UPDATE bots SET restart_count=0 WHERE bot_id=?", (bid,))
    conn().commit()


def set_bot_schedule(bid: int, start_time: Optional[str], stop_time: Optional[str]) -> None:
    conn().execute(
        "UPDATE bots SET schedule_start=?,schedule_stop=? WHERE bot_id=?",
        (start_time, stop_time, bid),
    )
    conn().commit()


def soft_delete_bot(bid: int) -> None:
    conn().execute("UPDATE bots SET status='deleted',pid=NULL WHERE bot_id=?", (bid,))
    conn().execute("DELETE FROM bot_envvars WHERE bot_id=?", (bid,))
    conn().commit()


def bot_stats() -> dict:
    c = conn()
    return {
        "total":   c.execute("SELECT COUNT(*) FROM bots WHERE status!='deleted'").fetchone()[0],
        "running": c.execute("SELECT COUNT(*) FROM bots WHERE status='running'").fetchone()[0],
        "stopped": c.execute("SELECT COUNT(*) FROM bots WHERE status='stopped'").fetchone()[0],
        "error":   c.execute("SELECT COUNT(*) FROM bots WHERE status='error'").fetchone()[0],
    }


# ─────────────────────────────────────────────────────────────────────
# ENV VARS
# ─────────────────────────────────────────────────────────────────────

def set_env(bid: int, key: str, value: str) -> None:
    conn().execute(
        "INSERT INTO bot_envvars(bot_id,key,value) VALUES(?,?,?) "
        "ON CONFLICT(bot_id,key) DO UPDATE SET value=excluded.value",
        (bid, key, value),
    )
    conn().commit()


def get_envs(bid: int) -> List[sqlite3.Row]:
    return conn().execute(
        "SELECT * FROM bot_envvars WHERE bot_id=? ORDER BY key", (bid,)
    ).fetchall()


def del_env(bid: int, key: str) -> None:
    conn().execute("DELETE FROM bot_envvars WHERE bot_id=? AND key=?", (bid, key))
    conn().commit()


def env_dict(bid: int) -> Dict[str, str]:
    return {r["key"]: r["value"] for r in get_envs(bid)}


# ─────────────────────────────────────────────────────────────────────
# ADMIN LOG & SYSTEM EVENTS
# ─────────────────────────────────────────────────────────────────────

def log_action(admin_id: int, action: str,
               target: Optional[int] = None, detail: str = "") -> None:
    conn().execute(
        "INSERT INTO admin_log(admin_id,action,target_id,detail) VALUES(?,?,?,?)",
        (admin_id, action, target, detail),
    )
    conn().commit()


def get_log(limit: int = 25) -> List[sqlite3.Row]:
    return conn().execute(
        "SELECT * FROM admin_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()


def log_event(event_type: str, detail: str = "") -> None:
    conn().execute(
        "INSERT INTO system_events(event_type,detail) VALUES(?,?)",
        (event_type, detail),
    )
    conn().commit()


def recent_events(limit: int = 20) -> List[sqlite3.Row]:
    return conn().execute(
        "SELECT * FROM system_events ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()


def log_broadcast(admin_id: int, preview: str, sent: int, failed: int, pinned: bool) -> None:
    conn().execute(
        "INSERT INTO broadcasts(admin_id,preview,sent,failed,pinned) VALUES(?,?,?,?,?)",
        (admin_id, preview, sent, failed, int(pinned)),
    )
    conn().commit()


# ─────────────────────────────────────────────────────────────────────
# NOTIFICATIONS
# ─────────────────────────────────────────────────────────────────────

def create_notification(uid: int, type: str, title: str, message: str = "") -> None:
    conn().execute(
        "INSERT INTO notifications(user_id,type,title,message) VALUES(?,?,?,?)",
        (uid, type, title, message),
    )
    conn().commit()


def get_unread_notifications(uid: int) -> List[sqlite3.Row]:
    return conn().execute(
        "SELECT * FROM notifications WHERE user_id=? AND read=0 ORDER BY id DESC",
        (uid,),
    ).fetchall()


def mark_notification_read(nid: int) -> None:
    conn().execute("UPDATE notifications SET read=1 WHERE id=?", (nid,))
    conn().commit()


# ─────────────────────────────────────────────────────────────────────
# API KEYS
# ─────────────────────────────────────────────────────────────────────

def create_api_key(uid: int, key_hash: str, name: str = "", permissions: str = "read") -> None:
    conn().execute(
        "INSERT INTO api_keys(user_id,key_hash,name,permissions) VALUES(?,?,?,?)",
        (uid, key_hash, name, permissions),
    )
    conn().commit()


def get_api_key(key_hash: str) -> Optional[sqlite3.Row]:
    return conn().execute(
        "SELECT * FROM api_keys WHERE key_hash=?", (key_hash,)
    ).fetchone()


def update_api_key_last_used(key_hash: str) -> None:
    conn().execute(
        "UPDATE api_keys SET last_used=datetime('now') WHERE key_hash=?",
        (key_hash,),
    )
    conn().commit()


def delete_api_key(uid: int, key_hash: str) -> None:
    conn().execute(
        "DELETE FROM api_keys WHERE user_id=? AND key_hash=?", (uid, key_hash)
    )
    conn().commit()


# ─────────────────────────────────────────────────────────────────────
# EXPORT FOR WEB API
# ─────────────────────────────────────────────────────────────────────

def export_stats() -> Dict[str, Any]:
    """Export all stats for web admin panel."""
    return {
        "users": user_stats(),
        "bots": bot_stats(),
        "economy": economy_stats(),
        "referrals": conn().execute("SELECT COUNT(*) FROM referrals").fetchone()[0],
        "broadcasts": {
            "count": conn().execute("SELECT COUNT(*) FROM broadcasts").fetchone()[0],
            "sent": conn().execute("SELECT SUM(sent) FROM broadcasts").fetchone()[0] or 0,
        }
    }
