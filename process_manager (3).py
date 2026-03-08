# ╔══════════════════════════════════════════════════════════════════════╗
# ║   ⚡ GADGET PREMIUM HOST  v4.0  ·  process_manager.py               ║
# ╚══════════════════════════════════════════════════════════════════════╝

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Callable, Optional

import psutil

import config
import database as db

log = logging.getLogger("GPH.pm")

# Registry of running subprocesses
_procs: dict[int, asyncio.subprocess.Process] = {}
# Last auto-restart timestamp per bot
_last_restart: dict[int, float] = {}
# Async notify callback set at startup
_notify_cb: Optional[Callable] = None


def set_notify_cb(cb: Callable) -> None:
    global _notify_cb
    _notify_cb = cb


# ─────────────────────────────────────────────────────────────────────
# START
# ─────────────────────────────────────────────────────────────────────

async def start(bid: int, file_path: str,
                env_vars: Optional[dict] = None) -> tuple[bool, str]:
    # Kill stale
    if bid in _procs:
        await _terminate(_procs.pop(bid))

    Path(config.LOGS_DIR).mkdir(parents=True, exist_ok=True)
    log_path = Path(config.LOGS_DIR) / f"{bid}.log"
    env = {**os.environ, **(env_vars or {})}

    try:
        fh = open(log_path, "a", encoding="utf-8")
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        fh.write(f"\n{'═'*52}\n▶  STARTED  {ts}\n{'═'*52}\n")
        fh.flush()

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-u", file_path,
            stdout=fh, stderr=fh,
            env=env, start_new_session=True,
        )
        _procs[bid] = proc
        db.update_bot_status(bid, "running", proc.pid)
        db.reset_restart_count(bid)
        log.info(f"[Bot {bid}] started PID={proc.pid}")
        db.log_event("BOT_START", f"bid={bid} pid={proc.pid}")
        return True, f"✅ Started! PID: <code>{proc.pid}</code>"
    except Exception as e:
        log.error(f"[Bot {bid}] start failed: {e}")
        db.update_bot_status(bid, "error")
        return False, f"❌ Start failed: <code>{e}</code>"


# ─────────────────────────────────────────────────────────────────────
# STOP
# ─────────────────────────────────────────────────────────────────────

async def stop(bid: int) -> tuple[bool, str]:
    proc = _procs.pop(bid, None)
    if proc is None:
        row = db.get_bot(bid)
        if row and row["pid"]:
            with suppress(ProcessLookupError, PermissionError):
                os.kill(row["pid"], signal.SIGTERM)
        db.update_bot_status(bid, "stopped")
        return True, "⏹  Bot stopped."
    await _terminate(proc)
    db.update_bot_status(bid, "stopped")
    db.log_event("BOT_STOP", f"bid={bid}")
    log.info(f"[Bot {bid}] stopped")
    return True, "⏹  Bot stopped."


async def _terminate(proc: asyncio.subprocess.Process) -> None:
    with suppress(ProcessLookupError):
        proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        with suppress(ProcessLookupError):
            proc.kill()
        with suppress(Exception):
            await asyncio.wait_for(proc.wait(), timeout=3.0)


# ─────────────────────────────────────────────────────────────────────
# RESTART
# ─────────────────────────────────────────────────────────────────────

async def restart(bid: int) -> tuple[bool, str]:
    row = db.get_bot(bid)
    if not row:
        return False, "❌ Bot not found."
    await stop(bid)
    await asyncio.sleep(1.0)
    envs = db.env_dict(bid)
    return await start(bid, row["file_path"], envs or None)


# ─────────────────────────────────────────────────────────────────────
# LOG READER
# ─────────────────────────────────────────────────────────────────────

async def read_log(bid: int) -> str:
    path = Path(config.LOGS_DIR) / f"{bid}.log"
    if not path.exists():
        return "ℹ️  No log file yet."
    size = path.stat().st_size
    if size == 0:
        return "ℹ️  Log is empty."
    seek = max(0, size - config.LOG_TAIL_BYTES)
    with open(path, "r", errors="replace") as f:
        f.seek(seek)
        content = f.read()
    lines = content.splitlines()[-config.MAX_LOG_LINES:]
    return "\n".join(lines)


def log_path(bid: int) -> Optional[Path]:
    p = Path(config.LOGS_DIR) / f"{bid}.log"
    return p if p.exists() else None


# ─────────────────────────────────────────────────────────────────────
# RESOURCE SNAPSHOT
# ─────────────────────────────────────────────────────────────────────

def snapshot(bid: int) -> Optional[dict]:
    row = db.get_bot(bid)
    if not row or not row["pid"]:
        return None
    try:
        p   = psutil.Process(row["pid"])
        cpu = p.cpu_percent(interval=0.3)
        mem = p.memory_info()
        thr = p.num_threads()
        fds = p.num_fds() if hasattr(p, "num_fds") else 0
        ups = time.time() - p.create_time()
        db.update_bot_resources(bid, cpu, mem.rss)
        return {"pid": row["pid"], "cpu": cpu, "rss": mem.rss,
                "vms": mem.vms, "threads": thr, "fds": fds, "uptime": ups}
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


# ─────────────────────────────────────────────────────────────────────
# BULK OPS
# ─────────────────────────────────────────────────────────────────────

async def kill_all_for_user(uid: int) -> int:
    count = 0
    for b in db.get_user_bots(uid):
        bid = b["bot_id"]
        if bid in _procs:
            await _terminate(_procs.pop(bid))
            db.update_bot_status(bid, "stopped")
            count += 1
    return count


def delete_user_files(uid: int) -> None:
    user_dir = Path(config.BOTS_DIR) / str(uid)
    if user_dir.exists():
        shutil.rmtree(user_dir, ignore_errors=True)
    for b in db.get_user_bots(uid):
        lp = Path(config.LOGS_DIR) / f"{b['bot_id']}.log"
        lp.unlink(missing_ok=True)
        db.soft_delete_bot(b["bot_id"])


# ─────────────────────────────────────────────────────────────────────
# WATCHDOG
# ─────────────────────────────────────────────────────────────────────

_alert_ts: dict[str, float] = {}


async def watchdog() -> None:
    log.info("Watchdog started ✔")
    while True:
        await asyncio.sleep(config.WATCHDOG_INTERVAL)
        await _check_processes()
        await _check_system_resources()
        if config.ENABLE_SCHEDULED_BOTS:
            await _check_schedules()


async def _check_processes() -> None:
    for bid, proc in list(_procs.items()):
        if proc.returncode is not None:
            log.warning(f"[Bot {bid}] exited code={proc.returncode}")
            _procs.pop(bid, None)
            row = db.get_bot(bid)
            if not row or row["status"] == "deleted":
                continue

            db.update_bot_status(bid, "error")
            db.inc_crash_count(bid)

            if config.ENABLE_AUTO_RESTART and row["auto_restart"]:
                now   = time.time()
                last  = _last_restart.get(bid, 0)
                count = db.inc_restart_count(bid)
                if count <= config.MAX_AUTO_RESTART and now - last > config.RESTART_COOLDOWN:
                    _last_restart[bid] = now
                    log.info(f"[Bot {bid}] auto-restart #{count}")
                    envs = db.env_dict(bid)
                    ok, msg = await start(bid, row["file_path"], envs or None)
                    if ok and _notify_cb:
                        await _notify_cb(
                            row["owner_id"], bid, row["bot_name"],
                            f"🔄 Auto-restarted (attempt {count}/{config.MAX_AUTO_RESTART})"
                        )
                    elif not ok and _notify_cb:
                        await _notify_cb(
                            row["owner_id"], bid, row["bot_name"],
                            f"💀 Crashed! Auto-restart #{count} failed.\n{msg}"
                        )
                    continue

            if _notify_cb:
                await _notify_cb(
                    row["owner_id"], bid, row["bot_name"],
                    f"💀 Bot crashed! (exit code {proc.returncode})"
                )


async def _check_system_resources() -> None:
    if not _notify_cb:
        return
    now = time.time()

    try:
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        dsk = psutil.disk_usage("/").percent

        for key, val, threshold, label in [
            ("cpu",  cpu,  config.CPU_ALERT_PCT,  f"🔥 CPU: {cpu:.1f}%"),
            ("ram",  ram,  config.RAM_ALERT_PCT,  f"💾 RAM: {ram:.1f}%"),
            ("disk", dsk,  config.DISK_ALERT_PCT, f"💿 Disk: {dsk:.1f}%"),
        ]:
            if val > threshold and now - _alert_ts.get(key, 0) > config.ALERT_COOLDOWN:
                _alert_ts[key] = now
                db.log_event("RESOURCE_ALERT", label)
                await _notify_cb(config.OWNER_ID, None, "⚠️ SERVER ALERT", label)
    except Exception:
        pass


async def _check_schedules() -> None:
    now_hm = time.strftime("%H:%M")
    for row in db.get_all_active_bots():
        bid = row["bot_id"]
        if row["schedule_start"] == now_hm and row["status"] == "stopped":
            envs = db.env_dict(bid)
            await start(bid, row["file_path"], envs or None)
            if _notify_cb:
                await _notify_cb(
                    row["owner_id"], bid, row["bot_name"],
                    f"⏰ Scheduled start at {now_hm}"
                )
        elif row["schedule_stop"] == now_hm and row["status"] == "running":
            await stop(bid)
            if _notify_cb:
                await _notify_cb(
                    row["owner_id"], bid, row["bot_name"],
                    f"⏰ Scheduled stop at {now_hm}"
                )


# ─────────────────────────────────────────────────────────────────────
# SYSTEM INFO
# ─────────────────────────────────────────────────────────────────────

def get_system_stats() -> dict:
    """Get comprehensive system statistics."""
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    net = psutil.net_io_counters()
    uptime = time.time() - psutil.boot_time()
    load = psutil.getloadavg()
    
    temp = None
    with suppress(Exception):
        temps = psutil.sensors_temperatures() or {}
        for chip_temps in temps.values():
            for t in chip_temps:
                if t.current:
                    temp = t.current
                    break
            if temp:
                break
    
    return {
        "cpu": cpu,
        "memory": {
            "used": mem.used,
            "total": mem.total,
            "percent": mem.percent,
        },
        "disk": {
            "used": disk.used,
            "total": disk.total,
            "percent": disk.percent,
        },
        "uptime": uptime,
        "processes": len(psutil.pids()),
        "network": {
            "sent": net.bytes_sent,
            "recv": net.bytes_recv,
        },
        "load_avg": list(load),
        "temperature": temp,
    }
