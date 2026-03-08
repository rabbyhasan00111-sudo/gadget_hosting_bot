# ╔══════════════════════════════════════════════════════════════════════╗
# ║   ⚡ GADGET PREMIUM HOST  v4.0  ·  admin_handlers.py                ║
# ╚══════════════════════════════════════════════════════════════════════╝

from __future__ import annotations

import asyncio
import functools
import shutil
import time
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Optional

import psutil

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery, FSInputFile, InlineKeyboardButton, Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
import database as db
import keyboards as kb
import process_manager as pm
import utils

router = Router()


# ─────────────────────────────────────────────────────────────────────
# STATES
# ─────────────────────────────────────────────────────────────────────

class AdminState(StatesGroup):
    note        = State()
    give_coins  = State()
    give_slots  = State()
    send_msg    = State()
    exec_cmd    = State()
    broadcast   = State()


# ─────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────

async def _edit(cq: CallbackQuery, text: str, markup=None) -> None:
    try:
        await cq.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        await cq.message.answer(text, reply_markup=markup)


def _require_admin(func):
    """Admin-only guard for CallbackQuery handlers."""
    @functools.wraps(func)
    async def _wrap(cq: CallbackQuery, **kwargs):
        if not utils.is_admin(cq.from_user.id):
            await cq.answer("🚫  Admin only!", show_alert=True)
            return
        return await func(cq, **kwargs)
    return _wrap


def _require_owner(func):
    """Owner-only guard for Message handlers."""
    @functools.wraps(func)
    async def _wrap(msg: Message, **kwargs):
        if not utils.is_owner(msg.from_user.id):
            await msg.reply("🚫  <b>Owner only.</b>")
            return
        return await func(msg, **kwargs)
    return _wrap


# ─────────────────────────────────────────────────────────────────────
# ADMIN HOME
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_home")
async def cb_admin_home(cq: CallbackQuery):
    if not utils.is_admin(cq.from_user.id):
        await cq.answer("🚫  Admin only!", show_alert=True)
        return
    await cq.answer()
    await _edit(cq, _admin_home_text(), kb.kb_admin())


def _admin_home_text() -> str:
    us = db.user_stats()
    bs = db.bot_stats()
    cpu = psutil.cpu_percent()
    ram = psutil.virtual_memory().percent
    maint = "🔒 ON" if utils.is_maintenance() else "🔓 OFF"
    return (
        "╔══════════════════════════════════╗\n"
        "║  👑  GOD MODE  ·  ADMIN PANEL    ║\n"
        "╚══════════════════════════════════╝\n\n"
        f"👤  <b>{config.BOT_NAME}</b>  v{config.BOT_VERSION}\n"
        f"🔧  Maintenance: {maint}\n\n"
        f"{utils.divider()}\n"
        f"👥  Users:      <code>{us['total']}</code>  "
        f"(+{us['today']} today · {us['active_7d']} active 7d)\n"
        f"💎  Premium:    <code>{us['premium']}</code>\n"
        f"🚫  Banned:     <code>{us['banned']}</code>\n"
        f"{utils.divider()}\n"
        f"🤖  Bots:       <code>{bs['total']}</code> total\n"
        f"🟢  Running:    <code>{bs['running']}</code>\n"
        f"🔴  Stopped:    <code>{bs['stopped']}</code>\n"
        f"🟡  Error:      <code>{bs['error']}</code>\n"
        f"{utils.divider()}\n"
        f"⚙️   CPU:        <code>{cpu:.1f}%</code>\n"
        f"💾  RAM:        <code>{ram:.1f}%</code>\n"
        f"{utils.divider()}"
    )


# ─────────────────────────────────────────────────────────────────────
# /server
# ─────────────────────────────────────────────────────────────────────

@router.message(Command("server"))
async def cmd_server(msg: Message):
    if not utils.is_admin(msg.from_user.id):
        return
    await msg.reply(_server_text(), reply_markup=_server_kb())


@router.callback_query(F.data == "adm_server")
@_require_admin
async def cb_server(cq: CallbackQuery):
    await cq.answer("Refreshing…")
    await _edit(cq, _server_text(), _server_kb())


def _server_text() -> str:
    stats = pm.get_system_stats()
    cpu_bar  = utils.pbar(stats["cpu"], 100)
    mem_bar  = utils.pbar(stats["memory"]["percent"], 100)
    dsk_bar  = utils.pbar(stats["disk"]["percent"], 100)

    temp_line = ""
    if stats["temperature"]:
        temp_line = f"🌡️  Temp:       <code>{stats['temperature']:.1f}°C</code>\n"

    return (
        "╔════════════════════════════════╗\n"
        "║   🖥️   LIVE  SERVER  MONITOR   ║\n"
        "╚════════════════════════════════╝\n\n"
        f"⚡  CPU:    {cpu_bar} <code>{stats['cpu']:.1f}%</code>\n"
        f"    Load:   <code>{stats['load_avg'][0]:.2f} {stats['load_avg'][1]:.2f} {stats['load_avg'][2]:.2f}</code>\n\n"
        f"💾  RAM:    {mem_bar} <code>{utils.fmt_bytes(stats['memory']['used'])}/{utils.fmt_bytes(stats['memory']['total'])}</code>\n\n"
        f"💿  DISK:   {dsk_bar} <code>{stats['disk']['percent']:.1f}%</code>\n"
        f"    Free:   <code>{utils.fmt_bytes(stats['disk']['total'] - stats['disk']['used'])}</code>\n\n"
        f"{utils.divider()}\n"
        f"⏱   Uptime:    <code>{utils.fmt_uptime(stats['uptime'])}</code>\n"
        f"🔢  Processes: <code>{stats['processes']}</code>\n"
        f"📤  Net ↑:     <code>{utils.fmt_bytes(stats['network']['sent'])}</code>\n"
        f"📥  Net ↓:     <code>{utils.fmt_bytes(stats['network']['recv'])}</code>\n"
        + temp_line +
        f"{utils.divider()}\n"
        f"<i>⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
    )


def _server_kb():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔄  Refresh",    callback_data="adm_server"))
    b.row(InlineKeyboardButton(text="◀  Admin Panel", callback_data="admin_home"))
    return b.as_markup()


# ─────────────────────────────────────────────────────────────────────
# ANALYTICS
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm_analytics")
@_require_admin
async def cb_analytics(cq: CallbackQuery):
    await cq.answer()
    us  = db.user_stats()
    bs  = db.bot_stats()
    eco = db.economy_stats()
    c   = db.conn()
    ref_count = c.execute("SELECT COUNT(*) FROM referrals").fetchone()[0]
    bc_count  = c.execute("SELECT COUNT(*) FROM broadcasts").fetchone()[0]
    bc_sent   = c.execute("SELECT SUM(sent) FROM broadcasts").fetchone()[0] or 0

    text = (
        "📊 <b>ANALYTICS  DASHBOARD</b>\n"
        f"{utils.divider()}\n\n"
        "👥 <b>Users</b>\n"
        f"   Total:      <code>{us['total']}</code>\n"
        f"   New Today:  <code>{us['today']}</code>\n"
        f"   Active 7d:  <code>{us['active_7d']}</code>\n"
        f"   Premium:    <code>{us['premium']}</code>\n"
        f"   Banned:     <code>{us['banned']}</code>\n\n"
        "🤖 <b>Bots</b>\n"
        f"   Total:      <code>{bs['total']}</code>\n"
        f"   Running:    <code>{bs['running']}</code>\n"
        f"   Stopped:    <code>{bs['stopped']}</code>\n"
        f"   Error:      <code>{bs['error']}</code>\n\n"
        "🪙 <b>Economy</b>\n"
        f"   Coins circ: <code>{eco['total_coins']:,}</code>\n"
        f"   Ever earned:<code>{eco['total_earned']:,}</code>\n"
        f"   Tx count:   <code>{eco['tx_count']:,}</code>\n"
        f"   Slots sold: <code>{eco['slots_bought']}</code>\n\n"
        "🔗 <b>Referrals</b>\n"
        f"   Total:      <code>{ref_count}</code>\n\n"
        "📢 <b>Broadcasts</b>\n"
        f"   Total sent: <code>{bc_count}</code> broadcasts\n"
        f"   Messages:   <code>{bc_sent}</code>\n\n"
        f"<i>⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}</i>"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="◀  Admin Panel", callback_data="admin_home"))
    await _edit(cq, text, b.as_markup())


# ─────────────────────────────────────────────────────────────────────
# USER LIST
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm_users_"))
@_require_admin
async def cb_user_list(cq: CallbackQuery):
    await cq.answer()
    page  = int(cq.data.split("_")[-1])
    users = db.all_users()
    text  = f"👥 <b>All Users  ({len(users)})</b>"
    await _edit(cq, text, kb.kb_admin_users(users, page))


# ─────────────────────────────────────────────────────────────────────
# USER PROFILE
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm_view_"))
@_require_admin
async def cb_view_user(cq: CallbackQuery):
    await cq.answer()
    uid = int(cq.data.split("_")[-1])
    await _show_profile(cq, uid)


async def _show_profile(target, uid: int) -> None:
    row = db.get_user(uid)
    if not row:
        txt = f"❌ User <code>{uid}</code> not found."
        if isinstance(target, CallbackQuery):
            await target.message.answer(txt)
        else:
            await target.reply(txt)
        return

    bots    = db.get_user_bots(uid)
    used, mx = db.get_slot_counts(uid)
    running  = [b for b in bots if b["status"] == "running"]
    pids     = ", ".join(str(b["pid"]) for b in running if b["pid"]) or "None"
    refs     = db.referral_count(uid)

    text = (
        "╔════════════════════════════╗\n"
        "║  🕵️   SPY  MODE  ·  Profile ║\n"
        "╚════════════════════════════╝\n\n"
        f"👤  <b>{row['full_name']}</b>\n"
        f"🔗  @{row['username'] or 'N/A'}\n"
        f"🆔  <code>{row['user_id']}</code>\n\n"
        f"{utils.divider()}\n"
        f"📋  Plan:         {utils.plan_label(row['plan'])}\n"
        f"🚫  Banned:       {'⚠️ Yes' if row['is_banned'] else '✅ No'}\n"
        + (f"📋  Ban Reason:   <i>{row['ban_reason']}</i>\n" if row['is_banned'] else "")
        + f"🪙  Coins:        <code>{row['coins']:,}</code>\n"
        f"💰  Total Earned: <code>{row['total_earned']:,}</code>\n"
        f"🔲  Slots:        <code>{used}/{mx}</code>  "
        f"(+{row['bonus_slots']} bonus)\n"
        f"🔗  Referrals:    <code>{refs}</code>\n"
        f"🔥  Streak:       <code>{row['daily_streak']} days</code>\n"
        f"💬  Messages:     <code>{row['message_count']}</code>\n"
        f"{utils.divider()}\n"
        f"🤖  Total Bots:   <code>{len(bots)}</code>\n"
        f"🟢  Running:      <code>{len(running)}</code>\n"
        f"🔢  PIDs:         <code>{pids}</code>\n"
        f"{utils.divider()}\n"
        + (f"📝  Note:         <i>{row['admin_note']}</i>\n" if row['admin_note'] else "")
        + f"📅  Joined:       <code>{utils.fmt_ts(row['joined_at'])}</code>\n"
        f"👁   Last Seen:    <code>{utils.fmt_ts(row['last_seen'])}</code>"
    )
    markup = kb.kb_user_ctrl(uid)
    if isinstance(target, CallbackQuery):
        await _edit(target, text, markup)
    else:
        await target.reply(text, reply_markup=markup)


# ─────────────────────────────────────────────────────────────────────
# /user command
# ─────────────────────────────────────────────────────────────────────

@router.message(Command("user"))
async def cmd_user(msg: Message):
    if not utils.is_admin(msg.from_user.id):
        return
    parts = msg.text.split()
    if len(parts) < 2:
        await msg.reply("Usage: <code>/user &lt;user_id&gt;</code>")
        return
    try:
        uid = int(parts[1])
    except ValueError:
        await msg.reply("❌ Invalid ID.")
        return
    await _show_profile(msg, uid)


# ─────────────────────────────────────────────────────────────────────
# BAN / UNBAN
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm_ban_"))
@_require_admin
async def cb_ban(cq: CallbackQuery):
    uid = int(cq.data.split("_")[-1])
    db.ban_user(uid, "Banned by admin")
    db.log_action(cq.from_user.id, "BAN", uid)
    await pm.kill_all_for_user(uid)
    await cq.answer(f"✅  User {uid} banned!")


@router.callback_query(F.data.startswith("adm_unban_"))
@_require_admin
async def cb_unban(cq: CallbackQuery):
    uid = int(cq.data.split("_")[-1])
    db.unban_user(uid)
    db.log_action(cq.from_user.id, "UNBAN", uid)
    await cq.answer(f"✅  User {uid} unbanned!")


# ─────────────────────────────────────────────────────────────────────
# SET PLAN
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm_plan_"))
@_require_admin
async def cb_set_plan(cq: CallbackQuery):
    parts = cq.data.split("_")
    uid, plan = int(parts[2]), parts[3]
    if plan not in config.PLANS:
        await cq.answer("Invalid plan.", show_alert=True)
        return
    db.set_plan(uid, plan)
    db.log_action(cq.from_user.id, f"SET_PLAN:{plan}", uid)
    await cq.answer(f"✅  {utils.plan_label(plan)} → {uid}!")
    bot_obj = cq.bot
    with suppress(Exception):
        await bot_obj.send_message(
            uid,
            f"🎉 <b>Plan Upgraded!</b>\n\n"
            f"Your new plan: {utils.plan_label(plan)}\n"
            f"Slots: <code>{utils.plan_slots(plan)}</code>\n\n"
            f"Enjoy your upgrade! {utils.plan_emoji(plan)} 🚀"
        )


# ─────────────────────────────────────────────────────────────────────
# KILL BOTS / DELETE FILES
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm_killbots_"))
@_require_admin
async def cb_kill(cq: CallbackQuery):
    uid   = int(cq.data.split("_")[-1])
    count = await pm.kill_all_for_user(uid)
    db.log_action(cq.from_user.id, "KILL_BOTS", uid, f"count={count}")
    await cq.answer(f"🛑  Killed {count} bot(s) for {uid}!")


@router.callback_query(F.data.startswith("adm_delfiles_"))
@_require_admin
async def cb_delfiles(cq: CallbackQuery):
    uid = int(cq.data.split("_")[-1])
    await pm.kill_all_for_user(uid)
    pm.delete_user_files(uid)
    db.log_action(cq.from_user.id, "DELETE_FILES", uid)
    await cq.answer(f"🗑  All files deleted for {uid}!")


# ─────────────────────────────────────────────────────────────────────
# NOTE
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm_note_"))
@_require_admin
async def cb_note_prompt(cq: CallbackQuery, state: FSMContext):
    uid = int(cq.data.split("_")[-1])
    await cq.answer()
    await state.set_state(AdminState.note)
    await state.update_data(target=uid)
    await cq.message.answer(
        f"📝 Send admin note for <code>{uid}</code>:",
        reply_markup=kb.kb_cancel("admin_home"),
    )


@router.message(AdminState.note, F.text)
async def handle_note(msg: Message, state: FSMContext):
    data = await state.get_data()
    uid  = data["target"]
    db.set_note(uid, msg.text.strip()[:500])
    db.log_action(msg.from_user.id, "NOTE", uid)
    await state.clear()
    await msg.reply(f"✅  Note saved for <code>{uid}</code>.")


# ─────────────────────────────────────────────────────────────────────
# GIVE COINS
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm_coins_"))
@_require_admin
async def cb_coins_prompt(cq: CallbackQuery, state: FSMContext):
    uid = int(cq.data.split("_")[-1])
    await cq.answer()
    await state.set_state(AdminState.give_coins)
    await state.update_data(target=uid)
    row = db.get_user(uid)
    bal = row["coins"] if row else 0
    await cq.message.answer(
        f"🪙 Give/deduct coins for <code>{uid}</code>\n"
        f"Current balance: <code>{bal:,}</code>\n\n"
        "Send amount (negative to deduct):",
        reply_markup=kb.kb_cancel("admin_home"),
    )


@router.message(AdminState.give_coins, F.text)
async def handle_give_coins(msg: Message, state: FSMContext):
    data = await state.get_data()
    uid  = data["target"]
    try:
        amount = int(msg.text.strip())
    except ValueError:
        await msg.reply("❌ Enter an integer.")
        return
    db.add_coins(uid, amount, f"admin_gift by {msg.from_user.id}")
    db.log_action(msg.from_user.id, f"COINS:{amount:+}", uid)
    row = db.get_user(uid)
    await state.clear()
    await msg.reply(
        f"{'🪙 Gave' if amount > 0 else '💸 Deducted'} "
        f"<code>{abs(amount)}</code> coins "
        f"{'to' if amount > 0 else 'from'} <code>{uid}</code>\n"
        f"New balance: <code>{row['coins']:,}</code>"
    )
    with suppress(Exception):
        await msg.bot.send_message(
            uid,
            f"{'🪙 Received' if amount > 0 else '💸 Deducted'} "
            f"<b>{abs(amount):,} coins</b> by admin!\n"
            f"Balance: <code>{row['coins']:,}</code>"
        )


# ─────────────────────────────────────────────────────────────────────
# SEND MESSAGE TO USER
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm_msg_"))
@_require_admin
async def cb_msg_prompt(cq: CallbackQuery, state: FSMContext):
    uid = int(cq.data.split("_")[-1])
    await cq.answer()
    await state.set_state(AdminState.send_msg)
    await state.update_data(target=uid)
    await cq.message.answer(
        f"📨 Send message to <code>{uid}</code>:",
        reply_markup=kb.kb_cancel("admin_home"),
    )


@router.message(AdminState.send_msg, F.text)
async def handle_send_msg(msg: Message, state: FSMContext):
    data = await state.get_data()
    uid  = data["target"]
    await state.clear()
    try:
        await msg.bot.send_message(
            uid,
            f"📨 <b>Message from Admin:</b>\n\n{msg.text}"
        )
        await msg.reply(f"✅  Message delivered to <code>{uid}</code>.")
    except Exception as e:
        await msg.reply(f"❌  Failed: <code>{e}</code>")


# ─────────────────────────────────────────────────────────────────────
# SLOTS COMMAND
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm_slots_"))
@_require_admin
async def cb_slots_prompt(cq: CallbackQuery, state: FSMContext):
    uid = int(cq.data.split("_")[-1])
    await cq.answer()
    row = db.get_user(uid)
    cur_bonus = row["bonus_slots"] if row else 0
    await cq.message.answer(
        f"🔲 Set bonus slots for <code>{uid}</code>\n"
        f"Current bonus: <code>{cur_bonus}</code>\n\n"
        "Send new bonus slot count:",
        reply_markup=kb.kb_cancel("admin_home"),
    )
    await state.set_state(AdminState.give_slots)
    await state.update_data(target=uid)


@router.message(AdminState.give_slots, F.text)
async def handle_give_slots(msg: Message, state: FSMContext):
    data = await state.get_data()
    uid  = data["target"]
    try:
        n = int(msg.text.strip())
    except ValueError:
        await msg.reply("❌ Enter an integer.")
        return
    db.set_bonus_slots(uid, n)
    db.log_action(msg.from_user.id, f"SET_SLOTS:{n}", uid)
    await state.clear()
    await msg.reply(f"✅  Bonus slots for <code>{uid}</code> set to <code>{n}</code>.")


# ─────────────────────────────────────────────────────────────────────
# MAINTENANCE
# ─────────────────────────────────────────────────────────────────────

@router.message(Command("maintenance"))
async def cmd_maintenance(msg: Message):
    if not utils.is_admin(msg.from_user.id):
        return
    parts = msg.text.split()
    if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
        await msg.reply("Usage: <code>/maintenance on|off</code>")
        return
    on = parts[1].lower() == "on"
    utils.set_maintenance(on)
    db.log_action(msg.from_user.id, f"MAINTENANCE_{'ON' if on else 'OFF'}")
    await msg.reply(f"🔧 Maintenance: <b>{'🔒 ENABLED' if on else '🔓 DISABLED'}</b>")


@router.callback_query(F.data == "adm_maint_on")
@_require_admin
async def cb_maint_on(cq: CallbackQuery):
    utils.set_maintenance(True)
    db.log_action(cq.from_user.id, "MAINTENANCE_ON")
    await cq.answer("🔒  Maintenance ON")
    await _edit(cq, _admin_home_text(), kb.kb_admin())


@router.callback_query(F.data == "adm_maint_off")
@_require_admin
async def cb_maint_off(cq: CallbackQuery):
    utils.set_maintenance(False)
    db.log_action(cq.from_user.id, "MAINTENANCE_OFF")
    await cq.answer("🔓  Maintenance OFF")
    await _edit(cq, _admin_home_text(), kb.kb_admin())


# ─────────────────────────────────────────────────────────────────────
# /exec  (OWNER ONLY)
# ─────────────────────────────────────────────────────────────────────

@router.message(Command("exec"))
async def cmd_exec(msg: Message):
    if not utils.is_owner(msg.from_user.id):
        await msg.reply("🚫 <b>OWNER ONLY</b>")
        return
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("Usage: <code>/exec &lt;command&gt;</code>")
        return
    cmd = parts[1].strip()
    sm  = await msg.reply(f"💻  Running: <code>{cmd[:80]}</code>…")
    db.log_action(msg.from_user.id, "EXEC", detail=cmd[:300])
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=config.EXEC_TIMEOUT)
        output = out.decode("utf-8", errors="replace")
        tail   = output[-3400:] if len(output) > 3400 else output
        icon   = "✅" if proc.returncode == 0 else "❌"
        await sm.edit_text(
            f"{icon}  Exit: <code>{proc.returncode}</code>\n"
            f"<code>{cmd[:80]}</code>\n"
            f"{utils.divider()}\n"
            f"<pre>{tail or '(no output)'}</pre>"
        )
    except asyncio.TimeoutError:
        await sm.edit_text(f"⏱  Timed out ({config.EXEC_TIMEOUT}s)")
    except Exception as e:
        await sm.edit_text(f"❌  Error: <code>{e}</code>")


# ─────────────────────────────────────────────────────────────────────
# /broadcast
# ─────────────────────────────────────────────────────────────────────

@router.message(Command("broadcast"))
async def cmd_broadcast(msg: Message):
    if not utils.is_admin(msg.from_user.id):
        return
    if not msg.reply_to_message:
        await msg.reply(
            "📢 <b>Broadcast</b>\n\n"
            "Reply to a message with this command:\n"
            "<code>/broadcast</code>  — send to all\n"
            "<code>/broadcast pin</code>  — send + pin"
        )
        return

    args   = msg.text.split()[1:]
    do_pin = "pin" in args
    reply  = msg.reply_to_message
    users  = db.all_users()
    sm     = await msg.reply(f"📢  Broadcasting to <b>{len(users)}</b> users…")
    sent = fail = 0

    for u in users:
        try:
            sent_msg = await msg.bot.copy_message(
                u["user_id"], reply.chat.id, reply.message_id
            )
            if do_pin:
                with suppress(Exception):
                    await msg.bot.pin_chat_message(u["user_id"], sent_msg.message_id)
            sent += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            fail += 1
        except Exception:
            fail += 1
        await asyncio.sleep(config.BROADCAST_DELAY)

    preview = (reply.text or reply.caption or "media")[:80]
    db.log_broadcast(msg.from_user.id, preview, sent, fail, do_pin)
    db.log_action(msg.from_user.id, "BROADCAST", detail=f"sent={sent} fail={fail}")
    await sm.edit_text(
        f"📢 <b>Broadcast Complete!</b>\n\n"
        f"✅  Sent:   <code>{sent}</code>\n"
        f"❌  Failed: <code>{fail}</code>\n"
        f"📌  Pinned: {'Yes' if do_pin else 'No'}"
    )


@router.callback_query(F.data == "adm_broadcast")
@_require_admin
async def cb_broadcast_info(cq: CallbackQuery):
    await cq.answer()
    await _edit(
        cq,
        "📢 <b>Broadcast</b>\n\n"
        "Reply to any message with:\n"
        "<code>/broadcast</code>  — send to all users\n"
        "<code>/broadcast pin</code>  — send and pin\n\n"
        "<i>Supports text, images, videos, documents.</i>",
        kb.kb_back("admin_home"),
    )


# ─────────────────────────────────────────────────────────────────────
# LEADERBOARD
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm_leaderboard")
@_require_admin
async def cb_leaderboard(cq: CallbackQuery):
    await cq.answer()
    tops  = db.top_referrers(10)
    tcoin = db.top_coins(10)
    medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7

    lines = ["🏆 <b>LEADERBOARD</b>\n\n🔗 <b>Top Referrers:</b>"]
    for i, r in enumerate(tops):
        name = r["full_name"] or r["username"] or str(r["user_id"])
        lines.append(f"{medals[i]}  {name[:20]} — <code>{r['rc']}</code> refs")

    lines.append("\n🪙 <b>Top Coin Holders:</b>")
    for i, r in enumerate(tcoin):
        name = r["full_name"] or r["username"] or str(r["user_id"])
        lines.append(f"{medals[i]}  {name[:20]} — <code>{r['coins']:,}</code> coins")

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="◀  Admin Panel", callback_data="admin_home"))
    await _edit(cq, "\n".join(lines), b.as_markup())


# ─────────────────────────────────────────────────────────────────────
# ADMIN LOG
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm_log")
@_require_admin
async def cb_admin_log(cq: CallbackQuery):
    await cq.answer()
    logs  = db.get_log(25)
    lines = [f"📋 <b>Admin Log  (last {len(logs)})</b>\n"]
    for e in logs:
        tgt = f" → <code>{e['target_id']}</code>" if e["target_id"] else ""
        lines.append(
            f"<code>{e['created_at'][11:16]}</code>  "
            f"<b>{e['action']}</b>{tgt}"
            + (f"\n   <i>{e['detail'][:60]}</i>" if e["detail"] else "")
        )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="◀  Admin Panel", callback_data="admin_home"))
    await _edit(cq, "\n".join(lines), b.as_markup())


# ─────────────────────────────────────────────────────────────────────
# SYSTEM EVENTS
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm_events")
@_require_admin
async def cb_events(cq: CallbackQuery):
    await cq.answer()
    events = db.recent_events(20)
    lines  = [f"📡 <b>System Events  (last {len(events)})</b>\n"]
    type_icon = {
        "BOT_START": "▶️", "BOT_STOP": "⏹",
        "RESOURCE_ALERT": "🔥", "BOT_CRASH": "💀",
    }
    for e in events:
        icon = type_icon.get(e["event_type"], "•")
        lines.append(
            f"{icon}  <code>{e['created_at'][11:16]}</code>  "
            f"<b>{e['event_type']}</b>"
            + (f"  <i>{e['detail'][:50]}</i>" if e["detail"] else "")
        )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="◀  Admin Panel", callback_data="admin_home"))
    await _edit(cq, "\n".join(lines), b.as_markup())


# ─────────────────────────────────────────────────────────────────────
# ALL BOTS
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm_allbots_"))
@_require_admin
async def cb_all_bots(cq: CallbackQuery):
    await cq.answer()
    page = int(cq.data.split("_")[-1])
    bots = db.get_all_active_bots()
    bs   = db.bot_stats()
    text = (
        f"🤖 <b>All Active Bots  ({bs['total']})</b>\n"
        f"🟢 {bs['running']} running  🔴 {bs['stopped']} stopped"
    )
    await _edit(cq, text, kb.kb_admin_bots(bots, page))


# ─────────────────────────────────────────────────────────────────────
# DATABASE BACKUP
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm_backup")
@_require_admin
async def cb_backup(cq: CallbackQuery):
    await cq.answer("Creating backup…")
    Path(config.BACKUPS_DIR).mkdir(parents=True, exist_ok=True)
    fname = f"gph_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    dest  = Path(config.BACKUPS_DIR) / fname
    shutil.copy2(config.DB_PATH, dest)
    db.log_action(cq.from_user.id, "DB_BACKUP")
    await cq.message.answer_document(
        FSInputFile(dest, filename=fname),
        caption=f"💾 <b>DB Backup</b>\n<code>{fname}</code>",
    )


# ─────────────────────────────────────────────────────────────────────
# ECONOMY PANEL
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm_economy")
@_require_admin
async def cb_economy(cq: CallbackQuery):
    await cq.answer()
    eco = db.economy_stats()
    text = (
        "💰 <b>ECONOMY  OVERVIEW</b>\n"
        f"{utils.divider()}\n\n"
        f"🪙  In Circulation:  <code>{eco['total_coins']:,}</code>\n"
        f"💸  Ever Distributed: <code>{eco['total_earned']:,}</code>\n"
        f"📊  Transactions:    <code>{eco['tx_count']:,}</code>\n"
        f"🛒  Slots Purchased: <code>{eco['slots_bought']}</code>\n\n"
        f"💡 Earn rates:\n"
        f"   Daily base:     <code>+{config.DAILY_BASE_COINS}</code>\n"
        f"   Streak bonus:   <code>+{config.DAILY_STREAK_BONUS}/day</code>\n"
        f"   7-day bonus:    <code>+{config.WEEKLY_BONUS_COINS}</code>\n"
        f"   30-day bonus:   <code>+{config.MONTHLY_BONUS_COINS}</code>\n"
        f"   Referral:       <code>+{config.REFERRAL_COINS}</code>\n\n"
        f"🛒 Slot cost: <code>{config.COIN_PER_SLOT}</code> coins"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="◀  Admin Panel", callback_data="admin_home"))
    await _edit(cq, text, b.as_markup())


# ─────────────────────────────────────────────────────────────────────
# COMMANDS: /addcoins  /setslots  /setplan  /finduser
# ─────────────────────────────────────────────────────────────────────

@router.message(Command("addcoins"))
async def cmd_addcoins(msg: Message):
    if not utils.is_admin(msg.from_user.id):
        return
    parts = msg.text.split()
    if len(parts) < 3:
        await msg.reply("Usage: <code>/addcoins &lt;uid&gt; &lt;amount&gt;</code>")
        return
    try:
        uid, n = int(parts[1]), int(parts[2])
    except ValueError:
        await msg.reply("❌ Invalid args.")
        return
    db.add_coins(uid, n, f"admin_cmd by {msg.from_user.id}")
    db.log_action(msg.from_user.id, f"ADDCOINS:{n}", uid)
    row = db.get_user(uid)
    await msg.reply(f"🪙  Done. Balance: <code>{row['coins']:,}</code>")


@router.message(Command("setslots"))
async def cmd_setslots(msg: Message):
    if not utils.is_admin(msg.from_user.id):
        return
    parts = msg.text.split()
    if len(parts) < 3:
        await msg.reply("Usage: <code>/setslots &lt;uid&gt; &lt;n&gt;</code>")
        return
    try:
        uid, n = int(parts[1]), int(parts[2])
    except ValueError:
        await msg.reply("❌ Invalid args.")
        return
    db.set_bonus_slots(uid, n)
    db.log_action(msg.from_user.id, f"SETSLOTS:{n}", uid)
    await msg.reply(f"✅  Bonus slots set to <code>{n}</code> for <code>{uid}</code>.")


@router.message(Command("setplan"))
async def cmd_setplan(msg: Message):
    if not utils.is_admin(msg.from_user.id):
        return
    parts = msg.text.split()
    if len(parts) < 3:
        await msg.reply(
            "Usage: <code>/setplan &lt;uid&gt; &lt;plan&gt;</code>\n"
            f"Plans: {', '.join(config.PLANS.keys())}"
        )
        return
    try:
        uid = int(parts[1])
    except ValueError:
        await msg.reply("❌ Invalid UID.")
        return
    plan = parts[2].lower()
    if plan not in config.PLANS:
        await msg.reply(f"❌ Invalid plan. Use: {', '.join(config.PLANS.keys())}")
        return
    db.set_plan(uid, plan)
    db.log_action(msg.from_user.id, f"SETPLAN:{plan}", uid)
    await msg.reply(f"✅  Plan set to {utils.plan_label(plan)} for <code>{uid}</code>.")


@router.message(Command("finduser"))
async def cmd_finduser(msg: Message):
    if not utils.is_admin(msg.from_user.id):
        return
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply("Usage: <code>/finduser &lt;query&gt;</code>")
        return
    results = db.search_users(parts[1].strip())
    if not results:
        await msg.reply("❌  No users found.")
        return
    lines = [f"🔍 <b>Results ({len(results)})</b>\n"]
    for r in results:
        lines.append(
            f"• <code>{r['user_id']}</code>  "
            f"{r['full_name'] or '?'}  @{r['username'] or 'N/A'}  "
            f"{utils.plan_label(r['plan'])}"
        )
    b = InlineKeyboardBuilder()
    if len(results) <= 5:
        for r in results:
            b.row(InlineKeyboardButton(
                text=f"👤 {r['full_name'][:15] or r['user_id']}",
                callback_data=f"adm_view_{r['user_id']}"
            ))
    b.row(InlineKeyboardButton(text="🏠  Menu", callback_data="home"))
    await msg.reply("\n".join(lines), reply_markup=b.as_markup())


# ─────────────────────────────────────────────────────────────────────
# WEB ADMIN PANEL
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm_web")
@_require_admin
async def cb_web_admin(cq: CallbackQuery):
    await cq.answer()
    text = (
        "🌐 <b>Web Admin Panel</b>\n\n"
        "Access the advanced web dashboard:\n\n"
        f"🔗 URL: <code>http://your-server:{config.WEB_ADMIN_PORT}</code>\n\n"
        "<i>The web panel provides real-time monitoring, "
        "advanced analytics, and easy management.</i>\n\n"
        "<b>Features:</b>\n"
        "• Real-time server stats\n"
        "• Bot management\n"
        "• User management\n"
        "• Analytics & Charts\n"
        "• Activity logs"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="◀  Admin Panel", callback_data="admin_home"))
    await _edit(cq, text, b.as_markup())


# ─────────────────────────────────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm_settings")
@_require_admin
async def cb_settings(cq: CallbackQuery):
    await cq.answer()
    text = (
        "⚙️ <b>SYSTEM SETTINGS</b>\n"
        f"{utils.divider()}\n\n"
        f"🤖 Bot Name:  <code>{config.BOT_NAME}</code>\n"
        f"📌 Version:   <code>{config.BOT_VERSION}</code>\n"
        f"👤 Owner:     {config.OWNER_USERNAME}\n\n"
        f"<b>Features:</b>\n"
        f"  ZIP Deploy:     {'✅' if config.ENABLE_ZIP_DEPLOY else '❌'}\n"
        f"  Auto-Restart:   {'✅' if config.ENABLE_AUTO_RESTART else '❌'}\n"
        f"  Coins System:   {'✅' if config.ENABLE_COINS else '❌'}\n"
        f"  Daily Rewards:  {'✅' if config.ENABLE_DAILY else '❌'}\n"
        f"  Scheduled Bots: {'✅' if config.ENABLE_SCHEDULED_BOTS else '❌'}\n\n"
        f"<b>Limits:</b>\n"
        f"  Max File Size:  <code>{config.MAX_FILE_SIZE // 1024 // 1024} MB</code>\n"
        f"  Max Auto-Restart: <code>{config.MAX_AUTO_RESTART}</code>\n"
        f"  Watchdog Interval: <code>{config.WATCHDOG_INTERVAL}s</code>"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="◀  Admin Panel", callback_data="admin_home"))
    await _edit(cq, text, b.as_markup())
