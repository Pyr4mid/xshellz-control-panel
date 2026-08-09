"""
Pyramid Server Manager
-----------------------
A single-owner Telegram bot that acts as a professional, fully button-driven
control panel for a Linux VPS: bot process manager, real file manager,
persistent terminal mode, live resource monitor, backups and settings.
Reply-keyboard only UI (no typing paths/names unless unavoidable),
SQLite storage.

Run with:  python main.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import platform
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
import uuid
import zipfile
import importlib.metadata as importlib_metadata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import psutil
from telegram import ReplyKeyboardMarkup, Update, KeyboardButton
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    filters,
)

import config

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("pyramid")

# Dependency cache: persistent per-project hashes. A cache entry is only
# written after a successful dependency check/install.
DEPENDENCY_CACHE_FILE = Path(config.SERVER_PATH) / ".xshellz_dependency_cache.json"

def _load_dependency_cache() -> dict:
    try:
        if DEPENDENCY_CACHE_FILE.exists():
            data = json.loads(DEPENDENCY_CACHE_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        log.exception("Failed to load dependency cache")
    return {}

def _save_dependency_cache(data: dict) -> None:
    tmp = DEPENDENCY_CACHE_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(DEPENDENCY_CACHE_FILE)
    except Exception:
        log.exception("Failed to save dependency cache")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass

def _dependency_fingerprint(path: Path, runtime: str) -> Optional[str]:
    files = [path / "requirements.txt"] if runtime == "python" else [path / "package.json", path / "package-lock.json"]
    h = hashlib.sha256()
    found = False
    for fp in files:
        if fp.exists() and fp.is_file():
            found = True
            h.update(fp.name.encode())
            h.update(b"\0")
            h.update(fp.read_bytes())
            h.update(b"\0")
    return h.hexdigest() if found else None

async def _run_blocking(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)

# =========================================================================
# Static button labels
# =========================================================================

BTN_BACK = "⬅️ رجوع"
BTN_HOME = "🏠 القائمة الرئيسية"
NAV_ROW = [BTN_BACK, BTN_HOME]

BTN_BOTS = "🤖 إدارة البوتات"
BTN_FILES = "📁 إدارة الملفات"
BTN_SERVER_INFO = "🖥️ معلومات السيرفر"
BTN_TERMINAL = "💻 تريمنال"
BTN_MONITOR = "📊 مراقبة الموارد"
BTN_SETTINGS = "⚙️ الإعدادات"
BTN_GIT_UPDATE = "📦 تحديث المشاريع من GitHub"

BTN_BOT_NEW = "➕ رفع بوت جديد"

BOT_ACTION_START = "▶ تشغيل"
BOT_ACTION_STOP = "⏹ إيقاف"
BOT_ACTION_RESTART = "🔄 إعادة تشغيل"
BOT_ACTION_LOGS = "📜 Logs"
BOT_ACTION_USAGE = "📊 استهلاك الموارد"
BOT_ACTION_FILES = "📂 الملفات"
BOT_ACTION_SETTINGS = "⚙ الإعدادات"
BOT_ACTION_DELETE = "🗑 حذف"
BOT_ACTION_RENAME = "✏ إعادة تسمية"

CONFIRM_YES = "✅ تأكيد"
CONFIRM_NO = "❌ إلغاء"

FILE_ACT_VIEW = "📄 عرض"
FILE_ACT_EDIT = "✏ تعديل"
FILE_ACT_DOWNLOAD = "📥 تنزيل"
FILE_ACT_SHARE = "📤 مشاركة"
FILE_ACT_COPY = "📑 نسخ"
FILE_ACT_MOVE = "🚚 نقل"
FILE_ACT_DELETE = "🗑 حذف"
FILE_ACT_ZIP = "📦 ضغط"
FILE_ACT_INFO = "ℹ معلومات"

DIR_ACT_OPEN = "📂 فتح"
DIR_ACT_DELETE = "🗑 حذف"
DIR_ACT_ZIP = "📦 ضغط"
DIR_ACT_RENAME = "✏ إعادة تسمية"
DIR_ACT_MKDIR = "📁 إنشاء مجلد"
DIR_ACT_UPLOAD = "⬆ رفع ملف داخل المجلد"

FM_MKDIR = "📁 إنشاء مجلد"
FM_UPLOAD_HERE = "⬆ رفع ملف داخل هذا المجلد"
FM_SEARCH = "🔍 بحث"
FM_PASTE = "📥 لصق هنا"

TERM_CTRLC = "⏹️ Ctrl+C"
TERM_CLEAR = "🧹 مسح الشاشة"
TERM_HISTORY = "📜 آخر الأوامر"
TERM_COPY = "📋 نسخ"

BTN_REFRESH_SERVER = "🔄 تحديث السيرفر"
BTN_DEPS_UPDATE = "📦 تحديث المكتبات"
BTN_ENV_CHECK = "🔍 فحص البيئة"
BTN_RESTART_BOT = "🔁 إعادة تشغيل البوت"

MON_REFRESH = "🔄 تحديث"

CLEAN_BTN = "🧹 تنظيف السيرفر"

BTN_BACKUP_CREATE = "💾 إنشاء نسخة احتياطية"
BTN_BACKUP_RESTORE = "♻️ استعادة نسخة"
BTN_BACKUP_SEND = "📤 إرسال نسخة"

BTN_SET_PASSWORD = "🔑 تغيير كلمة المرور"
BTN_SET_ADD_ADMIN = "➕ إضافة مدير"
BTN_SET_DEL_ADMIN = "➖ حذف مدير"
BTN_SET_NOTIFY = "🔔 تبديل الإشعارات"
BTN_SET_OPLOG = "🧾 سجل العمليات"
BTN_SET_BACKUP = "💾 النسخ الاحتياطي"

INFO_REFRESH = "🔄 تحديث"
INFO_COPY = "📋 نسخ المعلومات"


def kb(rows: list[list[str]]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(t) for t in row] for row in rows] + [NAV_ROW],
        resize_keyboard=True,
    )


MAIN_MENU = kb(
    [
        [BTN_BOTS, BTN_FILES],
        [BTN_SERVER_INFO, BTN_TERMINAL],
        [BTN_MONITOR, BTN_SETTINGS],
        [BTN_GIT_UPDATE, BTN_REFRESH_SERVER],
    ]
)

SETTINGS_MENU = kb(
    [
        [BTN_SET_PASSWORD],
        [BTN_SET_ADD_ADMIN, BTN_SET_DEL_ADMIN],
        [BTN_SET_NOTIFY, BTN_SET_OPLOG],
        [BTN_SET_BACKUP],
        [CLEAN_BTN],
        [BTN_DEPS_UPDATE, BTN_ENV_CHECK],
        [BTN_RESTART_BOT],
    ]
)

BACKUP_MENU = kb([[BTN_BACKUP_CREATE], [BTN_BACKUP_RESTORE], [BTN_BACKUP_SEND]])

TERMINAL_MENU = kb([[TERM_CTRLC, TERM_CLEAR], [TERM_HISTORY, TERM_COPY]])

BOT_DETAIL_MENU = kb(
    [
        [BOT_ACTION_START, BOT_ACTION_STOP],
        [BOT_ACTION_RESTART, BOT_ACTION_LOGS],
        [BOT_ACTION_USAGE, BOT_ACTION_FILES],
        [BOT_ACTION_SETTINGS, BOT_ACTION_RENAME],
        [BOT_ACTION_DELETE],
    ]
)

FILE_ACTION_MENU = kb(
    [
        [FILE_ACT_VIEW, FILE_ACT_EDIT],
        [FILE_ACT_DOWNLOAD, FILE_ACT_SHARE],
        [FILE_ACT_COPY, FILE_ACT_MOVE],
        [FILE_ACT_ZIP, FILE_ACT_INFO],
        [FILE_ACT_DELETE],
    ]
)

DIR_ACTION_MENU = kb(
    [
        [DIR_ACT_OPEN],
        [DIR_ACT_MKDIR, DIR_ACT_UPLOAD],
        [DIR_ACT_ZIP, DIR_ACT_RENAME],
        [DIR_ACT_DELETE],
    ]
)

CONFIRM_MENU = kb([[CONFIRM_YES, CONFIRM_NO]])

# =========================================================================
# Database
# =========================================================================


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def db_init() -> None:
    conn = db_connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY
        );
        CREATE TABLE IF NOT EXISTS bots (
            name TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            runtime TEXT NOT NULL,
            entry TEXT NOT NULL,
            pid INTEGER,
            status TEXT DEFAULT 'stopped',
            auto_restart INTEGER DEFAULT 1,
            started_at TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS oplog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            user_id INTEGER,
            action TEXT
        );
        CREATE TABLE IF NOT EXISTS login_state (
            user_id INTEGER PRIMARY KEY,
            attempts INTEGER DEFAULT 0,
            locked_until TEXT
        );
        """
    )
    # Backfill columns for databases created by earlier versions.
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(bots)")}
    if "started_at" not in existing_cols:
        conn.execute("ALTER TABLE bots ADD COLUMN started_at TEXT")

    if conn.execute("SELECT value FROM settings WHERE key='panel_password'").fetchone() is None:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('panel_password', ?)",
            (config.DEFAULT_PANEL_PASSWORD,),
        )
    if conn.execute("SELECT value FROM settings WHERE key='notifications'").fetchone() is None:
        conn.execute("INSERT INTO settings (key, value) VALUES ('notifications', '1')")
    conn.commit()
    conn.close()


def get_setting(key: str, default: str = "") -> str:
    conn = db_connect()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    conn = db_connect()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


def log_action(user_id: int, action: str) -> None:
    conn = db_connect()
    conn.execute(
        "INSERT INTO oplog (ts, user_id, action) VALUES (?, ?, ?)",
        (datetime.now().isoformat(timespec="seconds"), user_id, action),
    )
    conn.commit()
    conn.close()


def is_admin(user_id: int) -> bool:
    if user_id == config.OWNER_ID:
        return True
    conn = db_connect()
    row = conn.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row is not None


# =========================================================================
# Bot process management (DB helpers)
# =========================================================================

RUNTIME_ENTRY = {
    "python": ["python3", "{entry}"],
    "node": ["node", "{entry}"],
    "php": ["php", "{entry}"],
    "java": ["java", "-jar", "{entry}"],
}

RUNNING_PROCS: dict[str, subprocess.Popen] = {}
TERM_SHELLS: dict[int, "PersistentShell"] = {}


def detect_runtime(path: Path) -> tuple[str, str] | None:
    for f in path.rglob("*.py"):
        return "python", str(f.relative_to(path))
    for f in path.rglob("*.js"):
        return "node", str(f.relative_to(path))
    for f in path.rglob("*.php"):
        return "php", str(f.relative_to(path))
    for f in path.rglob("*.jar"):
        return "java", str(f.relative_to(path))
    return None


def db_upsert_bot(name, path, runtime, entry):
    conn = db_connect()
    conn.execute(
        "INSERT INTO bots (name, path, runtime, entry, status, created_at) "
        "VALUES (?, ?, ?, ?, 'stopped', ?) "
        "ON CONFLICT(name) DO UPDATE SET path=excluded.path, runtime=excluded.runtime, entry=excluded.entry",
        (name, path, runtime, entry, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


def db_get_bot(name: str):
    conn = db_connect()
    row = conn.execute("SELECT * FROM bots WHERE name=?", (name,)).fetchone()
    conn.close()
    return row


def db_all_bots():
    conn = db_connect()
    rows = conn.execute("SELECT * FROM bots ORDER BY name").fetchall()
    conn.close()
    return rows


def db_set_bot_status(name: str, status: str, pid: Optional[int]):
    conn = db_connect()
    started = datetime.now().isoformat(timespec="seconds") if status == "running" else None
    conn.execute(
        "UPDATE bots SET status=?, pid=?, started_at=COALESCE(?, started_at) WHERE name=?",
        (status, pid, started if status == "running" else None, name),
    )
    if status != "running":
        conn.execute("UPDATE bots SET started_at=NULL WHERE name=?", (name,))
    conn.commit()
    conn.close()


def db_delete_bot(name: str):
    conn = db_connect()
    conn.execute("DELETE FROM bots WHERE name=?", (name,))
    conn.commit()
    conn.close()


def db_rename_bot(old: str, new: str):
    conn = db_connect()
    conn.execute("UPDATE bots SET name=? WHERE name=?", (new, old))
    conn.commit()
    conn.close()


def db_toggle_autorestart(name: str) -> bool:
    conn = db_connect()
    row = conn.execute("SELECT auto_restart FROM bots WHERE name=?", (name,)).fetchone()
    new_val = 0 if row and row["auto_restart"] else 1
    conn.execute("UPDATE bots SET auto_restart=? WHERE name=?", (new_val, name))
    conn.commit()
    conn.close()
    return bool(new_val)


async def start_bot_process(name: str) -> str:
    row = db_get_bot(name)
    if row is None:
        return "❌ البوت غير موجود."
    existing = RUNNING_PROCS.get(name)
    if existing is not None:
        try:
            if existing.poll() is None:
                return "⚠️ البوت يعمل بالفعل."
            RUNNING_PROCS.pop(name, None)
        except Exception:
            RUNNING_PROCS.pop(name, None)
    if row["pid"] and psutil.pid_exists(row["pid"]):
        try:
            ps = psutil.Process(row["pid"])
            if ps.is_running() and ps.status() != psutil.STATUS_ZOMBIE:
                return "⚠️ البوت يعمل بالفعل."
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    template = RUNTIME_ENTRY[row["runtime"]]
    cmd = [part.format(entry=row["entry"]) for part in template]
    log_file = Path(row["path"]) / "bot.log"
    try:
        proc = await _run_blocking(_spawn_bot_sync, cmd, row["path"], str(log_file))
        RUNNING_PROCS[name] = proc
        db_set_bot_status(name, "running", proc.pid)
        return f"🟢 تم تشغيل {name} (PID {proc.pid})."
    except Exception as exc:
        return f"❌ فشل التشغيل: {exc}"

def _spawn_bot_sync(cmd: list[str], cwd: str, log_file: str):
    with open(log_file, "ab") as lf:
        return subprocess.Popen(cmd, cwd=cwd, stdout=lf, stderr=lf, start_new_session=True)

async def stop_bot_process(name: str) -> str:
    proc = RUNNING_PROCS.get(name)
    row = db_get_bot(name)
    pid = proc.pid if proc else (row["pid"] if row else None)
    if not pid:
        return "⚠️ البوت غير مشغل."
    try:
        alive = False
        if proc is not None:
            alive = proc.poll() is None
        else:
            try:
                ps = psutil.Process(pid)
                alive = ps.is_running() and ps.status() != psutil.STATUS_ZOMBIE
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                alive = False
        if alive:
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except Exception:
                try:
                    psutil.Process(pid).terminate()
                except Exception:
                    pass
            if proc is not None:
                try:
                    await _run_blocking(proc.wait, 5)
                except Exception:
                    try:
                        if proc.poll() is None:
                            os.killpg(os.getpgid(pid), signal.SIGKILL)
                    except Exception:
                        pass
        if proc is not None and proc.poll() is not None:
            RUNNING_PROCS.pop(name, None)
        else:
            RUNNING_PROCS.pop(name, None)
        db_set_bot_status(name, "stopped", None)
        return f"⏹️ تم إيقاف {name}."
    except Exception as exc:
        return f"❌ فشل إيقاف {name}: {exc}"


async def install_requirements(path: Path, runtime: str, force: bool = False) -> str:
    fingerprint = _dependency_fingerprint(path, runtime)
    cache = _load_dependency_cache()
    key = str(path.resolve())
    if fingerprint and not force and cache.get(key, {}).get("fingerprint") == fingerprint and cache.get(key, {}).get("success"):
        return "ℹ️ المتطلبات لم تتغير منذ آخر تثبيت ناجح؛ تم استخدام الـCache ولم تتم إعادة التثبيت."

    def _install():
        if runtime == "python" and (path / "requirements.txt").exists():
            return subprocess.run([sys.executable, "-m", "pip", "install", "--break-system-packages", "-r", "requirements.txt"], cwd=path, capture_output=True, text=True, timeout=300)
        if runtime == "node" and (path / "package.json").exists():
            cmd = ["npm", "ci"] if (path / "package-lock.json").exists() else ["npm", "install"]
            return subprocess.run(cmd, cwd=path, capture_output=True, text=True, timeout=300)
        return None

    try:
        r = await _run_blocking(_install)
        if r is None:
            return "(لا توجد متطلبات للتثبيت)"
        output = (r.stdout or "")[-1500:] + (r.stderr or "")[-1500:]
        if r.returncode == 0 and fingerprint:
            cache[key] = {"fingerprint": fingerprint, "runtime": runtime, "success": True, "updated_at": datetime.now().isoformat(timespec="seconds")}
            _save_dependency_cache(cache)
            return output or "✅ تم التحقق من المتطلبات بنجاح."
        return output or "❌ فشل تثبيت المتطلبات."
    except Exception as exc:
        return f"❌ فشل تثبيت المتطلبات: {exc}"


async def watchdog_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    for row in db_all_bots():
        name = row["name"]
        if row["status"] != "running":
            continue
        proc = RUNNING_PROCS.get(name)
        if proc is not None:
            rc = proc.poll()
            if rc is None:
                continue
            # Reap only after reading the exit code, so crash detection cannot
            # race with the reaper and lose the real return code.
            try:
                await _run_blocking(proc.wait)
            except Exception:
                pass
            RUNNING_PROCS.pop(name, None)
            if rc == 0:
                db_set_bot_status(name, "stopped", None)
                continue
            db_set_bot_status(name, "crashed", None)
            await notify_owner(context.application, f"⚠️ البوت {name} توقف بشكل غير متوقع (exit code {rc}).")
            if row["auto_restart"]:
                msg = await start_bot_process(name)
                await notify_owner(context.application, f"🔄 إعادة تشغيل تلقائي لـ {name}:\n{msg}")
            continue
        # Fallback for processes not present in memory after a restart.
        if row["pid"] and psutil.pid_exists(row["pid"]):
            try:
                ps = psutil.Process(row["pid"])
                if ps.is_running() and ps.status() != psutil.STATUS_ZOMBIE:
                    continue
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        db_set_bot_status(name, "crashed", None)
        await notify_owner(context.application, f"⚠️ البوت {name} توقف بشكل غير متوقع.")
        if row["auto_restart"]:
            msg = await start_bot_process(name)
            await notify_owner(context.application, f"🔄 إعادة تشغيل تلقائي لـ {name}:\n{msg}")


async def notify_owner(app: Application, text: str) -> None:
    if get_setting("notifications", "1") == "1":
        try:
            await app.bot.send_message(chat_id=config.OWNER_ID, text=text)
        except Exception:
            log.exception("Failed to notify owner")


# =========================================================================
# General helpers
# =========================================================================


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


def progress_bar(percent: float, width: int = 12) -> str:
    percent = max(0.0, min(100.0, percent))
    filled = round(width * percent / 100)
    return "▓" * filled + "░" * (width - filled) + f" {percent:.1f}%"


def trim_chunks(text: str, limit: int = config.MAX_OUTPUT_CHARS) -> list[str]:
    if not text:
        return ["(لا يوجد ناتج)"]
    return [text[i : i + limit] for i in range(0, len(text), limit)] or ["(لا يوجد ناتج)"]


def fmt_duration(seconds: float) -> str:
    return str(timedelta(seconds=int(seconds)))


# --- sandboxed path helpers (used for file manager root = FS_ROOT) -------


def resolve_under(root: str, rel_or_abs: str) -> Optional[Path]:
    base = Path(root).resolve()
    try:
        target = Path(rel_or_abs)
        target = target if target.is_absolute() else base / target
        target = target.resolve()
    except Exception:
        return None
    if base == target or base in target.parents:
        return target
    return None


def safe_child_name(name: str) -> Optional[str]:
    """Allow a single filename/folder/bot name only; reject path traversal."""
    name = (name or "").strip()
    if not name or name in {".", ".."} or "/" in name or "\\" in name or "\x00" in name:
        return None
    if Path(name).name != name:
        return None
    return name

def safe_extract_zip(zf: zipfile.ZipFile, destination: Path) -> None:
    base = destination.resolve()
    for member in zf.infolist():
        target = (base / member.filename).resolve()
        if target != base and base not in target.parents:
            raise ValueError(f"مسار ZIP غير آمن: {member.filename}")
    zf.extractall(base)

# =========================================================================
# Per-user session / navigation state
#
# We use context.user_data (persisted per chat by PTB) for all navigation
# state so different sections never bleed into each other.
# =========================================================================

AUTHENTICATED: set[int] = set()


def ud(context: ContextTypes.DEFAULT_TYPE) -> dict:
    d = context.user_data
    d.setdefault("stack", ["main"])
    d.setdefault("mode", None)          # None | "terminal" | "filemanager"
    d.setdefault("pending", None)       # name of awaited free-text input, if any
    d.setdefault("data", {})            # scratch data for the pending input
    d.setdefault("fm_root", config.FS_ROOT)
    d.setdefault("fm_path", config.FS_ROOT)
    d.setdefault("fm_listing", {})      # button label -> absolute path
    d.setdefault("fm_selected", None)
    d.setdefault("fm_clipboard", None)  # {"op": "copy"/"move", "path": str}
    d.setdefault("bot_selected", None)
    d.setdefault("cmd_history", [])
    d.setdefault("term_last", None)
    return d


def reset_pending(d: dict) -> None:
    d["pending"] = None
    d["data"] = {}


async def show(update: Update, text: str, markup) -> None:
    await update.message.reply_text(text, reply_markup=markup)


# =========================================================================
# Static-menu navigation
# =========================================================================

MENUS = {
    "main": (MAIN_MENU, "🏠 القائمة الرئيسية"),
    "settings": (SETTINGS_MENU, "⚙️ الإعدادات"),
    "backup": (BACKUP_MENU, "💾 النسخ الاحتياطي"),
}


def push_menu(d: dict, name: str) -> None:
    if d["stack"][-1] != name:
        d["stack"].append(name)


def pop_menu(d: dict) -> str:
    if len(d["stack"]) > 1:
        d["stack"].pop()
    return d["stack"][-1]


async def goto_static(update: Update, d: dict, name: str) -> None:
    d["mode"] = None
    push_menu(d, name)
    markup, title = MENUS[name]
    await show(update, title, markup)


# =========================================================================
# BOT MANAGEMENT (fully button-driven, no typing bot names)
# =========================================================================


def bots_list_menu() -> ReplyKeyboardMarkup:
    rows = []
    row = []
    for b in db_all_bots():
        dot = "🟢" if b["status"] == "running" else "🔴"
        row.append(f"{dot} {b['name']}")
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([BTN_BOT_NEW])
    return kb(rows)


def label_to_bot_name(label: str) -> Optional[str]:
    for dot in ("🟢 ", "🔴 "):
        if label.startswith(dot):
            return label[len(dot):]
    return None


async def open_bots_menu(update: Update, d: dict) -> None:
    d["mode"] = None
    d["bot_selected"] = None
    push_menu(d, "bots")
    await show(update, "🤖 إدارة البوتات — اختر بوتاً، أو ارفع بوتاً جديداً:", bots_list_menu())


async def return_to_bots_list(update: Update, d: dict) -> None:
    """Like open_bots_menu, but safe to call from a deeper screen (e.g. right
    after deleting a bot from its own detail page) without leaving a stray
    duplicate entry on the navigation stack."""
    if d["stack"] and d["stack"][-1] == "bot_detail":
        d["stack"].pop()
    d["mode"] = None
    d["bot_selected"] = None
    if not d["stack"] or d["stack"][-1] != "bots":
        d["stack"].append("bots")
    await show(update, "🤖 إدارة البوتات — اختر بوتاً، أو ارفع بوتاً جديداً:", bots_list_menu())


async def open_bot_detail(update: Update, d: dict, name: str) -> None:
    row = db_get_bot(name)
    if row is None:
        await update.message.reply_text("❌ هذا البوت لم يعد موجوداً.")
        await open_bots_menu(update, d)
        return
    d["bot_selected"] = name
    push_menu(d, "bot_detail")
    dot = "🟢 يعمل" if row["status"] == "running" else "🔴 متوقف"
    text = f"🤖 {name}\nالحالة: {dot}\nاللغة: {row['runtime']}\nإعادة التشغيل التلقائي: {'مفعلة' if row['auto_restart'] else 'معطلة'}"
    await show(update, text, BOT_DETAIL_MENU)


async def bot_usage_text(row) -> str:
    if row["pid"] and psutil.pid_exists(row["pid"]):
        try:
            pr = psutil.Process(row["pid"])
            cpu = await _run_blocking(pr.cpu_percent, 0.2)
            mem = pr.memory_percent()
            uptime = "-"
            if row["started_at"]:
                started = datetime.fromisoformat(row["started_at"])
                uptime = fmt_duration((datetime.now() - started).total_seconds())
            return (
                f"📊 استهلاك {row['name']}\n"
                f"الحالة: {row['status']}\nPID: {row['pid']}\n"
                f"CPU: {cpu:.1f}%\nRAM: {mem:.1f}%\n"
                f"مدة التشغيل: {uptime}\nاللغة: {row['runtime']}"
            )
        except Exception:
            pass
    return f"📊 {row['name']} غير مشغل حالياً."


# =========================================================================
# FILE MANAGER (fully button-driven; root = config.FS_ROOT or a bot's dir)
# =========================================================================


def dir_listing(root: str, path: str) -> dict[str, str]:
    """Returns {button_label: absolute_path} for entries in `path`."""
    p = Path(path)
    listing: dict[str, str] = {}
    try:
        entries = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    except Exception:
        return listing
    for e in entries[:100]:
        tag = "📁" if e.is_dir() else "📄"
        label = f"{tag} {e.name}"
        # de-duplicate identical labels (shouldn't normally happen)
        base_label = label
        i = 2
        while label in listing:
            label = f"{base_label} ({i})"
            i += 1
        listing[label] = str(e)
    return listing


def fm_menu(d: dict) -> ReplyKeyboardMarkup:
    rows = []
    row = []
    for label in d["fm_listing"]:
        row.append(label)
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    action_row = [FM_MKDIR, FM_UPLOAD_HERE]
    rows.append(action_row)
    rows.append([FM_SEARCH])
    if d.get("fm_clipboard"):
        rows.append([FM_PASTE])
    return kb(rows)


def return_to_filemanager(d: dict) -> None:
    """Pop any action/search frames off the stack and land back on a single
    normalized 'filemanager' frame — regardless of whether the action was
    entered from the normal listing or from a search-results screen."""
    while d["stack"] and d["stack"][-1] in ("file_actions", "dir_actions", "search_results"):
        d["stack"].pop()
    if not d["stack"] or d["stack"][-1] != "filemanager":
        d["stack"].append("filemanager")


async def open_file_manager(update: Update, d: dict, root: str, title: str) -> None:
    d["mode"] = "filemanager"
    d["fm_root"] = root
    d["fm_path"] = root
    d["fm_clipboard"] = None
    push_menu(d, "filemanager")
    await render_fm(update, d, title)


async def render_fm(update: Update, d: dict, title: Optional[str] = None) -> None:
    d["fm_listing"] = dir_listing(d["fm_root"], d["fm_path"])
    rel = os.path.relpath(d["fm_path"], d["fm_root"])
    loc = "/" if rel == "." else f"/{rel}"
    header = title or f"📁 {loc}"
    if not d["fm_listing"]:
        header += "\n(المجلد فارغ)"
    await show(update, header, fm_menu(d))


async def open_file_actions(update: Update, d: dict, path: str) -> None:
    d["fm_selected"] = path
    push_menu(d, "file_actions")
    p = Path(path)
    size = human_size(p.stat().st_size) if p.exists() and p.is_file() else ""
    await show(update, f"📄 {p.name} {size}", FILE_ACTION_MENU)


async def open_dir_actions(update: Update, d: dict, path: str) -> None:
    d["fm_selected"] = path
    push_menu(d, "dir_actions")
    await show(update, f"📁 {Path(path).name}", DIR_ACTION_MENU)


async def fm_search(update: Update, d: dict, term: str) -> None:
    base = Path(d["fm_root"])
    matches = []
    for root, _, files in os.walk(base):
        for name in files:
            if term.lower() in name.lower():
                matches.append(str(Path(root) / name))
        if len(matches) >= 40:
            break
    if not matches:
        await update.message.reply_text("لا توجد نتائج مطابقة.")
        await render_fm(update, d)
        return
    listing = {}
    rows = []
    row = []
    for m in matches[:40]:
        label = f"📄 {Path(m).name}"
        base_label = label
        i = 2
        while label in listing:
            label = f"{base_label} ({i})"
            i += 1
        listing[label] = m
        row.append(label)
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    d["fm_listing"] = listing
    push_menu(d, "search_results")
    await update.message.reply_text(f"🔍 نتائج البحث عن «{term}»:", reply_markup=kb(rows))


# =========================================================================
# TERMINAL MODE
# =========================================================================
#
# A real, persistent /bin/bash process is kept alive per user for the whole
# duration of their Terminal session (from entering Terminal mode until they
# leave it). Every command they send is written to that same shell's stdin,
# so `cd`, `export`, `alias` and any other state-changing command behaves
# exactly like a real SSH session: the working directory and environment
# carry over to the next command. The shell is only killed when the user
# explicitly exits Terminal mode (Back/Home) — never mid-session.


class PersistentShell:
    """One real bash process per user, reused across commands."""

    # Marker used to detect the end of a command's output in the shared
    # stdout/stderr stream, and to recover the exit code + new cwd after it.
    _SEP = "\x1e"

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.lock = asyncio.Lock()
        self.busy = False
        self.cwd = config.SERVER_PATH

    async def _spawn(self) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            "/bin/bash", "--noprofile", "--norc",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=config.SERVER_PATH,
            preexec_fn=os.setsid,
        )
        # Enable alias expansion, which bash disables by default for
        # non-interactive/piped shells.
        init = "shopt -s expand_aliases\n"
        self.proc.stdin.write(init.encode())
        await self.proc.stdin.drain()
        self.cwd = config.SERVER_PATH

    async def ensure_alive(self) -> None:
        if self.proc is None or self.proc.returncode is not None:
            await self._spawn()

    async def stop(self) -> None:
        if self.proc and self.proc.returncode is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            except Exception:
                pass
        self.proc = None

    def interrupt(self) -> bool:
        """Sends SIGINT to the running child process(es) of the shell only
        (e.g. the `ping`/`sleep`/`git` currently executing) — never to the
        bash process itself, so the persistent session survives."""
        if not self.proc or self.proc.returncode is not None:
            return False
        try:
            parent = psutil.Process(self.proc.pid)
            children = parent.children(recursive=True)
        except Exception:
            return False
        if not children:
            return False
        signaled = False
        for child in children:
            try:
                child.send_signal(signal.SIGINT)
                signaled = True
            except Exception:
                pass
        return signaled

    async def run(self, command: str, timeout: int) -> tuple[str, Optional[int], bool]:
        """Runs `command` in the persistent shell.
        Returns (output_text, exit_code_or_None, timed_out)."""
        async with self.lock:
            await self.ensure_alive()
            token = f"__XSHELLZ_{uuid.uuid4().hex}__"
            marker_cmd = (
                f"\nprintf '\\n%s{self._SEP}%s{self._SEP}%s\\n' "
                f"\"{token}\" \"$?\" \"$PWD\"\n"
            )
            try:
                self.proc.stdin.write(command.encode() + marker_cmd.encode())
                await self.proc.stdin.drain()
            except Exception:
                await self.stop()
                await self.ensure_alive()
                return "❌ انتهت جلسة الشيل بشكل غير متوقع، تم إنشاء جلسة جديدة.", None, False

            self.busy = True
            buf = b""
            start_t = time.monotonic()
            try:
                while True:
                    remaining = timeout - (time.monotonic() - start_t)
                    if remaining <= 0:
                        self.interrupt()
                        return buf.decode(errors="replace"), None, True
                    try:
                        line = await asyncio.wait_for(self.proc.stdout.readline(), timeout=remaining)
                    except asyncio.TimeoutError:
                        continue
                    if not line:
                        # shell process died unexpectedly
                        await self.stop()
                        return buf.decode(errors="replace"), None, False
                    text = line.decode(errors="replace")
                    if token in text:
                        parts = text.strip("\n").split(self._SEP)
                        if len(parts) == 3:
                            _, code_str, new_cwd = parts
                            self.cwd = new_cwd.strip() or self.cwd
                            try:
                                exit_code = int(code_str)
                            except ValueError:
                                exit_code = None
                            return buf.decode(errors="replace"), exit_code, False
                        # marker malformed, treat as regular output
                    buf += line
            finally:
                self.busy = False


def get_shell(user_id: int) -> PersistentShell:
    shell = TERM_SHELLS.get(user_id)
    if shell is None:
        shell = PersistentShell(user_id)
        TERM_SHELLS[user_id] = shell
    return shell


async def exit_terminal_session(user_id: int) -> None:
    shell = TERM_SHELLS.pop(user_id, None)
    if shell:
        await shell.stop()


async def enter_terminal(update: Update, d: dict) -> None:
    d["mode"] = "terminal"
    push_menu(d, "terminal")
    shell = get_shell(update.effective_user.id)
    await shell.ensure_alive()
    await show(
        update,
        f"💻 وضع التريمنال مفعّل — جلسة مستمرة (مثل SSH).\n📍 {shell.cwd}\n\n"
        "أرسل أي أمر Linux وسيتم تنفيذه، وسيحتفظ بمكانك (cd) والمتغيرات (export) بين الأوامر.\n"
        "استخدم ⏹️ Ctrl+C لإيقاف عملية طويلة، ورجوع/الرئيسية لإنهاء الجلسة والخروج.",
        TERMINAL_MENU,
    )


async def run_terminal_command(update: Update, context: ContextTypes.DEFAULT_TYPE, d: dict, command: str) -> None:
    user_id = update.effective_user.id
    d["cmd_history"].append(command)
    d["cmd_history"] = d["cmd_history"][-10:]
    log_action(user_id, f"terminal: {command}")

    shell = get_shell(user_id)
    start_t = time.perf_counter()
    output_text, exit_code, timed_out = await shell.run(command, config.COMMAND_TIMEOUT)
    elapsed = time.perf_counter() - start_t

    if timed_out:
        await update.message.reply_text(
            f"⏱️ انتهت المهلة ({config.COMMAND_TIMEOUT} ثانية) وتم إيقاف الأمر الحالي فقط.\n"
            "الجلسة نفسها ما زالت مفتوحة ويمكنك إرسال أمر جديد."
        )
        return

    if exit_code is None and not output_text:
        await update.message.reply_text(output_text or "❌ حدث خطأ غير متوقع في الجلسة.")
        return

    footer = f"⏱️ {elapsed:.2f}ث | 🔚 Exit: {exit_code} | 📍 {shell.cwd}"
    full_plain = f"$ {command}\n\n{output_text}\n\n{footer}"
    d["term_last"] = full_plain

    body = f"$ {command}\n\n{output_text}"
    # Send command + output as ONE message whenever it fits; only split when
    # it exceeds Telegram's limits, and keep the timing/exit-code footer
    # attached to that single message when possible.
    if len(body) + len(footer) + 20 <= config.MAX_OUTPUT_CHARS:
        await update.message.reply_text(
            f"```\n{body}\n```\n{footer}", parse_mode=ParseMode.MARKDOWN
        )
    else:
        chunks = trim_chunks(body)
        for i, chunk in enumerate(chunks):
            prefix = f"[{i+1}/{len(chunks)}]\n"
            await update.message.reply_text(f"{prefix}```\n{chunk}\n```", parse_mode=ParseMode.MARKDOWN)
        await update.message.reply_text(footer)


async def terminal_ctrlc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    shell = TERM_SHELLS.get(user_id)
    if not shell or not shell.busy:
        await update.message.reply_text("لا توجد عملية قيد التشغيل حالياً.")
        return
    if shell.interrupt():
        await update.message.reply_text("⏹️ تم إرسال Ctrl+C للعملية الحالية.")
    else:
        await update.message.reply_text("❌ تعذر إيقاف العملية.")


# =========================================================================
# Cleaning
# =========================================================================


async def clean_server(update: Update) -> None:
    start_t = time.perf_counter()
    freed = 0
    removed = 0
    now = time.time()

    # 1) walk the data dir + /tmp removing caches/pyc/pycache/empty/old logs
    targets = [Path(config.SERVER_PATH), Path("/tmp")]
    for base in targets:
        if not base.exists():
            continue
        for root, dirs, files in os.walk(base, topdown=True):
            if "backups" in Path(root).parts and base == Path(config.SERVER_PATH):
                # never touch backups during cleanup
                if Path(root) == Path(config.BACKUPS_DIR):
                    dirs[:] = []
                    continue
            if "__pycache__" in dirs:
                pcache = Path(root) / "__pycache__"
                try:
                    freed += sum(f.stat().st_size for f in pcache.rglob("*") if f.is_file())
                    shutil.rmtree(pcache, ignore_errors=True)
                    removed += 1
                except Exception:
                    pass
                dirs.remove("__pycache__")
            for name in list(files):
                fp = Path(root) / name
                try:
                    st = fp.stat()
                except (FileNotFoundError, PermissionError):
                    continue
                is_pyc = name.endswith(".pyc")
                is_empty = st.st_size == 0
                is_old_log = name.endswith(".log") and (now - st.st_mtime) > 30 * 86400
                is_temp = name.endswith((".tmp", ".tmp.zip", ".part", ".cache"))
                if is_pyc or is_empty or is_old_log or is_temp:
                    try:
                        freed += st.st_size
                        fp.unlink(missing_ok=True)
                        removed += 1
                    except Exception:
                        pass

    # 2) pip cache
    try:
        subprocess.run(["pip", "cache", "purge"], capture_output=True, timeout=60)
    except Exception:
        pass

    # 3) npm cache (optional, ignore failures if npm isn't installed)
    try:
        subprocess.run(["npm", "cache", "clean", "--force"], capture_output=True, timeout=60)
    except Exception:
        pass

    elapsed = time.perf_counter() - start_t
    await update.message.reply_text(
        f"🧹 اكتمل التنظيف الحقيقي.\n"
        f"عدد الملفات المحذوفة: {removed}\n"
        f"المساحة المحررة: {human_size(freed)}\n"
        f"مدة التنفيذ: {elapsed:.2f} ثانية\n"
        f"(تم أيضاً تنظيف pip cache و npm cache إن وُجدا)"
    )


# =========================================================================
# Server refresh (non-destructive) & dependency management
# =========================================================================


async def refresh_server(update: Update) -> None:
    """A safe, non-destructive 'refresh' of the panel's own runtime state.
    Never deletes files, libraries, settings, bots, or databases."""
    start_t = time.perf_counter()
    report = []

    try:
        subprocess.run(["sync"], timeout=10, capture_output=True)
        report.append("✅ تمت مزامنة نظام الملفات (sync)")
    except Exception:
        report.append("⚠️ تعذر تنفيذ sync (قد يتطلب صلاحيات إضافية)")

    fixed = 0
    for row in db_all_bots():
        if row["status"] == "running" and row["pid"] and not psutil.pid_exists(row["pid"]):
            db_set_bot_status(row["name"], "stopped", None)
            fixed += 1
    report.append(
        f"✅ تمت مزامنة حالة {fixed} بوت مع العمليات الفعلية" if fixed
        else "✅ حالة جميع البوتات متطابقة مع العمليات الفعلية"
    )

    restarted = 0
    for row in db_all_bots():
        if row["status"] == "crashed" and row["auto_restart"]:
            msg = await start_bot_process(row["name"])
            if msg.startswith("✅"):
                restarted += 1
    report.append(
        f"✅ تم إعادة تشغيل {restarted} بوت كان متعطلاً" if restarted
        else "✅ لا توجد بوتات متعطلة تحتاج إعادة تشغيل"
    )

    stale = [uid for uid, s in TERM_SHELLS.items() if s.proc is not None and s.proc.returncode is not None]
    for uid in stale:
        TERM_SHELLS.pop(uid, None)
    report.append(
        f"✅ تم تنظيف {len(stale)} جلسة تريمنال منتهية" if stale
        else "✅ لا توجد جلسات تريمنال معلّقة"
    )

    psutil.cpu_percent(interval=None)  # reset internal baseline for fresh readings
    report.append("✅ تم تحديث قراءات المعالج والموارد")

    elapsed = time.perf_counter() - start_t
    await update.message.reply_text(
        "🔄 تقرير تحديث السيرفر (بدون حذف أي بيانات):\n\n" + "\n".join(report) +
        f"\n\n⏱️ مدة التنفيذ: {elapsed:.2f} ثانية"
    )


def project_requirements_path() -> Path:
    return Path(__file__).resolve().parent / "requirements.txt"


def parse_requirements(path: Path) -> list[tuple[str, Optional[str]]]:
    reqs: list[tuple[str, Optional[str]]] = []
    if not path.exists():
        return reqs
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "==" in line:
            pkg, ver = line.split("==", 1)
            reqs.append((pkg.strip(), ver.strip()))
        else:
            pkg = line
            for sep in ("[", ">=", "<=", "!=", ">", "<"):
                pkg = pkg.split(sep)[0]
            reqs.append((pkg.strip(), None))
    return reqs


def check_environment() -> list[tuple[str, Optional[str], str, Optional[str]]]:
    """Returns (package, required_version_or_None, status, installed_version_or_None).
    status is one of: 'installed', 'update', 'missing'."""
    results = []
    for pkg, ver in parse_requirements(project_requirements_path()):
        try:
            installed_ver = importlib_metadata.version(pkg)
        except importlib_metadata.PackageNotFoundError:
            results.append((pkg, ver, "missing", None))
            continue
        if ver and installed_ver != ver:
            results.append((pkg, ver, "update", installed_ver))
        else:
            results.append((pkg, ver, "installed", installed_ver))
    return results


async def update_dependencies() -> str:
    """Check/install panel dependencies using a persistent content hash cache.
    A successful install is the only event that updates the cache."""
    results = check_environment()
    to_install = [r for r in results if r[2] != "installed"]
    project = Path(config.SERVER_PATH)
    fingerprint = _dependency_fingerprint(project, "python")
    cache = _load_dependency_cache()
    key = str(project.resolve()) + ":panel-python"
    if not to_install and fingerprint and cache.get(key, {}).get("fingerprint") == fingerprint and cache.get(key, {}).get("success"):
        return f"ℹ️ تم فحص {len(results)} مكتبة\n✅ المتطلبات مطابقة للـCache\n✅ لا توجد حاجة لإعادة التثبيت"

    if not to_install:
        if fingerprint:
            cache[key] = {"fingerprint": fingerprint, "runtime": "python", "success": True, "updated_at": datetime.now().isoformat(timespec="seconds")}
            _save_dependency_cache(cache)
        return f"✅ تم فحص {len(results)} مكتبة\n✅ كل المكتبات محدثة\n✅ لا توجد أخطاء"

    report = await install_requirements(project, "python", force=True)
    if report.startswith("❌"):
        return f"❌ فشل تحديث المكتبات\n{report}"
    return f"✅ تم فحص {len(results)} مكتبة\n{report}"


async def send_env_check(update: Update) -> None:
    results = check_environment()
    icon = {"installed": "✅ مثبتة", "update": "⬆ تحتاج تحديث", "missing": "❌ غير مثبتة"}
    lines = [
        f"Python: {platform.python_version()}",
        f"pip: {get_version(['pip', '--version'])}",
        "",
        "📦 المكتبات المطلوبة:",
    ]
    if not results:
        lines.append("(لم يتم العثور على requirements.txt)")
    for pkg, ver, status, installed_ver in results:
        extra = f" (الحالي: {installed_ver})" if installed_ver else ""
        lines.append(f"• {pkg}{f' {ver}' if ver else ''}: {icon[status]}{extra}")
    await update.message.reply_text("\n".join(lines))


async def restart_bot_process(update: Update) -> None:
    await update.message.reply_text("🔁 جاري إعادة تشغيل البوت...")
    python = sys.executable
    os.execv(python, [python] + sys.argv)


async def post_init(app: Application) -> None:
    """Runs once on startup: auto-checks/installs missing or mismatched
    dependencies from requirements.txt and notifies the owner of the result."""
    try:
        results = check_environment()
        missing_or_stale = [r for r in results if r[2] != "installed"]
        if missing_or_stale:
            report = await update_dependencies()
            await notify_owner(app, f"📦 فحص تلقائي عند بدء التشغيل:\n{report}")
    except Exception as exc:  # noqa: BLE001
        try:
            await app.bot.send_message(chat_id=config.OWNER_ID, text=f"⚠️ خطأ أثناء الفحص التلقائي للمكتبات: {exc}")
        except Exception:
            pass


# =========================================================================
# Server info / monitoring
# =========================================================================


def get_version(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        out = (r.stdout or r.stderr).strip()
        return out.splitlines()[0] if out else "غير مثبت"
    except Exception:
        return "غير مثبت"


def get_external_ip() -> str:
    try:
        with urllib.request.urlopen(config.EXTERNAL_IP_SERVICE, timeout=4) as resp:
            return resp.read().decode().strip()
    except Exception:
        return "غير متاح"


async def build_server_info_text() -> str:
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage(config.FS_ROOT if os.path.exists(config.FS_ROOT) else "/")
    uptime = fmt_duration(time.time() - psutil.boot_time())
    boot_time = datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S")
    try:
        load1, load5, load15 = os.getloadavg()
        load_txt = f"{load1:.2f} / {load5:.2f} / {load15:.2f}"
    except (AttributeError, OSError):
        load_txt = "غير متاح"
    external_ip = get_external_ip()
    try:
        local_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        local_ip = "غير معروف"

    return (
        f"🖥️ *معلومات السيرفر*\n\n"
        f"نظام التشغيل: {platform.system()} {platform.release()}\n"
        f"الإصدار: {platform.version()[:60]}\n"
        f"عدد الأنوية: {psutil.cpu_count(logical=True)}\n"
        f"Load Average: {load_txt}\n\n"
        f"CPU: {progress_bar(psutil.cpu_percent(interval=0.3))}\n"
        f"RAM: {progress_bar(mem.percent)} ({human_size(mem.used)}/{human_size(mem.total)})\n"
        f"Disk: {progress_bar(disk.percent)} ({human_size(disk.used)}/{human_size(disk.total)})\n"
        f"المساحة الحرة: {human_size(disk.free)}\n\n"
        f"Uptime: {uptime}\n"
        f"آخر إقلاع (Restart): {boot_time}\n\n"
        f"Python: {platform.python_version()}\n"
        f"PHP: {get_version(['php', '-v'])}\n"
        f"Node: {get_version(['node', '-v'])}\n"
        f"Java: {get_version(['java', '-version'])}\n\n"
        f"Hostname: {socket.gethostname()}\n"
        f"IP المحلي: {local_ip}\n"
        f"IP الخارجي: {external_ip}"
    )


def server_info_menu() -> ReplyKeyboardMarkup:
    return kb([[INFO_REFRESH, INFO_COPY]])


async def send_server_info(update: Update) -> None:
    text = await build_server_info_text()
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=server_info_menu())


def monitor_menu() -> ReplyKeyboardMarkup:
    rows = []
    row = []
    for b in db_all_bots():
        dot = "🟢" if b["status"] == "running" else "🔴"
        row.append(f"{dot} {b['name']}")
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([MON_REFRESH])
    return kb(rows)


_NET_BASELINE: Optional[tuple[float, int, int]] = None

async def live_network_rate() -> tuple[float, float]:
    global _NET_BASELINE
    now = time.monotonic()
    net = psutil.net_io_counters()
    current = (now, net.bytes_sent, net.bytes_recv)
    if _NET_BASELINE is None:
        _NET_BASELINE = current
        return 0.0, 0.0
    old_t, old_up, old_down = _NET_BASELINE
    _NET_BASELINE = current
    dt = max(0.001, now - old_t)
    return max(0, net.bytes_sent - old_up) / dt, max(0, net.bytes_recv - old_down) / dt

async def build_monitor_text() -> str:
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk_root = config.FS_ROOT if os.path.exists(config.FS_ROOT) else "/"
    disk = psutil.disk_usage(disk_root)
    up_bps, down_bps = await live_network_rate()
    uptime = fmt_duration(time.time() - psutil.boot_time())
    try:
        load = os.getloadavg()
        load_txt = " / ".join(f"{x:.2f}" for x in load)
    except (AttributeError, OSError):
        load_txt = "غير متاح"
    cpu = await _run_blocking(psutil.cpu_percent, 0.05)
    process_count = len(psutil.pids())
    thread_count = 0
    for proc in psutil.process_iter(["num_threads"]):
        try:
            thread_count += proc.info.get("num_threads") or 0
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    lines = [
        "📊 *مراقبة الموارد*\n",
        f"CPU: {progress_bar(cpu)}",
        f"RAM: {progress_bar(mem.percent)} ({human_size(mem.used)}/{human_size(mem.total)})",
        f"Disk: {progress_bar(disk.percent)} ({human_size(disk.used)}/{human_size(disk.total)})",
        f"المساحة الحرة: {human_size(disk.free)}",
        f"Swap: {progress_bar(swap.percent)} ({human_size(swap.used)}/{human_size(swap.total)})",
        f"Swap Free: {human_size(swap.free)}",
        f"Load Average: {load_txt}",
        f"Processes: {process_count} | Threads: {thread_count}",
        f"Network: ⬆ {human_size(up_bps)}/s | ⬇ {human_size(down_bps)}/s",
        f"Uptime: {uptime}\n",
        "🤖 *البوتات النشطة*",
    ]
    rows = db_all_bots()
    if not rows:
        lines.append("لا توجد بوتات مضافة حتى الآن. أضف بوتاً من قسم «🤖 إدارة البوتات».")
    else:
        for r in rows:
            if r["pid"] and psutil.pid_exists(r["pid"]):
                try:
                    pr = psutil.Process(r["pid"])
                    cpu = await _run_blocking(pr.cpu_percent, 0.05)
                    ram = pr.memory_percent()
                    up = "-"
                    if r["started_at"]:
                        up = fmt_duration((datetime.now() - datetime.fromisoformat(r["started_at"])).total_seconds())
                    status_label = {"running": "🟢 يعمل", "crashed": "🔴 انهار", "stopped": "⚪ متوقف"}.get(r["status"], r["status"])
                    lines.append(f"• {r['name']} [{r['runtime']}] {status_label} | PID {r['pid']} | CPU {cpu:.1f}% | RAM {ram:.1f}% | {up}")
                    continue
                except Exception:
                    pass
            lines.append(f"• {r['name']} [{r['runtime']}] 🔴 متوقف")
    return "\n".join(lines)


async def send_monitor(update: Update) -> None:
    text = await build_monitor_text()
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=monitor_menu())


async def send_oplog(update: Update) -> None:
    conn = db_connect()
    rows = conn.execute("SELECT * FROM oplog ORDER BY id DESC LIMIT 30").fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("لا يوجد سجل عمليات بعد.")
        return
    lines = [f"[{r['ts']}] user {r['user_id']}: {r['action']}" for r in rows]
    for chunk in trim_chunks("\n".join(lines)):
        await update.message.reply_text(chunk)


# =========================================================================
# Backups
# =========================================================================


async def create_backup(update: Update) -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(config.BACKUPS_DIR) / f"backup_{ts}.zip"
    base = Path(config.SERVER_PATH)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(base):
            if Path(root) == Path(config.BACKUPS_DIR) or Path(config.BACKUPS_DIR) in Path(root).parents:
                dirs[:] = []
                continue
            for name in files:
                full = Path(root) / name
                zf.write(full, full.relative_to(base))
    await update.message.reply_text(f"✅ تم إنشاء نسخة احتياطية: {out.name}")


async def restore_backup(update: Update, name: str) -> None:
    src = Path(config.BACKUPS_DIR) / name
    if not src.exists():
        await update.message.reply_text("❌ الملف غير موجود.")
        return
    try:
        with zipfile.ZipFile(src) as zf:
            safe_extract_zip(zf, Path(config.SERVER_PATH))
        await update.message.reply_text("✅ تمت الاستعادة.")
    except Exception as exc:
        await update.message.reply_text(f"❌ فشلت الاستعادة: {exc}")


async def send_backup(update: Update, name: str) -> None:
    src = Path(config.BACKUPS_DIR) / name
    if not src.exists():
        await update.message.reply_text("❌ الملف غير موجود.")
        return
    with open(src, "rb") as f:
        await update.message.reply_document(f, filename=src.name)


def list_backup_files() -> list[str]:
    base = Path(config.BACKUPS_DIR)
    if not base.exists():
        return []
    files = [f for f in base.iterdir() if f.is_file() and f.suffix == ".zip"]
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return [f.name for f in files]


async def render_backup_list(update: Update, d: dict, purpose: str) -> None:
    """purpose: 'restore' or 'send'. Shows existing backups as buttons — no
    filename ever has to be typed."""
    d["data"]["backup_purpose"] = purpose
    files = list_backup_files()
    title = "♻️ استعادة نسخة احتياطية" if purpose == "restore" else "📤 إرسال نسخة احتياطية"
    if not files:
        d["data"]["backup_files"] = {}
        await show(update, f"{title}\n\nلا توجد نسخ احتياطية بعد. أنشئ واحدة من «💾 إنشاء نسخة احتياطية».", BACKUP_MENU)
        return
    labels: dict[str, str] = {}
    rows: list[list[str]] = []
    row: list[str] = []
    for name in files:
        label = f"💾 {name}"
        labels[label] = name
        row.append(label)
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    d["data"]["backup_files"] = labels
    hint = "اختر نسخة للاستعادة منها:" if purpose == "restore" else "اختر نسخة لإرسالها:"
    await show(update, f"{title}\n\n{hint}", kb(rows))


# =========================================================================
# GitHub project auto-updater
# =========================================================================
#
# No project path is ever typed by the user — projects are discovered by
# scanning for `.git` directories under the panel's own folder, the bots
# directory, and the file-manager root. Update flow is deliberately
# non-destructive: fetch first (read-only), bail out with "already
# up to date" if there's nothing new, and if the repo has unsaved local
# changes AND there's something to pull, stop and ask for explicit
# confirmation before doing anything (git stash, never reset --hard).

GIT_SCAN_MAX_DEPTH = 5
GIT_SCAN_SKIP_DIRS = {
    "node_modules", "__pycache__", "venv", ".venv", "env",
    ".cache", ".npm", "dist", "build", ".idea", ".vscode",
}


def discover_git_projects() -> dict[str, Path]:
    """Returns {display_label: repo_path} for every git repo found under the
    panel's own directory, the managed-bots directory and the file-manager
    root (deduplicated). Nested repos (e.g. a sub-project cloned inside
    another project's folder) are found too."""
    roots = [Path(__file__).resolve().parent, Path(config.BOTS_DIR), Path(config.FS_ROOT)]
    found: dict[Path, Path] = {}
    visited = 0
    MAX_VISITED = 20000

    def walk(base: Path, depth_left: int) -> None:
        nonlocal visited
        if visited > MAX_VISITED:
            return
        visited += 1
        try:
            if not base.is_dir() or base.is_symlink():
                return
            resolved = base.resolve()
        except OSError:
            return
        if (base / ".git").exists():
            found[resolved] = base
        if depth_left <= 0:
            return
        try:
            entries = list(base.iterdir())
        except (PermissionError, OSError):
            return
        for e in entries:
            name = e.name
            if name == ".git" or name in GIT_SCAN_SKIP_DIRS or name.startswith("."):
                continue
            walk(e, depth_left - 1)

    seen_roots: set[Path] = set()
    for root in roots:
        try:
            rr = root.resolve()
        except OSError:
            continue
        if rr in seen_roots:
            continue
        seen_roots.add(rr)
        walk(root, GIT_SCAN_MAX_DEPTH)

    labels: dict[str, Path] = {}
    for path in sorted(found.values(), key=lambda p: p.name.lower()):
        label = f"📦 {path.name}"
        base_label = label
        i = 2
        while label in labels:
            label = f"{base_label} ({i})"
            i += 1
        labels[label] = path
    return labels


def _scrub_git_output(text: str) -> str:
    """Strips any credentials that might be embedded in a remote URL
    (https://user:token@host/...) out of git's own output before it is ever
    shown to the user or written to logs."""
    return re.sub(r"https://[^\s@/]+:[^\s@/]+@", "https://***:***@", text)


async def _git_run(args: list[str], cwd: Path, timeout: int = 60) -> tuple[int, str]:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"  # never hang waiting for a username/password prompt
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=str(cwd), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
    except Exception as exc:
        return -1, str(exc)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return -1, "⏱️ انتهت المهلة"
    return proc.returncode, _scrub_git_output(out.decode(errors="replace"))


def _file_hash(p: Path) -> Optional[str]:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except Exception:
        return None


async def _restart_managed_bot_if_any(resolved_path: Path) -> Optional[str]:
    for row in db_all_bots():
        try:
            if Path(row["path"]).resolve() != resolved_path:
                continue
        except Exception:
            continue
        if row["status"] == "running":
            await stop_bot_process(row["name"])
            msg = await start_bot_process(row["name"])
            return "✅ تمت إعادة تشغيل المشروع" if msg.startswith("✅") else f"⚠️ تعذرت إعادة تشغيل المشروع تلقائياً: {msg}"
        return "ℹ️ المشروع غير مُشغّل حالياً، لم تتم إعادة تشغيله"
    return None


async def perform_git_update(path: Path, allow_stash: bool = False) -> tuple[str, bool, bool]:
    """Returns (report_text, needs_dirty_confirmation, self_restart_needed)."""
    if not (path / ".git").exists():
        return "❌ هذا المجلد ليس مستودع Git.", False, False

    code, fetch_out = await _git_run(["git", "fetch", "--quiet"], path, timeout=90)
    if code != 0:
        return f"❌ فشل تحديث المشروع\nتعذر الاتصال بـ GitHub (git fetch):\n{fetch_out.strip()[:300]}", False, False

    code, branch_out = await _git_run(["git", "rev-parse", "--abbrev-ref", "HEAD"], path, timeout=15)
    branch = branch_out.strip() or "HEAD"

    code, cmp_out = await _git_run(
        ["git", "rev-list", "--left-right", "--count", f"HEAD...origin/{branch}"], path, timeout=15
    )
    behind = 0
    if code == 0:
        parts = cmp_out.strip().split()
        if len(parts) == 2:
            behind = int(parts[1])

    if behind == 0:
        return "ℹ️ المشروع محدث بالفعل، لا توجد تحديثات جديدة على GitHub.", False, False

    code, status_out = await _git_run(["git", "status", "--porcelain"], path, timeout=20)
    if code != 0:
        return f"❌ فشل فحص حالة Git:\n{status_out.strip()[:300]}", False, False
    dirty = bool(status_out.strip())

    if dirty and not allow_stash:
        return (
            f"⚠️ يوجد تحديث جديد على GitHub لهذا المشروع، لكن توجد أيضاً تعديلات محلية لم تُحفظ بعد.\n"
            "لن يتم سحب أي تحديث حتى تؤكد، حتى لا تُفقد تعديلاتك.\n"
            "عند التأكيد: سيتم حفظ تعديلاتك مؤقتاً (git stash) قبل التحديث، ثم إرجاعها تلقائياً بعده.",
            True, False,
        )

    report = []
    stashed = False
    if dirty and allow_stash:
        code, stash_out = await _git_run(["git", "stash", "push", "-u", "-m", "xshellz-auto-update"], path, timeout=30)
        if code != 0:
            return f"❌ فشل تحديث المشروع\nتعذر حفظ التعديلات المحلية (git stash):\n{stash_out.strip()[:300]}", False, False
        stashed = True

    old_req_hash = _file_hash(path / "requirements.txt")
    old_pkg_hash = _file_hash(path / "package.json")

    code, pull_out = await _git_run(["git", "pull", "--ff-only", "origin", branch], path, timeout=120)
    if code != 0:
        if stashed:
            await _git_run(["git", "stash", "pop"], path, timeout=30)
        return f"❌ فشل تحديث المشروع\nتعذر تنفيذ git pull (قد يحتاج دمجاً يدوياً):\n{pull_out.strip()[:300]}", False, False
    report.append("✅ تم تحديث Git")

    if stashed:
        code, pop_out = await _git_run(["git", "stash", "pop"], path, timeout=30)
        if code != 0:
            report.append(
                "⚠️ حدث تعارض عند إرجاع تعديلاتك المحلية بعد التحديث.\n"
                "تعديلاتك محفوظة بأمان ولم تُحذف — راجعها من التريمنال بأمر: git stash list"
            )
        else:
            report.append("✅ تم إرجاع تعديلاتك المحلية بعد التحديث")

    new_req_hash = _file_hash(path / "requirements.txt")
    new_pkg_hash = _file_hash(path / "package.json")

    if new_req_hash and new_req_hash != old_req_hash:
        report.append(await install_requirements(path, "python", force=True))

    if new_pkg_hash and new_pkg_hash != old_pkg_hash:
        report.append(await install_requirements(path, "node", force=True))

    self_restart = False
    resolved = path.resolve()
    if resolved == Path(__file__).resolve().parent:
        report.append("🔁 سيتم إعادة تشغيل لوحة التحكم الآن لتطبيق التحديث...")
        self_restart = True
    else:
        note = await _restart_managed_bot_if_any(resolved)
        if note:
            report.append(note)

    return "✅ تم تحديث المشروع\n" + "\n".join(report), False, self_restart


async def render_git_projects(update: Update, d: dict) -> None:
    projects = discover_git_projects()
    d["data"]["git_projects"] = {label: str(path) for label, path in projects.items()}
    if not projects:
        await show(
            update,
            "📦 تحديث المشاريع من GitHub\n\nلم يتم العثور على أي مستودع Git على السيرفر.",
            kb([]),
        )
        return
    rows: list[list[str]] = []
    row: list[str] = []
    for label in projects:
        row.append(label)
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    await show(update, "📦 تحديث المشاريع من GitHub\n\nاختر مشروعاً لفحصه وتحديثه من GitHub:", kb(rows))


async def open_git_projects(update: Update, d: dict) -> None:
    d["mode"] = None
    push_menu(d, "git_projects")
    await render_git_projects(update, d)


# =========================================================================
# /start & authentication
# =========================================================================


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text(
            "🛡️ Pyramid Server Manager\n\n"
            "هذه لوحة إدارة خاصة.\n"
            "ليس لديك صلاحية للوصول.\n\n"
            "إذا كنت تعتقد أن هذا خطأ، يرجى التواصل مع مسؤول النظام."
        )
        return

    d = ud(context)
    if user_id in AUTHENTICATED:
        d["stack"] = ["main"]
        d["mode"] = None
        await show(update, "🏠 القائمة الرئيسية", MAIN_MENU)
        return

    conn = db_connect()
    row = conn.execute("SELECT * FROM login_state WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    if row and row["locked_until"]:
        locked_until = datetime.fromisoformat(row["locked_until"])
        if datetime.now() < locked_until:
            remaining = int((locked_until - datetime.now()).total_seconds() // 60) + 1
            await update.message.reply_text(f"⛔ محاولات كثيرة. حاول بعد {remaining} دقيقة.")
            return

    d["pending"] = "await_password"
    await update.message.reply_text("🔒 أدخل كلمة مرور لوحة التحكم.")


async def handle_password(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    user_id = update.effective_user.id
    d = ud(context)
    correct = get_setting("panel_password", config.DEFAULT_PANEL_PASSWORD)
    conn = db_connect()

    if text == correct:
        conn.execute(
            "INSERT INTO login_state (user_id, attempts, locked_until) VALUES (?, 0, NULL) "
            "ON CONFLICT(user_id) DO UPDATE SET attempts=0, locked_until=NULL",
            (user_id,),
        )
        conn.commit()
        conn.close()
        AUTHENTICATED.add(user_id)
        reset_pending(d)
        d["stack"] = ["main"]
        d["mode"] = None
        log_action(user_id, "login")
        await update.message.reply_text("✅ تم تسجيل الدخول بنجاح.")
        await show(update, "🏠 القائمة الرئيسية", MAIN_MENU)
        return

    row = conn.execute("SELECT attempts FROM login_state WHERE user_id=?", (user_id,)).fetchone()
    attempts = (row["attempts"] if row else 0) + 1
    if attempts >= config.MAX_LOGIN_ATTEMPTS:
        locked_until = (datetime.now() + timedelta(minutes=config.LOCKOUT_MINUTES)).isoformat()
        conn.execute(
            "INSERT INTO login_state (user_id, attempts, locked_until) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET attempts=excluded.attempts, locked_until=excluded.locked_until",
            (user_id, attempts, locked_until),
        )
        conn.commit()
        conn.close()
        reset_pending(d)
        await update.message.reply_text(
            f"⛔ تم قفل الدخول لمدة {config.LOCKOUT_MINUTES} دقيقة بسبب المحاولات الخاطئة المتكررة."
        )
        await notify_owner(context.application, f"⚠️ محاولات دخول فاشلة متكررة من المستخدم {user_id}.")
        return

    conn.execute(
        "INSERT INTO login_state (user_id, attempts, locked_until) VALUES (?, ?, NULL) "
        "ON CONFLICT(user_id) DO UPDATE SET attempts=excluded.attempts",
        (user_id, attempts),
    )
    conn.commit()
    conn.close()
    await update.message.reply_text("❌ كلمة المرور غير صحيحة.")


# =========================================================================
# Central text router
# =========================================================================


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if not is_admin(user_id):
        return

    d = ud(context)

    if user_id not in AUTHENTICATED:
        if d.get("pending") == "await_password":
            await handle_password(update, context, text)
        else:
            await start(update, context)
        return

    # --- global navigation ------------------------------------------------
    if text == BTN_HOME:
        reset_pending(d)
        if d["mode"] == "terminal":
            await exit_terminal_session(user_id)
        d["mode"] = None
        d["stack"] = ["main"]
        d["fm_clipboard"] = None
        await show(update, "🏠 القائمة الرئيسية", MAIN_MENU)
        return

    if text == BTN_BACK:
        await handle_back(update, d)
        return

    # --- pending free-text input (rename, mkdir name, search term, etc.) --
    if d.get("pending"):
        await handle_pending(update, context, d, text)
        return

    # --- terminal mode: everything else is a shell command ---------------
    if d["mode"] == "terminal":
        if text == TERM_CTRLC:
            await terminal_ctrlc(update, context)
            return
        if text == TERM_CLEAR:
            await update.message.reply_text("🧹 تم مسح الشاشة.\n💻 التريمنال جاهز لأمر جديد.")
            return
        if text == TERM_HISTORY:
            hist = d["cmd_history"]
            await update.message.reply_text("📜 آخر الأوامر:\n" + ("\n".join(hist) if hist else "(لا يوجد سجل بعد)"))
            return
        if text == TERM_COPY:
            last = d.get("term_last")
            if not last:
                await update.message.reply_text("لا يوجد ناتج سابق لنسخه بعد.")
                return
            for chunk in trim_chunks(last):
                await update.message.reply_text(chunk)
            return
        await run_terminal_command(update, context, d, text)
        return

    # --- file manager mode: resolve tapped entry/action buttons -----------
    if d["mode"] == "filemanager":
        if await handle_filemanager_text(update, context, d, text):
            return
        # falls through to global menu matching below (in case of stale kb)

    # --- main menu ----------------------------------------------------
    if text == BTN_BOTS:
        await open_bots_menu(update, d)
        return
    if text == BTN_FILES:
        await open_file_manager(update, d, config.FS_ROOT, f"📁 مستعرض الملفات — /root")
        return
    if text == BTN_SETTINGS:
        await goto_static(update, d, "settings")
        return
    if text == BTN_SERVER_INFO:
        push_menu(d, "server_info")
        await send_server_info(update)
        return
    if text == BTN_MONITOR:
        push_menu(d, "monitor")
        await send_monitor(update)
        return
    if text == BTN_TERMINAL:
        await enter_terminal(update, d)
        return
    if text == BTN_REFRESH_SERVER:
        await refresh_server(update)
        return
    if text == BTN_GIT_UPDATE:
        await open_git_projects(update, d)
        return

    # --- GitHub project list buttons -------------------------------------
    if d["stack"][-1] == "git_projects" and text in d["data"].get("git_projects", {}):
        path = Path(d["data"]["git_projects"][text])
        await update.message.reply_text(f"⏳ جاري فحص {path.name} ...")
        report, needs_confirm, self_restart = await perform_git_update(path, allow_stash=False)
        if needs_confirm:
            d["pending"] = "git_confirm_dirty"
            d["data"]["git_confirm_path"] = str(path)
            await update.message.reply_text(report, reply_markup=CONFIRM_MENU)
            return
        log_action(user_id, f"git update: {path}")
        await update.message.reply_text(report)
        if self_restart:
            python = sys.executable
            os.execv(python, [python] + sys.argv)
        return

    # --- server info screen buttons ------------------------------------
    if text == INFO_REFRESH:
        await send_server_info(update)
        return
    if text == INFO_COPY:
        info_text = await build_server_info_text()
        plain = info_text.replace("*", "")
        await update.message.reply_text(f"```\n{plain}\n```", parse_mode=ParseMode.MARKDOWN)
        return

    # --- monitor screen buttons -----------------------------------------
    if text == MON_REFRESH:
        await send_monitor(update)
        return
    bot_name = label_to_bot_name(text)
    if bot_name and d["stack"][-1] == "monitor":
        await open_bot_detail(update, d, bot_name)
        return

    # --- bots list buttons -----------------------------------------------
    if bot_name and d["stack"][-1] == "bots":
        await open_bot_detail(update, d, bot_name)
        return
    if text == BTN_BOT_NEW:
        d["pending"] = "bot_upload_name"
        await update.message.reply_text("أرسل اسماً للبوت الجديد:")
        return

    # --- bot detail buttons ------------------------------------------------
    if d["stack"][-1] == "bot_detail" and d.get("bot_selected"):
        if await handle_bot_detail_action(update, context, d, text):
            return

    # --- settings submenu --------------------------------------------------
    if text == BTN_SET_PASSWORD:
        d["pending"] = "set_password"
        await update.message.reply_text("أرسل كلمة المرور الجديدة:")
        return
    if text == BTN_SET_ADD_ADMIN:
        d["pending"] = "add_admin"
        await update.message.reply_text("أرسل معرف المستخدم (ID) المراد إضافته كمدير:")
        return
    if text == BTN_SET_DEL_ADMIN:
        d["pending"] = "del_admin"
        await update.message.reply_text("أرسل معرف المستخدم (ID) المراد حذفه من المدراء:")
        return
    if text == BTN_SET_NOTIFY:
        cur = get_setting("notifications", "1")
        new = "0" if cur == "1" else "1"
        set_setting("notifications", new)
        await update.message.reply_text("🔔 الإشعارات مفعلة." if new == "1" else "🔕 الإشعارات معطلة.")
        return
    if text == BTN_SET_OPLOG:
        await send_oplog(update)
        return
    if text == BTN_SET_BACKUP:
        await goto_static(update, d, "backup")
        return

    # --- backup submenu -----------------------------------------------------
    if text == BTN_BACKUP_CREATE:
        await create_backup(update)
        return
    if text == BTN_BACKUP_RESTORE:
        push_menu(d, "backup_list")
        await render_backup_list(update, d, "restore")
        return
    if text == BTN_BACKUP_SEND:
        push_menu(d, "backup_list")
        await render_backup_list(update, d, "send")
        return

    # --- backup file list buttons ------------------------------------------
    if d["stack"][-1] == "backup_list" and text in d["data"].get("backup_files", {}):
        filename = d["data"]["backup_files"][text]
        purpose = d["data"].get("backup_purpose")
        if purpose == "send":
            await send_backup(update, filename)
        else:
            d["pending"] = "backup_confirm_restore"
            d["data"]["backup_restore_file"] = filename
            await update.message.reply_text(
                f"⚠️ استعادة {filename} ستكتب فوق الملفات الحالية. متأكد؟", reply_markup=CONFIRM_MENU
            )
        return

    if text == CLEAN_BTN:
        await clean_server(update)
        return
    if text == BTN_DEPS_UPDATE:
        await update.message.reply_text("📦 جاري فحص وتحديث المكتبات...")
        report = await update_dependencies()
        await update.message.reply_text(report)
        return
    if text == BTN_ENV_CHECK:
        await send_env_check(update)
        return
    if text == BTN_RESTART_BOT:
        await restart_bot_process(update)
        return

    await update.message.reply_text("لم أفهم الأمر، الرجاء استخدام الأزرار.")


# --- BACK navigation, context-aware ----------------------------------------


async def show_menu_by_name(update: Update, d: dict, name: str) -> None:
    """Render whichever screen `name` refers to (works for both static menus
    and the dynamic ones that need fresh data each time)."""
    if name == "bots":
        await show(update, "🤖 إدارة البوتات — اختر بوتاً، أو ارفع بوتاً جديداً:", bots_list_menu())
        return
    if name == "bot_detail" and d.get("bot_selected"):
        await refresh_bot_detail_message(update, d["bot_selected"])
        return
    if name == "monitor":
        await send_monitor(update)
        return
    if name == "server_info":
        await send_server_info(update)
        return
    if name == "git_projects":
        await render_git_projects(update, d)
        return
    markup, title = MENUS.get(name, (MAIN_MENU, "🏠 القائمة الرئيسية"))
    await show(update, title, markup)


async def handle_back(update: Update, d: dict) -> None:
    reset_pending(d)
    if d["mode"] == "terminal":
        await exit_terminal_session(update.effective_user.id)

    if d["mode"] == "filemanager" and d["stack"][-1] in ("filemanager",):
        # Step up a directory if not already at the file-manager root.
        if os.path.normpath(d["fm_path"]) != os.path.normpath(d["fm_root"]):
            d["fm_path"] = str(Path(d["fm_path"]).parent)
            await render_fm(update, d)
            return
        # already at root -> leave file manager entirely, back to whichever
        # screen it was opened from (main files section or a bot's page)
        d["mode"] = None
        d["fm_clipboard"] = None
        name = pop_menu(d)
        await show_menu_by_name(update, d, name)
        return

    if d["stack"][-1] in ("file_actions", "dir_actions", "search_results"):
        return_to_filemanager(d)
        await render_fm(update, d)
        return

    if d["mode"] == "terminal":
        d["mode"] = None
        pop_menu(d)

    if d["stack"][-1] == "bot_detail":
        d["bot_selected"] = None
        d["stack"].pop()
        await show(update, "🤖 إدارة البوتات — اختر بوتاً، أو ارفع بوتاً جديداً:", bots_list_menu())
        return

    name = pop_menu(d)
    await show_menu_by_name(update, d, name)


# --- File manager text-button dispatch --------------------------------------


async def handle_filemanager_text(update: Update, context: ContextTypes.DEFAULT_TYPE, d: dict, text: str) -> bool:
    """Returns True if the text was handled as a file-manager action."""

    if d["stack"][-1] == "filemanager":
        if text == FM_MKDIR:
            d["pending"] = "fm_mkdir"
            await update.message.reply_text("أرسل اسم المجلد الجديد:")
            return True
        if text == FM_UPLOAD_HERE:
            d["pending"] = "fm_upload_file"
            await update.message.reply_text("أرسل الملف الآن ليتم رفعه داخل هذا المجلد:")
            return True
        if text == FM_SEARCH:
            d["pending"] = "fm_search_term"
            await update.message.reply_text("أرسل اسم الملف (أو جزءاً منه) للبحث:")
            return True
        if text == FM_PASTE:
            await fm_paste(update, d)
            return True
        if text in d["fm_listing"]:
            target = d["fm_listing"][text]
            if Path(target).is_dir():
                await open_dir_actions(update, d, target)
            else:
                await open_file_actions(update, d, target)
            return True
        return False

    if d["stack"][-1] == "search_results":
        if text in d["fm_listing"]:
            target = d["fm_listing"][text]
            await open_file_actions(update, d, target)
            return True
        return False

    if d["stack"][-1] == "file_actions":
        return await handle_file_action(update, context, d, text)

    if d["stack"][-1] == "dir_actions":
        return await handle_dir_action(update, context, d, text)

    return False


async def fm_paste(update: Update, d: dict) -> None:
    clip = d.get("fm_clipboard")
    if not clip:
        await update.message.reply_text("لا يوجد عنصر منسوخ حالياً.")
        return
    src = Path(clip["path"])
    dst = Path(d["fm_path"]) / src.name
    try:
        if clip["op"] == "copy":
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
            await update.message.reply_text(f"✅ تم نسخ {src.name} هنا.")
        else:
            shutil.move(str(src), str(dst))
            await update.message.reply_text(f"✅ تم نقل {src.name} هنا.")
    except Exception as exc:
        await update.message.reply_text(f"❌ فشلت العملية: {exc}")
    d["fm_clipboard"] = None
    await render_fm(update, d)


async def handle_file_action(update: Update, context: ContextTypes.DEFAULT_TYPE, d: dict, text: str) -> bool:
    user_id = update.effective_user.id
    path = d.get("fm_selected")
    if not path:
        return False
    p = Path(path)

    if text == FILE_ACT_VIEW:
        try:
            content = p.read_text(errors="replace")
        except Exception as exc:
            await update.message.reply_text(f"❌ لا يمكن قراءة الملف: {exc}")
            return True
        for chunk in trim_chunks(content):
            await update.message.reply_text(f"```\n{chunk}\n```", parse_mode=ParseMode.MARKDOWN)
        return True

    if text == FILE_ACT_EDIT:
        d["pending"] = "fm_edit_content"
        await update.message.reply_text("أرسل المحتوى الجديد الكامل للملف:")
        return True

    if text in (FILE_ACT_DOWNLOAD, FILE_ACT_SHARE):
        if p.stat().st_size > config.MAX_FILE_SIZE:
            await update.message.reply_text("❌ الملف كبير جداً للإرسال عبر تيليجرام.")
            return True
        with open(p, "rb") as f:
            await update.message.reply_document(f, filename=p.name)
        return True

    if text == FILE_ACT_COPY:
        d["fm_clipboard"] = {"op": "copy", "path": str(p)}
        await update.message.reply_text("📑 تم نسخ الملف. انتقل إلى المجلد الوجهة ثم اضغط «📥 لصق هنا».")
        return_to_filemanager(d)
        await render_fm(update, d)
        return True

    if text == FILE_ACT_MOVE:
        d["fm_clipboard"] = {"op": "move", "path": str(p)}
        await update.message.reply_text("🚚 جاهز للنقل. انتقل إلى المجلد الوجهة ثم اضغط «📥 لصق هنا».")
        return_to_filemanager(d)
        await render_fm(update, d)
        return True

    if text == FILE_ACT_ZIP:
        out = p.with_suffix(p.suffix + ".zip")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(p, p.name)
        log_action(user_id, f"zip {p}")
        await update.message.reply_text(f"✅ تم إنشاء {out.name}")
        return_to_filemanager(d)
        await render_fm(update, d)
        return True

    if text == FILE_ACT_INFO:
        st = p.stat()
        info = (
            f"ℹ️ {p.name}\nالحجم: {human_size(st.st_size)}\n"
            f"آخر تعديل: {datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"الصلاحيات: {oct(st.st_mode)[-3:]}"
        )
        await update.message.reply_text(info)
        return True

    if text == FILE_ACT_DELETE:
        d["pending"] = "fm_confirm_delete"
        await update.message.reply_text(f"هل أنت متأكد من حذف {p.name}؟", reply_markup=CONFIRM_MENU)
        return True

    return False


async def handle_dir_action(update: Update, context: ContextTypes.DEFAULT_TYPE, d: dict, text: str) -> bool:
    user_id = update.effective_user.id
    path = d.get("fm_selected")
    if not path:
        return False
    p = Path(path)

    if text == DIR_ACT_OPEN:
        d["fm_path"] = str(p)
        return_to_filemanager(d)
        await render_fm(update, d)
        return True

    if text == DIR_ACT_ZIP:
        out = Path(str(p) + ".zip")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(p):
                for name in files:
                    full = Path(root) / name
                    zf.write(full, full.relative_to(p.parent))
        log_action(user_id, f"zip dir {p}")
        await update.message.reply_text(f"✅ تم إنشاء {out.name}")
        return_to_filemanager(d)
        await render_fm(update, d)
        return True

    if text == DIR_ACT_RENAME:
        d["pending"] = "fm_rename_new_name"
        await update.message.reply_text("أرسل الاسم الجديد للمجلد:")
        return True

    if text == DIR_ACT_MKDIR:
        d["pending"] = "fm_mkdir_in_selected"
        await update.message.reply_text(f"أرسل اسم المجلد الجديد داخل {p.name}:")
        return True

    if text == DIR_ACT_UPLOAD:
        d["pending"] = "fm_upload_into_selected"
        await update.message.reply_text(f"أرسل الملف الآن ليُرفع داخل {p.name}:")
        return True

    if text == DIR_ACT_DELETE:
        d["pending"] = "fm_confirm_delete"
        await update.message.reply_text(f"هل أنت متأكد من حذف المجلد {p.name} وكل محتوياته؟", reply_markup=CONFIRM_MENU)
        return True

    return False


async def refresh_bot_detail_message(update: Update, name: str) -> None:
    """Resend the bot-detail screen with fresh status, without touching the
    navigation stack (used after start/stop/restart while already on that screen)."""
    row = db_get_bot(name)
    if row is None:
        return
    dot = "🟢 يعمل" if row["status"] == "running" else "🔴 متوقف"
    text = (
        f"🤖 {name}\nالحالة: {dot}\nاللغة: {row['runtime']}\n"
        f"إعادة التشغيل التلقائي: {'مفعلة' if row['auto_restart'] else 'معطلة'}"
    )
    await update.message.reply_text(text, reply_markup=BOT_DETAIL_MENU)


async def handle_bot_detail_action(update: Update, context: ContextTypes.DEFAULT_TYPE, d: dict, text: str) -> bool:
    user_id = update.effective_user.id
    name = d["bot_selected"]

    if text == BOT_ACTION_START:
        msg = await start_bot_process(name)
        log_action(user_id, f"start bot {name}")
        await update.message.reply_text(msg)
        await refresh_bot_detail_message(update, name)
        return True
    if text == BOT_ACTION_STOP:
        msg = await stop_bot_process(name)
        log_action(user_id, f"stop bot {name}")
        await update.message.reply_text(msg)
        await refresh_bot_detail_message(update, name)
        return True
    if text == BOT_ACTION_RESTART:
        await stop_bot_process(name)
        await asyncio.sleep(1)
        msg = await start_bot_process(name)
        log_action(user_id, f"restart bot {name}")
        await update.message.reply_text(msg)
        await refresh_bot_detail_message(update, name)
        return True
    if text == BOT_ACTION_LOGS:
        row = db_get_bot(name)
        log_file = Path(row["path"]) / "bot.log"
        if not log_file.exists():
            await update.message.reply_text("(لا يوجد سجل بعد)")
        else:
            content = log_file.read_text(errors="replace")[-config.MAX_OUTPUT_CHARS :]
            await update.message.reply_text(f"```\n{content}\n```", parse_mode=ParseMode.MARKDOWN)
        return True
    if text == BOT_ACTION_USAGE:
        row = db_get_bot(name)
        await update.message.reply_text(await bot_usage_text(row))
        return True
    if text == BOT_ACTION_FILES:
        row = db_get_bot(name)
        await open_file_manager(update, d, row["path"], f"📂 ملفات {name}")
        return True
    if text == BOT_ACTION_SETTINGS:
        new_state = db_toggle_autorestart(name)
        await update.message.reply_text(
            "✅ تم تفعيل إعادة التشغيل التلقائي." if new_state else "✅ تم تعطيل إعادة التشغيل التلقائي."
        )
        return True
    if text == BOT_ACTION_RENAME:
        d["pending"] = "bot_rename"
        await update.message.reply_text("أرسل الاسم الجديد للبوت:")
        return True
    if text == BOT_ACTION_DELETE:
        d["pending"] = "bot_confirm_delete"
        await update.message.reply_text(f"هل أنت متأكد من حذف البوت {name} نهائياً؟", reply_markup=CONFIRM_MENU)
        return True

    return False


# --- Pending (free-text) actions --------------------------------------------


async def handle_pending(update: Update, context: ContextTypes.DEFAULT_TYPE, d: dict, text: str) -> None:
    user_id = update.effective_user.id
    pending = d["pending"]

    if pending == "bot_upload_name":
        name = safe_child_name(text)
        if not name:
            await update.message.reply_text("❌ اسم بوت غير صالح. استخدم اسماً بدون / أو \\.")
            return
        if db_get_bot(name):
            await update.message.reply_text("⚠️ يوجد بوت بهذا الاسم بالفعل. اختر اسماً آخر:")
            return
        d["data"]["bot_name"] = name
        d["pending"] = "bot_upload_file"
        await update.message.reply_text("الآن أرسل ملف ZIP يحتوي على كود البوت:")
        return

    if pending == "bot_rename":
        old = d["bot_selected"]
        new = safe_child_name(text)
        if not new:
            await update.message.reply_text("❌ اسم بوت غير صالح.")
            return
        if db_get_bot(new):
            await update.message.reply_text("⚠️ يوجد بوت بهذا الاسم بالفعل. أرسل اسماً آخر:")
            return
        reset_pending(d)
        db_rename_bot(old, new)
        d["bot_selected"] = new
        log_action(user_id, f"renamed bot {old} -> {new}")
        await update.message.reply_text(f"✅ تم تغيير الاسم إلى {new}.")
        await refresh_bot_detail_message(update, new)
        return

    if pending == "bot_confirm_delete":
        reset_pending(d)
        if text == CONFIRM_YES:
            name = d["bot_selected"]
            row = db_get_bot(name)
            await stop_bot_process(name)
            if row:
                shutil.rmtree(row["path"], ignore_errors=True)
            db_delete_bot(name)
            log_action(user_id, f"delete bot {name}")
            await update.message.reply_text(f"🗑️ تم حذف {name}.")
        else:
            await update.message.reply_text("تم الإلغاء.")
        await return_to_bots_list(update, d)
        return

    if pending == "set_password":
        reset_pending(d)
        set_setting("panel_password", text)
        log_action(user_id, "changed panel password")
        await update.message.reply_text("✅ تم تغيير كلمة المرور.")
        return
    if pending == "add_admin":
        reset_pending(d)
        try:
            uid = int(text)
        except ValueError:
            await update.message.reply_text("❌ أدخل رقم ID صحيح.")
            return
        conn = db_connect()
        conn.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (uid,))
        conn.commit()
        conn.close()
        log_action(user_id, f"added admin {uid}")
        await update.message.reply_text(f"✅ تمت إضافة {uid} كمدير.")
        return
    if pending == "del_admin":
        reset_pending(d)
        try:
            uid = int(text)
        except ValueError:
            await update.message.reply_text("❌ أدخل رقم ID صحيح.")
            return
        conn = db_connect()
        conn.execute("DELETE FROM admins WHERE user_id=?", (uid,))
        conn.commit()
        conn.close()
        log_action(user_id, f"removed admin {uid}")
        await update.message.reply_text(f"✅ تم حذف {uid} من المدراء.")
        return
    if pending == "git_confirm_dirty":
        path = Path(d["data"].get("git_confirm_path", ""))
        reset_pending(d)
        if text == CONFIRM_YES:
            report, _, self_restart = await perform_git_update(path, allow_stash=True)
            log_action(user_id, f"git update (stash): {path}")
            await update.message.reply_text(report)
            if self_restart:
                python = sys.executable
                os.execv(python, [python] + sys.argv)
        else:
            await update.message.reply_text("تم الإلغاء. لم يتم تغيير أي شيء في المشروع.")
        return
    if pending == "backup_confirm_restore":
        filename = d["data"].get("backup_restore_file")
        reset_pending(d)
        if text == CONFIRM_YES and filename:
            await restore_backup(update, filename)
        else:
            await update.message.reply_text("تم الإلغاء.")
        await goto_static(update, d, "backup")
        return

    # --- file manager pending inputs ---------------------------------------
    if pending == "fm_mkdir":
        reset_pending(d)
        name = safe_child_name(text)
        if not name:
            await update.message.reply_text("❌ اسم مجلد غير صالح.")
            return
        new_dir = Path(d["fm_path"]) / name
        new_dir.mkdir(parents=True, exist_ok=True)
        log_action(user_id, f"mkdir {new_dir}")
        await update.message.reply_text("✅ تم إنشاء المجلد.")
        await render_fm(update, d)
        return

    if pending == "fm_search_term":
        reset_pending(d)
        await fm_search(update, d, text.strip())
        return

    if pending == "fm_edit_content":
        reset_pending(d)
        p = Path(d["fm_selected"])
        p.write_text(text, encoding="utf-8")
        log_action(user_id, f"edit file {p}")
        await update.message.reply_text("✅ تم حفظ الملف.")
        return_to_filemanager(d)
        await render_fm(update, d)
        return

    if pending == "fm_mkdir_in_selected":
        reset_pending(d)
        name = safe_child_name(text)
        if not name:
            await update.message.reply_text("❌ اسم مجلد غير صالح.")
            return
        parent = Path(d["fm_selected"])
        new_dir = parent / name
        new_dir.mkdir(parents=True, exist_ok=True)
        log_action(user_id, f"mkdir {new_dir}")
        await update.message.reply_text("✅ تم إنشاء المجلد.")
        return_to_filemanager(d)
        await render_fm(update, d)
        return

    if pending == "fm_rename_new_name":
        reset_pending(d)
        name = safe_child_name(text)
        if not name:
            await update.message.reply_text("❌ اسم غير صالح.")
            return
        src = Path(d["fm_selected"])
        dst = src.parent / name
        try:
            src.rename(dst)
            log_action(user_id, f"rename {src} -> {dst}")
            await update.message.reply_text("✅ تمت إعادة التسمية.")
        except Exception as exc:
            await update.message.reply_text(f"❌ فشلت إعادة التسمية: {exc}")
        return_to_filemanager(d)
        await render_fm(update, d)
        return

    if pending == "fm_confirm_delete":
        reset_pending(d)
        p = Path(d["fm_selected"])
        if text == CONFIRM_YES:
            try:
                if p.is_dir():
                    shutil.rmtree(p)
                else:
                    p.unlink()
                log_action(user_id, f"delete {p}")
                await update.message.reply_text(f"🗑️ تم حذف {p.name}.")
            except Exception as exc:
                await update.message.reply_text(f"❌ فشل الحذف: {exc}")
        else:
            await update.message.reply_text("تم الإلغاء.")
        return_to_filemanager(d)
        await render_fm(update, d)
        return

    reset_pending(d)
    await update.message.reply_text("تم إلغاء العملية.")


# =========================================================================
# Document (file/bot upload) handler
# =========================================================================


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_admin(user_id) or user_id not in AUTHENTICATED:
        return
    d = ud(context)
    pending = d.get("pending")
    doc = update.message.document

    if doc.file_size and doc.file_size > config.MAX_FILE_SIZE:
        await update.message.reply_text("❌ الملف أكبر من الحد المسموح.")
        return

    if pending == "fm_upload_file":
        reset_pending(d)
        filename = safe_child_name(doc.file_name)
        if not filename:
            await update.message.reply_text("❌ اسم الملف غير صالح.")
            return
        dest = Path(d["fm_path"]) / filename
        tg_file = await doc.get_file()
        await tg_file.download_to_drive(str(dest))
        log_action(user_id, f"upload file {dest}")
        await update.message.reply_text(f"✅ تم رفع {doc.file_name}.")
        await render_fm(update, d)
        return

    if pending == "fm_upload_into_selected":
        reset_pending(d)
        filename = safe_child_name(doc.file_name)
        if not filename:
            await update.message.reply_text("❌ اسم الملف غير صالح.")
            return
        parent = Path(d["fm_selected"])
        dest = parent / filename
        tg_file = await doc.get_file()
        await tg_file.download_to_drive(str(dest))
        log_action(user_id, f"upload file {dest}")
        await update.message.reply_text(f"✅ تم رفع {doc.file_name} داخل {parent.name}.")
        return_to_filemanager(d)
        await render_fm(update, d)
        return

    if pending == "bot_upload_file":
        reset_pending(d)
        name = d["data"]["bot_name"]
        bot_dir = Path(config.BOTS_DIR) / name
        bot_dir.mkdir(parents=True, exist_ok=True)
        zip_dest = bot_dir / "upload.zip"
        tg_file = await doc.get_file()
        await tg_file.download_to_drive(str(zip_dest))
        try:
            with zipfile.ZipFile(zip_dest) as zf:
                safe_extract_zip(zf, bot_dir)
        except zipfile.BadZipFile:
            await update.message.reply_text("❌ الملف ليس ZIP صالح.")
            shutil.rmtree(bot_dir, ignore_errors=True)
            return
        zip_dest.unlink(missing_ok=True)

        detected = detect_runtime(bot_dir)
        if not detected:
            await update.message.reply_text("❌ لم يتم التعرف على نوع المشروع.")
            shutil.rmtree(bot_dir, ignore_errors=True)
            return
        runtime, entry = detected
        db_upsert_bot(name, str(bot_dir), runtime, entry)
        log_action(user_id, f"uploaded bot {name} ({runtime})")
        await update.message.reply_text(f"📦 تم استلام {name} كمشروع {runtime}. جاري تثبيت المتطلبات...")
        result = install_requirements(bot_dir, runtime)
        await update.message.reply_text(f"✅ تم إعداد البوت.\n```\n{result[-1500:]}\n```", parse_mode=ParseMode.MARKDOWN)
        await open_bots_menu(update, d)
        return


# =========================================================================
# Entrypoint
# =========================================================================


def main() -> None:
    if not config.BOT_TOKEN or config.BOT_TOKEN == "PUT_YOUR_BOT_TOKEN_HERE":
        raise SystemExit("Please set BOT_TOKEN in config.py")
    if not config.OWNER_ID:
        raise SystemExit("Please set OWNER_ID in config.py")

    db_init()

    app = Application.builder().token(config.BOT_TOKEN).post_init(post_init).build()

    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.COMMAND, lambda u, c: start(u, c)))

    if app.job_queue:
        app.job_queue.run_repeating(watchdog_job, interval=config.WATCHDOG_INTERVAL, first=config.WATCHDOG_INTERVAL)

    log.info("Pyramid Server Manager starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
