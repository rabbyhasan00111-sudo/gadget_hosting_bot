# ╔══════════════════════════════════════════════════════════════════════╗
# ║   ⚡ GADGET PREMIUM HOST  v4.0  ·  config.py                        ║
# ║   Owner : SHUVO HASSAN  (@shuvohassan00)                            ║
# ╚══════════════════════════════════════════════════════════════════════╝

import os

# ── IDENTITY ──────────────────────────────────────────────────────────
BOT_TOKEN       = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
BOT_NAME        = "GADGET PREMIUM HOST"
BOT_VERSION     = "4.0"
BOT_USERNAME    = "gadget_hosting_bot"   # set after @BotFather

# ── OWNER ─────────────────────────────────────────────────────────────
OWNER_ID        = 7857957075
OWNER_USERNAME  = "@shuvohassan00"

# ── CO-ADMINS (partial admin rights, no /exec) ────────────────────────
CO_ADMINS: list[int] = []              # e.g. [111222, 333444]

# ── FORCE SUBSCRIBE ───────────────────────────────────────────────────
PUBLIC_CHANNEL_ID    = "@gadgetpremiumzone"
PUBLIC_CHANNEL_LINK  = "https://t.me/gadgetpremiumzone"
PUBLIC_CHANNEL_NAME  = "Gadget Premium Zone"

PRIVATE_CHANNEL_ID   = -1002429023073   # ← replace with real numeric ID
PRIVATE_CHANNEL_LINK = "https://t.me/+HSqmdVuHFr84MzRl"
PRIVATE_CHANNEL_NAME = "Gadget VIP Lounge"

# ── STORAGE PATHS ─────────────────────────────────────────────────────
DB_PATH         = "data/gadget.db"
BOTS_DIR        = "data/user_bots"
LOGS_DIR        = "data/logs"
BACKUPS_DIR     = "data/backups"
TEMP_DIR        = "data/temp"
MAX_FILE_SIZE   = 10 * 1024 * 1024     # 10 MB

# ── PLANS ─────────────────────────────────────────────────────────────
PLANS: dict[str, dict] = {
    "free":     {"slots": 1,   "label": "🆓 Free",    "emoji": "🆓"},
    "starter":  {"slots": 3,   "label": "⭐ Starter",  "emoji": "⭐"},
    "pro":      {"slots": 8,   "label": "🔥 Pro",      "emoji": "🔥"},
    "elite":    {"slots": 20,  "label": "💎 Elite",    "emoji": "💎"},
    "ultimate": {"slots": 999, "label": "👑 Ultimate", "emoji": "👑"},
}

# ── ECONOMY ───────────────────────────────────────────────────────────
REFERRAL_COINS       = 75
DAILY_BASE_COINS     = 25
DAILY_STREAK_BONUS   = 5         # extra coins per streak day
MAX_STREAK_BONUS     = 50        # cap bonus at this
COIN_PER_SLOT        = 150
WEEKLY_BONUS_COINS   = 200       # bonus at 7-day streak
MONTHLY_BONUS_COINS  = 1000      # bonus at 30-day streak

# ── PROCESS MANAGEMENT ────────────────────────────────────────────────
EXEC_TIMEOUT        = 30
GIT_TIMEOUT         = 120
PIP_TIMEOUT         = 180
MAX_AUTO_RESTART    = 5
RESTART_COOLDOWN    = 90         # seconds
LOG_TAIL_BYTES      = 20480
MAX_LOG_LINES       = 100
WATCHDOG_INTERVAL   = 15         # seconds

# ── RATE LIMITS ───────────────────────────────────────────────────────
BROADCAST_DELAY     = 0.035      # between messages
USER_CMD_COOLDOWN   = 2          # seconds between user commands

# ── ALERTS ────────────────────────────────────────────────────────────
CPU_ALERT_PCT       = 88.0
RAM_ALERT_PCT       = 88.0
DISK_ALERT_PCT      = 90.0
ALERT_COOLDOWN      = 600        # 10 min between same alert type

# ── FEATURES ──────────────────────────────────────────────────────────
ENABLE_ZIP_DEPLOY      = True
ENABLE_AUTO_RESTART    = True
ENABLE_COINS           = True
ENABLE_DAILY           = True
ENABLE_SCHEDULED_BOTS  = True
MAINTENANCE_FILE       = "data/.maintenance"

# ── WEB ADMIN PANEL ───────────────────────────────────────────────────
WEB_ADMIN_ENABLED      = True
WEB_ADMIN_PORT         = 8080
WEB_ADMIN_SECRET       = "your-secret-key-change-this"

# ── SECURITY ──────────────────────────────────────────────────────────
MAX_BOTS_PER_USER      = 50
MAX_ENV_VARS_PER_BOT   = 20
BAN_MESSAGE            = "Your account has been suspended. Contact support for assistance."
