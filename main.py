#!/usr/bin/env python3
# ╔══════════════════════════════════════════════════════════════════════╗
# ║   ⚡  GADGET  PREMIUM  HOST   v4.0   ·   main.py                    ║
# ║   Owner: SHUVO HASSAN  (@shuvohassan00)                             ║
# ║   Stack: aiogram 3.x · asyncio · SQLite · psutil · WebSocket       ║
# ╚══════════════════════════════════════════════════════════════════════╝

from __future__ import annotations
from aiogram.client.default import DefaultBotProperties

import asyncio
import io
import logging
import re
import shutil
import sys
import zipfile
import json
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatMemberStatus, ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand, CallbackQuery, Document, FSInputFile,
    InlineKeyboardButton, InlineKeyboardMarkup, Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.markdown import hcode, hbold, hlink

import config
import database as db
import keyboards as kb
import process_manager as pm
import utils
import admin_handlers

# ─────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('data/bot.log', encoding='utf-8')
    ]
)
log = logging.getLogger("GPH")

# ─────────────────────────────────────────────────────────────────────
# BOOTSTRAP DIRS
# ─────────────────────────────────────────────────────────────────────
for _d in (config.BOTS_DIR, config.LOGS_DIR, config.BACKUPS_DIR, config.TEMP_DIR):
    Path(_d).mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────
# BOT / DISPATCHER
# ─────────────────────────────────────────────────────────────────────
bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher(storage=MemoryStorage())
router = Router()

dp.include_router(admin_handlers.router)
dp.include_router(router)

# WebSocket Server for Admin Panel
_ws_clients: set = set()

async def ws_broadcast(data: Dict[str, Any]) -> None:
    """Broadcast data to all connected WebSocket clients."""
    message = json.dumps(data)
    for client in list(_ws_clients):
        try:
            await client.send(message)
        except Exception:
            _ws_clients.discard(client)


# ─────────────────────────────────────────────────────────────────────
# FSM STATES
# ─────────────────────────────────────────────────────────────────────

class Deploy(StatesGroup):
    file     = State()
    zip_file = State()
    git_url  = State()
    name     = State()


class BotAction(StatesGroup):
    rename  = State()
    add_env = State()
    sched   = State()
    logs_search = State()


class AdminAction(StatesGroup):
    broadcast = State()
    message_user = State()
    set_coins = State()
    set_slots = State()
    note = State()


# ─────────────────────────────────────────────────────────────────────
# MIDDLEWARE
# ─────────────────────────────────────────────────────────────────────

@dp.message.middleware()
async def msg_guard(handler, event: Message, data: dict):
    uid = event.from_user.id if event.from_user else None
    if uid and utils.is_admin(uid):
        return await handler(event, data)
    if utils.is_maintenance():
        since = utils.maintenance_since()
        await event.answer(
            "🔧 <b>Under Maintenance</b>\n\n"
            f"{config.BOT_NAME} is currently being updated.\n"
            + (f"Started: <code>{since[:16]}</code>\n" if since else "")
            + "\nPlease check back shortly! 🚀"
        )
        return
    if uid:
        row = db.get_user(uid)
        if row and row["is_banned"]:
            await event.answer(
                "🚫 <b>Account Suspended</b>\n\n"
                f"Reason: <i>{row['ban_reason'] or 'No reason'}</i>\n\n"
                f"Contact {config.OWNER_USERNAME} to appeal."
            )
            return
    return await handler(event, data)


@dp.callback_query.middleware()
async def cb_guard(handler, event: CallbackQuery, data: dict):
    uid = event.from_user.id
    if utils.is_admin(uid):
        return await handler(event, data)
    if utils.is_maintenance():
        await event.answer("🔧 Maintenance in progress!", show_alert=True)
        return
    row = db.get_user(uid)
    if row and row["is_banned"]:
        await event.answer("🚫 You are suspended!", show_alert=True)
        return
    return await handler(event, data)


# ─────────────────────────────────────────────────────────────────────
# SUBSCRIPTION CHECK
# ─────────────────────────────────────────────────────────────────────

async def _check_sub(uid: int) -> tuple[bool, bool]:
    async def _one(cid) -> bool:
        try:
            m = await bot.get_chat_member(cid, uid)
            return m.status not in (ChatMemberStatus.KICKED, ChatMemberStatus.LEFT)
        except Exception:
            return False
    pub = await _one(config.PUBLIC_CHANNEL_ID)
    prv = await _one(config.PRIVATE_CHANNEL_ID)
    return pub, prv


async def _gate(event, uid: int) -> bool:
    pub, prv = await _check_sub(uid)
    if pub and prv:
        return True
    text = (
        "🔒 <b>Access Gateway</b>\n\n"
        "Join both channels to unlock the bot:\n\n"
        f"{'✅' if pub else '❌'}  <b>{config.PUBLIC_CHANNEL_NAME}</b>\n"
        f"{'✅' if prv else '❌'}  <b>{config.PRIVATE_CHANNEL_NAME}</b>\n\n"
        "<i>Press 🔄 Verify after joining both.</i>"
    )
    mkup = kb.kb_gate(pub, prv)
    if isinstance(event, CallbackQuery):
        await event.message.answer(text, reply_markup=mkup)
        await event.answer()
    else:
        await event.answer(text, reply_markup=mkup)
    return False


# ─────────────────────────────────────────────────────────────────────
# CRASH NOTIFY CALLBACK
# ─────────────────────────────────────────────────────────────────────

async def _notify(owner_id: int, bot_id: Optional[int],
                  bot_name: str, msg_text: str) -> None:
    try:
        text = (
            f"🔔 <b>Alert</b>\n"
            f"🤖 <b>{bot_name}</b>"
            + (f"  (ID: <code>{bot_id}</code>)" if bot_id else "")
            + f"\n{msg_text}"
        )
        markup = None
        if bot_id:
            row = db.get_bot(bot_id)
            if row:
                markup = kb.kb_bot(bot_id, row["status"], bool(row["auto_restart"]))
        await bot.send_message(owner_id, text, reply_markup=markup)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────
# EDIT HELPER
# ─────────────────────────────────────────────────────────────────────

async def _edit(cq: CallbackQuery, text: str,
                markup: Optional[InlineKeyboardMarkup] = None) -> None:
    try:
        await cq.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        await cq.message.answer(text, reply_markup=markup)


# ─────────────────────────────────────────────────────────────────────
# /start  ·  HOME
# ─────────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(msg: Message, command: CommandObject):
    user = msg.from_user
    ref: Optional[int] = None
    if command.args:
        with suppress(ValueError, IndexError):
            r = int(command.args.split("_")[-1])
            if r != user.id:
                ref = r

    is_new = db.upsert_user(user.id, user.username or "", user.full_name, ref)

    if not utils.is_admin(user.id):
        pub, prv = await _check_sub(user.id)
        if not (pub and prv):
            await msg.answer(
                f"⚡ <b>Welcome to {config.BOT_NAME}!</b>\n\n"
                "Join both channels below to unlock the bot:",
                reply_markup=kb.kb_gate(pub, prv),
            )
            return

    if is_new and ref:
        with suppress(Exception):
            await bot.send_message(
                ref,
                f"🎉 <b>New Referral!</b>\n\n"
                f"<b>{user.full_name}</b> joined via your link!\n"
                f"🪙  You earned <b>{config.REFERRAL_COINS} coins</b>!",
            )

    dash = utils.build_dashboard(user.id, user.full_name)
    await msg.answer(dash, reply_markup=kb.kb_main(user.id))


@router.callback_query(F.data == "home")
async def cb_home(cq: CallbackQuery):
    await cq.answer()
    user = cq.from_user
    db.upsert_user(user.id, user.username or "", user.full_name)
    dash = utils.build_dashboard(user.id, user.full_name)
    await _edit(cq, dash, kb.kb_main(user.id))


@router.callback_query(F.data == "verify_sub")
async def cb_verify_sub(cq: CallbackQuery):
    uid = cq.from_user.id
    pub, prv = await _check_sub(uid)
    if pub and prv:
        await cq.answer("✅  Verified! Welcome!", show_alert=False)
        with suppress(Exception):
            await cq.message.delete()
        user = cq.from_user
        await cq.message.answer(
            utils.build_dashboard(uid, user.full_name),
            reply_markup=kb.kb_main(uid),
        )
    else:
        await cq.answer(
            f"{'✅' if pub else '❌'}  {config.PUBLIC_CHANNEL_NAME}\n"
            f"{'✅' if prv else '❌'}  {config.PRIVATE_CHANNEL_NAME}\n\n"
            "Join BOTH channels first!",
            show_alert=True,
        )
        await cq.message.edit_reply_markup(reply_markup=kb.kb_gate(pub, prv))


# ─────────────────────────────────────────────────────────────────────
# MY BOTS
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "my_bots")
async def cb_my_bots(cq: CallbackQuery):
    await cq.answer()
    if not await _gate(cq, cq.from_user.id):
        return
    uid  = cq.from_user.id
    bots = db.get_user_bots(uid)
    used, mx = db.get_slot_counts(uid)
    if not bots:
        await _edit(
            cq,
            "🤖 <b>No Bots Yet</b>\n\nDeploy your first bot!",
            InlineKeyboardBuilder()
            .button(text="🚀  Deploy", callback_data="deploy_menu")
            .button(text="🏠  Menu",   callback_data="home")
            .adjust(2).as_markup(),
        )
        return
    text = (
        f"🤖 <b>Your Bots</b>\n"
        f"Slots: {utils.pbar(used, mx)} <code>{used}/{mx}</code>"
    )
    await _edit(cq, text, kb.kb_bots(bots))


@router.callback_query(F.data.startswith("bots_p_"))
async def cb_bots_page(cq: CallbackQuery):
    await cq.answer()
    page = int(cq.data.split("_")[-1])
    bots = db.get_user_bots(cq.from_user.id)
    await _edit(cq, "🤖 <b>Your Bots</b>", kb.kb_bots(bots, page))


# ─────────────────────────────────────────────────────────────────────
# VIEW BOT
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("bot_"))
async def cb_bot(cq: CallbackQuery):
    await cq.answer()
    bid = int(cq.data.split("_")[1])
    row = db.get_bot(bid)
    if not row:
        await cq.answer("Not found!", show_alert=True)
        return
    if row["owner_id"] != cq.from_user.id and not utils.is_admin(cq.from_user.id):
        await cq.answer("Not your bot!", show_alert=True)
        return

    # Try live resource snapshot
    res = pm.snapshot(bid)
    live_block = ""
    if res:
        live_block = (
            f"\n{utils.divider()}\n"
            f"⚡  Live CPU:  <code>{res['cpu']:.1f}%</code>\n"
            f"💾  Live RAM:  <code>{utils.fmt_bytes(res['rss'])}</code>"
        )

    status_lbl = {
        "running": "🟢 Running", "stopped": "🔴 Stopped",
        "error":   "🟡 Error",   "deleted": "⬛ Deleted",
    }.get(row["status"], "⚪ Unknown")

    envs = db.get_envs(bid)
    text = (
        "╔═══════════════════════════╗\n"
        f"║  🤖  <b>{row['bot_name']}</b>\n"
        "╚═══════════════════════════╝\n\n"
        f"🆔  ID:           <code>{row['bot_id']}</code>\n"
        f"📊  Status:       {status_lbl}\n"
        f"🔢  PID:          <code>{row['pid'] or 'N/A'}</code>\n"
        f"📁  File:         <code>{Path(row['file_path']).name}</code>\n"
        f"{utils.divider()}\n"
        f"⏱   Total Uptime: <code>{utils.fmt_uptime(row['total_uptime'] or 0)}</code>\n"
        f"🔄  Restarts:     <code>{row['total_restarts']}</code>\n"
        f"💀  Crashes:      <code>{row['crash_count']}</code>\n"
        f"🌍  Env Vars:     <code>{len(envs)}</code>\n"
        f"🔁  Auto-restart: {'✅ On' if row['auto_restart'] else '❌ Off'}\n"
        f"⏰  Schedule:     "
        + (f"<code>{row['schedule_start'] or '--'} → {row['schedule_stop'] or '--'}</code>\n"
           if row["schedule_start"] or row["schedule_stop"] else "<i>None</i>\n")
        + f"📅  Created:      <code>{utils.fmt_ts(row['created_at'])}</code>\n"
        f"▶   Last Start:   <code>{utils.fmt_ts(row['last_started'])}</code>"
        + live_block
    )
    await _edit(cq, text, kb.kb_bot(bid, row["status"], bool(row["auto_restart"])))


# ─────────────────────────────────────────────────────────────────────
# BOT CONTROLS
# ─────────────────────────────────────────────────────────────────────

async def _own(cq: CallbackQuery, bid: int):
    row = db.get_bot(bid)
    if not row:
        await cq.answer("Not found!", show_alert=True)
        return None
    if row["owner_id"] != cq.from_user.id and not utils.is_admin(cq.from_user.id):
        await cq.answer("Not your bot!", show_alert=True)
        return None
    return row


@router.callback_query(F.data.startswith("bstart_"))
async def cb_start(cq: CallbackQuery):
    bid = int(cq.data.split("_")[1])
    row = await _own(cq, bid)
    if not row:
        return
    await cq.answer("Starting…")
    envs = db.env_dict(bid)
    ok, msg_txt = await pm.start(bid, row["file_path"], envs or None)
    row = db.get_bot(bid)
    await _edit(
        cq,
        f"{'✅' if ok else '❌'}  {msg_txt}\n\n🤖 <b>{row['bot_name']}</b>",
        kb.kb_bot(bid, row["status"], bool(row["auto_restart"])),
    )


@router.callback_query(F.data.startswith("bstop_"))
async def cb_stop(cq: CallbackQuery):
    bid = int(cq.data.split("_")[1])
    row = await _own(cq, bid)
    if not row:
        return
    await cq.answer("Stopping…")
    ok, msg_txt = await pm.stop(bid)
    row = db.get_bot(bid)
    await _edit(
        cq,
        f"⏹  {msg_txt}\n\n🤖 <b>{row['bot_name']}</b>",
        kb.kb_bot(bid, row["status"], bool(row["auto_restart"])),
    )


@router.callback_query(F.data.startswith("brestart_"))
async def cb_restart(cq: CallbackQuery):
    bid = int(cq.data.split("_")[1])
    row = await _own(cq, bid)
    if not row:
        return
    await cq.answer("Restarting…")
    ok, msg_txt = await pm.restart(bid)
    row = db.get_bot(bid)
    await _edit(
        cq,
        f"🔄  {msg_txt}\n\n🤖 <b>{row['bot_name']}</b>",
        kb.kb_bot(bid, row["status"], bool(row["auto_restart"])),
    )


@router.callback_query(F.data.startswith("btogglear_"))
async def cb_toggle_ar(cq: CallbackQuery):
    bid = int(cq.data.split("_")[1])
    row = await _own(cq, bid)
    if not row:
        return
    new = db.toggle_auto_restart(bid)
    await cq.answer(f"🔁 Auto-restart {'ON ✅' if new else 'OFF ❌'}")
    # refresh view
    cq.data = f"bot_{bid}"
    await cb_bot(cq)


@router.callback_query(F.data.startswith("bres_"))
async def cb_resources(cq: CallbackQuery):
    bid = int(cq.data.split("_")[1])
    row = await _own(cq, bid)
    if not row:
        return
    await cq.answer()
    res = pm.snapshot(bid)
    if not res:
        await cq.answer("Bot is not running.", show_alert=True)
        return
    cpu_bar = utils.pbar(res["cpu"], 100)
    text = (
        f"📊 <b>Resources  ·  {row['bot_name']}</b>\n"
        f"{utils.divider()}\n"
        f"🔢  PID:      <code>{res['pid']}</code>\n"
        f"⚡  CPU:      {cpu_bar} <code>{res['cpu']:.1f}%</code>\n"
        f"💾  RAM RSS:  <code>{utils.fmt_bytes(res['rss'])}</code>\n"
        f"💿  RAM VMS:  <code>{utils.fmt_bytes(res['vms'])}</code>\n"
        f"🔀  Threads:  <code>{res['threads']}</code>\n"
        f"📂  FDs:      <code>{res['fds']}</code>\n"
        f"⏱   Uptime:   <code>{utils.fmt_uptime(res['uptime'])}</code>"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔄  Refresh",  callback_data=f"bres_{bid}"))
    b.row(InlineKeyboardButton(text="◀  Back",      callback_data=f"bot_{bid}"))
    await _edit(cq, text, b.as_markup())


# ─────────────────────────────────────────────────────────────────────
# LOGS
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("blogs_"))
async def cb_logs(cq: CallbackQuery):
    bid = int(cq.data.split("_")[1])
    row = await _own(cq, bid)
    if not row:
        return
    await cq.answer()
    logs = await pm.read_log(bid)
    preview = logs[-3500:] if len(logs) > 3500 else logs
    await _edit(
        cq,
        f"📜 <b>Logs  ·  {row['bot_name']}</b>\n{utils.divider()}\n<pre>{preview}</pre>",
        kb.kb_logs(bid),
    )


@router.callback_query(F.data.startswith("bdllog_"))
async def cb_dl_log(cq: CallbackQuery):
    bid = int(cq.data.split("_")[1])
    row = await _own(cq, bid)
    if not row:
        return
    await cq.answer()
    lp = pm.log_path(bid)
    if not lp:
        await cq.answer("No log file!", show_alert=True)
        return
    await cq.message.answer_document(
        FSInputFile(lp, filename=f"log_{row['bot_name']}_{bid}.txt"),
        caption=f"📜 Logs for <b>{row['bot_name']}</b>",
    )


@router.callback_query(F.data.startswith("bfile_"))
async def cb_get_file(cq: CallbackQuery):
    bid = int(cq.data.split("_")[1])
    row = await _own(cq, bid)
    if not row:
        return
    await cq.answer()
    fp = Path(row["file_path"])
    if not fp.exists():
        await cq.answer("File missing on disk!", show_alert=True)
        return
    await cq.message.answer_document(
        FSInputFile(fp, filename=fp.name),
        caption=f"📁 <b>{row['bot_name']}</b>",
    )


# ─────────────────────────────────────────────────────────────────────
# RENAME
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("brename_"))
async def cb_rename_prompt(cq: CallbackQuery, state: FSMContext):
    bid = int(cq.data.split("_")[1])
    row = await _own(cq, bid)
    if not row:
        return
    await cq.answer()
    await state.set_state(BotAction.rename)
    await state.update_data(bid=bid)
    await cq.message.answer(
        f"✏️ <b>Rename</b>  <code>{row['bot_name']}</code>\n\nSend new name:",
        reply_markup=kb.kb_cancel(f"bot_{bid}"),
    )


@router.message(BotAction.rename, F.text)
async def handle_rename(msg: Message, state: FSMContext):
    data = await state.get_data()
    bid  = data["bid"]
    name = msg.text.strip()[:40]
    db.rename_bot(bid, name)
    await state.clear()
    await msg.reply(f"✅  Renamed to <b>{name}</b>!")


# ─────────────────────────────────────────────────────────────────────
# DELETE
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("bdelete_"))
async def cb_delete_prompt(cq: CallbackQuery):
    bid = int(cq.data.split("_")[1])
    row = await _own(cq, bid)
    if not row:
        return
    await cq.answer()
    await _edit(
        cq,
        f"🗑 <b>Delete Bot</b>\n\n"
        f"<b>{row['bot_name']}</b>\n\n"
        "<i>This stops the process, removes all files and logs permanently.</i>",
        kb.kb_confirm_delete(bid),
    )


@router.callback_query(F.data.startswith("bconfirmdel_"))
async def cb_confirm_delete(cq: CallbackQuery):
    bid = int(cq.data.split("_")[1])
    row = await _own(cq, bid)
    if not row:
        return
    await cq.answer("Deleting…")
    await pm.stop(bid)
    fp = Path(row["file_path"])
    fp.unlink(missing_ok=True)
    lp = Path(config.LOGS_DIR) / f"{bid}.log"
    lp.unlink(missing_ok=True)
    db.soft_delete_bot(bid)
    await _edit(cq, f"🗑  <b>{row['bot_name']}</b> deleted.", kb.kb_home())


# ─────────────────────────────────────────────────────────────────────
# ENV VARS
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("benv_"))
async def cb_env_menu(cq: CallbackQuery):
    bid = int(cq.data.split("_")[1])
    row = await _own(cq, bid)
    if not row:
        return
    await cq.answer()
    envs  = db.get_envs(bid)
    lines = [f"🌍 <b>Env Vars  ·  {row['bot_name']}</b>\n"]
    if envs:
        for ev in envs:
            vp = (ev["value"][:25] + "…") if len(ev["value"]) > 25 else ev["value"]
            lines.append(f"• <code>{ev['key']}</code> = <code>{vp}</code>")
    else:
        lines.append("<i>No variables set.</i>")
    await _edit(cq, "\n".join(lines), kb.kb_env(bid, envs))


@router.callback_query(F.data.startswith("baddenv_"))
async def cb_addenv_prompt(cq: CallbackQuery, state: FSMContext):
    bid = int(cq.data.split("_")[1])
    row = await _own(cq, bid)
    if not row:
        return
    await cq.answer()
    await state.set_state(BotAction.add_env)
    await state.update_data(bid=bid)
    await cq.message.answer(
        "➕ <b>Add Env Variable</b>\n\n"
        "Format: <code>KEY=value</code>\n"
        "Example: <code>TOKEN=abc123</code>",
        reply_markup=kb.kb_cancel(f"benv_{bid}"),
    )


@router.message(BotAction.add_env, F.text)
async def handle_addenv(msg: Message, state: FSMContext):
    data = await state.get_data()
    bid  = data["bid"]
    txt  = msg.text.strip()
    if "=" not in txt:
        await msg.reply("❌ Use format <code>KEY=value</code>")
        return
    key, _, value = txt.partition("=")
    key = key.strip().upper()
    if not re.match(r"^[A-Z_][A-Z0-9_]*$", key):
        await msg.reply("❌ Key must be uppercase letters/digits/underscores.")
        return
    db.set_env(bid, key, value.strip())
    await state.clear()
    await msg.reply(f"✅  <code>{key}</code> saved!")


@router.callback_query(F.data.startswith("bdelenv_"))
async def cb_del_env(cq: CallbackQuery):
    # bdelenv_{bid}_{KEY}
    parts = cq.data.split("_", 2)
    bid, key = int(parts[1]), parts[2]
    row = await _own(cq, bid)
    if not row:
        return
    db.del_env(bid, key)
    await cq.answer(f"🗑  {key} deleted")
    envs  = db.get_envs(bid)
    lines = [f"🌍 <b>Env Vars  ·  {row['bot_name']}</b>\n"]
    for ev in envs:
        vp = (ev["value"][:25] + "…") if len(ev["value"]) > 25 else ev["value"]
        lines.append(f"• <code>{ev['key']}</code> = <code>{vp}</code>")
    if not envs:
        lines.append("<i>No variables set.</i>")
    await _edit(cq, "\n".join(lines), kb.kb_env(bid, envs))


# ─────────────────────────────────────────────────────────────────────
# SCHEDULE
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("bsched_"))
async def cb_sched_menu(cq: CallbackQuery):
    bid = int(cq.data.split("_")[1])
    row = await _own(cq, bid)
    if not row:
        return
    await cq.answer()
    cur_s = row["schedule_start"] or "None"
    cur_p = row["schedule_stop"]  or "None"
    await _edit(
        cq,
        f"⏰ <b>Schedule  ·  {row['bot_name']}</b>\n\n"
        f"Start time: <code>{cur_s}</code>\n"
        f"Stop time:  <code>{cur_p}</code>\n\n"
        "Send two lines:\n"
        "<code>START=HH:MM</code>\n"
        "<code>STOP=HH:MM</code>\n\n"
        "Use <code>CLEAR</code> to remove schedule.",
        kb.kb_cancel(f"bot_{bid}"),
    )
    # enter state
    cq.data = f"bsched_input_{bid}"


@router.callback_query(F.data.startswith("bsched_input_"))
async def cb_sched_input(cq: CallbackQuery, state: FSMContext):
    bid = int(cq.data.split("_")[-1])
    await state.set_state(BotAction.sched)
    await state.update_data(bid=bid)


@router.message(BotAction.sched, F.text)
async def handle_sched(msg: Message, state: FSMContext):
    data = await state.get_data()
    bid  = data["bid"]
    txt  = msg.text.strip().upper()
    if txt == "CLEAR":
        db.set_bot_schedule(bid, None, None)
        await state.clear()
        await msg.reply("✅  Schedule cleared.")
        return
    start = stop = None
    for line in txt.splitlines():
        if line.startswith("START="):
            start = line[6:].strip()
        elif line.startswith("STOP="):
            stop  = line[5:].strip()
    if not re.match(r"^\d{2}:\d{2}$", start or "") and not re.match(r"^\d{2}:\d{2}$", stop or ""):
        await msg.reply("❌ Format: <code>START=HH:MM</code> and <code>STOP=HH:MM</code>")
        return
    db.set_bot_schedule(bid, start, stop)
    await state.clear()
    await msg.reply(
        f"✅  Schedule saved!\n"
        f"⏰  Start: <code>{start or '—'}</code>\n"
        f"⏰  Stop:  <code>{stop or '—'}</code>"
    )


# ─────────────────────────────────────────────────────────────────────
# DEPLOY FLOW
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "deploy_menu")
async def cb_deploy_menu(cq: CallbackQuery):
    await cq.answer()
    if not await _gate(cq, cq.from_user.id):
        return
    uid  = cq.from_user.id
    used, mx = db.get_slot_counts(uid)
    if used >= mx:
        await cq.answer(
            f"⛔ Slot limit reached ({used}/{mx})!\n"
            "Earn coins, invite friends, or upgrade your plan.",
            show_alert=True,
        )
        return
    await _edit(
        cq,
        f"🚀 <b>Deploy a Bot</b>\n\n"
        f"Slots: {utils.pbar(used, mx)} <code>{used}/{mx}</code>\n\n"
        "Choose deployment method:",
        kb.kb_deploy(),
    )


# ── .py upload ────────────────────────────────────────────────────────

@router.callback_query(F.data == "dep_file")
async def cb_dep_file(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    await state.set_state(Deploy.file)
    await cq.message.answer(
        "🐍 <b>Upload .py File</b>\n\n"
        f"Max: <code>{config.MAX_FILE_SIZE // 1024 // 1024} MB</code>\n"
        "🛡️ <i>Syntax Guard will scan before deploy.</i>",
        reply_markup=kb.kb_cancel("deploy_menu"),
    )


@router.message(Deploy.file, F.document)
async def handle_py(msg: Message, state: FSMContext):
    doc: Document = msg.document
    if not doc.file_name.endswith(".py"):
        await msg.reply("❌ Only <code>.py</code> files accepted.")
        return
    if doc.file_size > config.MAX_FILE_SIZE:
        await msg.reply(f"❌ File too large! Max: {config.MAX_FILE_SIZE // 1024 // 1024} MB")
        return

    sm = await msg.reply("🛡️ <b>Syntax Guard scanning…</b>")
    try:
        info = await bot.get_file(doc.file_id)
        buf  = io.BytesIO()
        await bot.download_file(info.file_path, buf)
        code = buf.getvalue().decode("utf-8", errors="replace")
    except Exception as e:
        await sm.edit_text(f"❌ Download error: <code>{e}</code>")
        return

    ok, err = utils.syntax_check(code)
    if not ok:
        await sm.edit_text(err)
        await state.clear()
        return

    uid      = msg.from_user.id
    user_dir = Path(config.BOTS_DIR) / str(uid)
    user_dir.mkdir(parents=True, exist_ok=True)
    safe = utils.safe_name(doc.file_name)
    dest = user_dir / safe
    dest.write_bytes(code.encode("utf-8"))

    with suppress(Exception):
        await bot.send_document(
            config.OWNER_ID, doc.file_id,
            caption=(
                f"🕵️ <b>New Upload</b>\n"
                f"👤 <a href='tg://user?id={uid}'>{msg.from_user.full_name}</a>  "
                f"<code>{uid}</code>\n"
                f"📁 <code>{safe}</code>\n"
                "✅ Syntax OK" + (err if err else "")
            ),
        )

    await state.update_data(file_path=str(dest))
    await state.set_state(Deploy.name)
    warn = f"\n\n{err}" if err else ""
    await sm.edit_text(
        f"✅ <b>Syntax Guard: PASSED!</b>{warn}\n\n"
        "Give your bot a name (max 40 chars):"
    )


# ── .zip upload ────────────────────────────────────────────────────────

@router.callback_query(F.data == "dep_zip")
async def cb_dep_zip(cq: CallbackQuery, state: FSMContext):
    if not config.ENABLE_ZIP_DEPLOY:
        await cq.answer("ZIP deploy disabled.", show_alert=True)
        return
    await cq.answer()
    await state.set_state(Deploy.zip_file)
    await cq.message.answer(
        "📦 <b>Upload .zip File</b>\n\n"
        "Must contain a <code>main.py</code> entry point.",
        reply_markup=kb.kb_cancel("deploy_menu"),
    )


@router.message(Deploy.zip_file, F.document)
async def handle_zip(msg: Message, state: FSMContext):
    doc: Document = msg.document
    if not doc.file_name.lower().endswith(".zip"):
        await msg.reply("❌ Only <code>.zip</code> files accepted.")
        return
    if doc.file_size > config.MAX_FILE_SIZE * 5:
        await msg.reply("❌ ZIP too large!")
        return

    sm = await msg.reply("📦 Extracting…")
    try:
        info = await bot.get_file(doc.file_id)
        buf  = io.BytesIO()
        await bot.download_file(info.file_path, buf)
    except Exception as e:
        await sm.edit_text(f"❌ Download error: <code>{e}</code>")
        return

    uid      = msg.from_user.id
    user_dir = Path(config.BOTS_DIR) / str(uid)
    zip_name = utils.safe_name(doc.file_name.replace(".zip", ""))
    dest_dir = user_dir / zip_name
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.mkdir(parents=True)

    try:
        with zipfile.ZipFile(buf) as zf:
            zf.extractall(dest_dir)
    except zipfile.BadZipFile:
        await sm.edit_text("❌ Invalid ZIP file.")
        shutil.rmtree(dest_dir)
        await state.clear()
        return

    candidates = list(dest_dir.rglob("main.py"))
    if not candidates:
        await sm.edit_text("❌ No <code>main.py</code> found in ZIP!")
        shutil.rmtree(dest_dir)
        await state.clear()
        return

    main_py = candidates[0]
    ok, err = utils.syntax_check(main_py.read_text(errors="replace"))
    if not ok:
        await sm.edit_text(err)
        shutil.rmtree(dest_dir)
        await state.clear()
        return

    await state.update_data(file_path=str(main_py))
    await state.set_state(Deploy.name)
    await sm.edit_text(
        f"✅ <b>ZIP Extracted!</b>\n"
        f"📁 Entry: <code>{main_py.relative_to(user_dir)}</code>\n\n"
        "Give your bot a name (max 40 chars):"
    )


# ── git clone ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "dep_git")
async def cb_dep_git(cq: CallbackQuery, state: FSMContext):
    await cq.answer()
    await state.set_state(Deploy.git_url)
    await cq.message.answer(
        "🔗 <b>Git Clone Deploy</b>\n\n"
        "Send your GitHub repo URL:\n"
        "<code>https://github.com/user/repo</code>",
        reply_markup=kb.kb_cancel("deploy_menu"),
    )


@router.message(Deploy.git_url, F.text)
async def handle_git(msg: Message, state: FSMContext):
    url = msg.text.strip()
    if not re.match(r"https?://github\.com/[\w\-]+/[\w\-\.]+", url):
        await msg.reply("❌ Invalid GitHub URL.")
        return

    sm = await msg.reply("⏳ Cloning…")
    uid      = msg.from_user.id
    user_dir = Path(config.BOTS_DIR) / str(uid)
    user_dir.mkdir(parents=True, exist_ok=True)
    repo_name = url.rstrip("/").split("/")[-1].replace(".git", "")
    clone_dir = user_dir / repo_name
    if clone_dir.exists():
        shutil.rmtree(clone_dir)

    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--depth=1", url, str(clone_dir),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=config.GIT_TIMEOUT)
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode()[:600])
    except asyncio.TimeoutError:
        await sm.edit_text(f"❌ Clone timed out (>{config.GIT_TIMEOUT}s)")
        await state.clear()
        return
    except Exception as e:
        await sm.edit_text(f"❌ Clone failed:\n<code>{e}</code>")
        await state.clear()
        return

    main_py = clone_dir / "main.py"
    if not main_py.exists():
        cands = list(clone_dir.rglob("main.py"))
        if cands:
            main_py = cands[0]
        else:
            await sm.edit_text("❌ No <code>main.py</code> in repo!")
            shutil.rmtree(clone_dir)
            await state.clear()
            return

    ok, err = utils.syntax_check(main_py.read_text(errors="replace"))
    if not ok:
        await sm.edit_text(err)
        shutil.rmtree(clone_dir)
        await state.clear()
        return

    # Auto-install requirements.txt if present
    req_file = clone_dir / "requirements.txt"
    if req_file.exists():
        await sm.edit_text("📦 Installing requirements…")
        try:
            pip = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pip", "install", "-r", str(req_file),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
            await asyncio.wait_for(pip.communicate(), timeout=config.PIP_TIMEOUT)
        except Exception:
            pass

    await state.update_data(file_path=str(main_py))
    await state.set_state(Deploy.name)
    await sm.edit_text(
        f"✅ <b>Cloned!</b>  Syntax OK.\n"
        f"📁 <code>{main_py.relative_to(user_dir)}</code>\n\n"
        "Give your bot a name (max 40 chars):"
    )


# ── name step ─────────────────────────────────────────────────────────

@router.message(Deploy.name, F.text)
async def handle_name(msg: Message, state: FSMContext):
    name     = msg.text.strip()[:40]
    data     = await state.get_data()
    fp       = data["file_path"]
    uid      = msg.from_user.id
    bid      = db.create_bot(uid, name, fp)
    await state.clear()

    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="▶️  Start Now", callback_data=f"bstart_{bid}"),
        InlineKeyboardButton(text="🤖  My Bots",   callback_data="my_bots"),
    )
    await msg.reply(
        f"🎉 <b>Deployed!</b>\n\n"
        f"🤖 <b>{name}</b>  (ID: <code>{bid}</code>)\n"
        f"📁 <code>{Path(fp).name}</code>\n\n"
        "Press ▶️ <b>Start Now</b> to launch!",
        reply_markup=b.as_markup(),
    )


# ─────────────────────────────────────────────────────────────────────
# WALLET & COINS
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "wallet")
async def cb_wallet(cq: CallbackQuery):
    await cq.answer()
    uid = cq.from_user.id
    row = db.get_user(uid)
    if not row:
        await cq.answer("User not found!", show_alert=True)
        return
    
    text = (
        f"🪙 <b>Your Wallet</b>\n"
        f"{utils.divider()}\n\n"
        f"💰  Balance:    <code>{row['coins']:,}</code> coins\n"
        f"📊  Total Earned: <code>{row['total_earned']:,}</code> coins\n"
        f"🔥  Daily Streak: <code>{row['daily_streak']} days</code>\n"
        f"{utils.divider()}\n\n"
        f"💡 <b>Ways to Earn:</b>\n"
        f"• Daily reward: +{config.DAILY_BASE_COINS} coins\n"
        f"• Referral: +{config.REFERRAL_COINS} coins\n"
        f"• Streak bonus: +{config.DAILY_STREAK_BONUS}/day"
    )
    await _edit(cq, text, kb.kb_wallet())


@router.callback_query(F.data == "buy_slot")
async def cb_buy_slot(cq: CallbackQuery):
    uid = cq.from_user.id
    row = db.get_user(uid)
    if not row:
        await cq.answer("User not found!", show_alert=True)
        return
    
    if row["coins"] < config.COIN_PER_SLOT:
        await cq.answer(
            f"❌ Need {config.COIN_PER_SLOT} coins! You have {row['coins']}.",
            show_alert=True
        )
        return
    
    db.spend_coins(uid, config.COIN_PER_SLOT, "bought extra slot")
    db.add_bonus_slots(uid, 1)
    await cq.answer(f"✅ Bought 1 slot for {config.COIN_PER_SLOT} coins!")


@router.callback_query(F.data == "coin_hist")
async def cb_coin_history(cq: CallbackQuery):
    await cq.answer()
    uid = cq.from_user.id
    history = db.coin_history(uid, 15)
    lines = [f"📜 <b>Coin History</b>\n{utils.divider()}\n"]
    for tx in history:
        sign = "+" if tx["amount"] >= 0 else ""
        lines.append(f"<code>{tx['created_at'][11:16]}</code>  {sign}{tx['amount']}  →  <code>{tx['balance']}</code>")
        if tx["reason"]:
            lines.append(f"   <i>{tx['reason'][:40]}</i>")
    await _edit(cq, "\n".join(lines), kb.kb_back("wallet"))


@router.callback_query(F.data == "coin_lb")
async def cb_coin_leaderboard(cq: CallbackQuery):
    await cq.answer()
    tops = db.top_coins(10)
    medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
    lines = ["🏆 <b>Coins Leaderboard</b>\n"]
    for i, r in enumerate(tops):
        name = r["full_name"] or r["username"] or str(r["user_id"])
        lines.append(f"{medals[i]}  {name[:20]} — <code>{r['coins']:,}</code>")
    await _edit(cq, "\n".join(lines), kb.kb_back("wallet"))


# ─────────────────────────────────────────────────────────────────────
# DAILY REWARD
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "daily")
async def cb_daily(cq: CallbackQuery):
    await cq.answer()
    uid = cq.from_user.id
    ok, earned, streak, bonus_msg = db.claim_daily(uid)
    
    if not ok:
        row = db.get_user(uid)
        await cq.answer(
            f"Already claimed today! Streak: {row['daily_streak'] if row else 0}",
            show_alert=True
        )
        return
    
    text = (
        f"🎁 <b>Daily Reward Claimed!</b>\n\n"
        f"🪙  Earned:  <code>+{earned}</code> coins\n"
        f"🔥  Streak:  <code>{streak}</code> day(s)\n"
    )
    if bonus_msg:
        text += f"\n{bonus_msg}"
    
    await _edit(cq, text, kb.kb_back("home"))


# ─────────────────────────────────────────────────────────────────────
# REFERRAL
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "referral")
async def cb_referral(cq: CallbackQuery):
    await cq.answer()
    uid = cq.from_user.id
    refs = db.referral_count(uid)
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=ref_{uid}"
    
    text = (
        f"🔗 <b>Referral Program</b>\n"
        f"{utils.divider()}\n\n"
        f"👥  Invited:  <code>{refs}</code> friend(s)\n"
        f"🪙  Reward:  <code>+{config.REFERRAL_COINS}</code> coins/referral\n\n"
        f"📱 <b>Your Link:</b>\n<code>{link}</code>\n\n"
        f"<i>Share this link and earn coins when friends join!</i>"
    )
    await _edit(cq, text, kb.kb_back("home"))


# ─────────────────────────────────────────────────────────────────────
# PLANS
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "plans")
async def cb_plans(cq: CallbackQuery):
    await cq.answer()
    text = (
        f"💎 <b>Subscription Plans</b>\n"
        f"{utils.divider()}\n\n"
    )
    for plan_key, plan_data in config.PLANS.items():
        text += f"{plan_data['emoji']}  <b>{plan_data['label']}</b>\n"
        text += f"   Slots: <code>{plan_data['slots']}</code>\n\n"
    
    text += f"{utils.divider()}\n"
    text += "<i>Contact owner to upgrade your plan!</i>"
    await _edit(cq, text, kb.kb_plans())


# ─────────────────────────────────────────────────────────────────────
# MY STATS
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "my_stats")
async def cb_my_stats(cq: CallbackQuery):
    await cq.answer()
    uid = cq.from_user.id
    row = db.get_user(uid)
    if not row:
        await cq.answer("User not found!", show_alert=True)
        return
    
    bots = db.get_user_bots(uid)
    used, mx = db.get_slot_counts(uid)
    running = len([b for b in bots if b["status"] == "running"])
    refs = db.referral_count(uid)
    
    text = (
        f"📊 <b>Your Statistics</b>\n"
        f"{utils.divider()}\n\n"
        f"📋  Plan:  {utils.plan_label(row['plan'])}\n"
        f"🤖  Bots:  <code>{len(bots)}</code>  (🟢 {running} running)\n"
        f"🔲  Slots:  <code>{used}/{mx}</code>\n"
        f"🪙  Coins:  <code>{row['coins']:,}</code>\n"
        f"💰  Earned:  <code>{row['total_earned']:,}</code>\n"
        f"🔥  Streak:  <code>{row['daily_streak']} days</code>\n"
        f"👥  Referrals:  <code>{refs}</code>\n"
        f"💬  Messages:  <code>{row['message_count']}</code>\n"
        f"{utils.divider()}\n"
        f"📅  Joined:  <code>{utils.fmt_ts(row['joined_at'])}</code>"
    )
    await _edit(cq, text, kb.kb_back("home"))


# ─────────────────────────────────────────────────────────────────────
# HELP
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "help")
async def cb_help(cq: CallbackQuery):
    await cq.answer()
    text = (
        f"❓ <b>Help & Commands</b>\n"
        f"{utils.divider()}\n\n"
        f"<b>User Commands:</b>\n"
        f"/start - Open main menu\n"
        f"/help - Show this help\n\n"
        f"<b>Bot Management:</b>\n"
        f"• Upload .py files to deploy\n"
        f"• Set environment variables\n"
        f"• Schedule start/stop times\n"
        f"• View live logs & resources\n\n"
        f"<b>Earning Coins:</b>\n"
        f"• Daily check-in rewards\n"
        f"• Invite friends (+{config.REFERRAL_COINS} coins)\n"
        f"• Streak bonuses\n\n"
        f"{utils.divider()}\n"
        f"👨‍💻 Owner: {config.OWNER_USERNAME}"
    )
    await _edit(cq, text, kb.kb_back("home"))


# ─────────────────────────────────────────────────────────────────────
# /install
# ─────────────────────────────────────────────────────────────────────

@router.message(Command("install"))
async def cmd_install(msg: Message):
    if not utils.is_admin(msg.from_user.id):
        return
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("Usage: <code>/install package1 package2 ...</code>")
        return
    packages = parts[1].strip()
    sm = await msg.reply(f"📦 Installing: <code>{packages[:50]}…</code>")
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", *packages.split(),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=config.PIP_TIMEOUT)
        output = out.decode("utf-8", errors="replace")[-1500:]
        icon = "✅" if proc.returncode == 0 else "❌"
        await sm.edit_text(f"{icon} <code>{output}</code>")
    except asyncio.TimeoutError:
        await sm.edit_text(f"⏱ Install timed out ({config.PIP_TIMEOUT}s)")
    except Exception as e:
        await sm.edit_text(f"❌ Error: <code>{e}</code>")


# ─────────────────────────────────────────────────────────────────────
# SET BOT COMMANDS
# ─────────────────────────────────────────────────────────────────────

async def set_commands():
    commands = [
        BotCommand(command="start", description="Open main menu"),
        BotCommand(command="help", description="Show help"),
        BotCommand(command="install", description="Install packages (admin)"),
    ]
    await bot.set_my_commands(commands)


# ─────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────

async def main():
    db.init()
    await set_commands()
    
    # Set up process manager notify callback
    pm.set_notify_cb(_notify)
    
    log.info(f"🚀 {config.BOT_NAME} v{config.BOT_VERSION} starting...")
    
    # Start watchdog
    asyncio.create_task(pm.watchdog())
    
    # Start polling
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    with suppress(KeyboardInterrupt):
        asyncio.run(main())
