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
import logging
import os
import platform
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
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
        [BTN_REFRESH_SERVER],
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
RUNNING_TERMINAL_PROCS: dict[int, asyncio.subprocess.Process] = {}


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


def start_bot_process(name: str) -> str:
    row = db_get_bot(name)
    if row is None:
        return "❌ البوت غير موجود."
    if name in RUNNING_PROCS and RUNNING_PROCS[name].poll() is None:
        return "⚠️ البوت يعمل بالفعل."
    template = RUNTIME_ENTRY[row["runtime"]]
    cmd = [part.format(entry=row["entry"]) for part in template]
    log_file = Path(row["path"]) / "bot.log"
    try:
        with open(log_file, "ab") as lf:
            proc = subprocess.Popen(
                cmd, cwd=row["path"], stdout=lf, stderr=lf, start_new_session=True,
            )
        RUNNING_PROCS[name] = proc
        db_set_bot_status(name, "running", proc.pid)
        return f"✅ تم تشغيل {name} (PID {proc.pid})."
    except Exception as exc:  # noqa: BLE001
        return f"❌ فشل التشغيل: {exc}"


def stop_bot_process(name: str) -> str:
    proc = RUNNING_PROCS.get(name)
    row = db_get_bot(name)
    pid = proc.pid if proc else (row["pid"] if row else None)
    if not pid:
        return "⚠️ البوت غير مشغل."
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except Exception:
        try:
            psutil.Process(pid).terminate()
        except Exception:
            pass
    RUNNING_PROCS.pop(name, None)
    db_set_bot_status(name, "stopped", None)
    return f"⏹️ تم إيقاف {name}."


def install_requirements(path: Path, runtime: str) -> str:
    if runtime == "python" and (path / "requirements.txt").exists():
        r = subprocess.run(
            ["pip", "install", "--break-system-packages", "-r", "requirements.txt"],
            cwd=path, capture_output=True, text=True, timeout=300,
        )
        return r.stdout[-1500:] + r.stderr[-1500:]
    if runtime == "node" and (path / "package.json").exists():
        r = subprocess.run(["npm", "install"], cwd=path, capture_output=True, text=True, timeout=300)
        return r.stdout[-1500:] + r.stderr[-1500:]
    return "(لا توجد متطلبات للتثبيت)"


async def watchdog_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    for row in db_all_bots():
        name = row["name"]
        if row["status"] != "running":
            continue
        proc = RUNNING_PROCS.get(name)
        alive = proc is not None and proc.poll() is None
        if not alive and row["pid"]:
            try:
                alive = psutil.pid_exists(row["pid"])
            except Exception:
                alive = False
        if not alive:
            db_set_bot_status(name, "crashed", None)
            await notify_owner(context.application, f"⚠️ البوت {name} توقف بشكل غير متوقع.")
            if row["auto_restart"]:
                msg = start_bot_process(name)
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
            cpu = pr.cpu_percent(interval=0.2)
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


async def enter_terminal(update: Update, d: dict) -> None:
    d["mode"] = "terminal"
    push_menu(d, "terminal")
    await show(
        update,
        "💻 وضع التريمنال مفعّل.\nأرسل أي أمر Linux وسيتم تنفيذه.\nاستخدم ⏹️ Ctrl+C لإيقاف عملية طويلة، ورجوع/الرئيسية للخروج.",
        TERMINAL_MENU,
    )


async def run_terminal_command(update: Update, context: ContextTypes.DEFAULT_TYPE, d: dict, command: str) -> None:
    user_id = update.effective_user.id
    d["cmd_history"].append(command)
    d["cmd_history"] = d["cmd_history"][-10:]
    log_action(user_id, f"terminal: {command}")

    start_t = time.perf_counter()
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=config.SERVER_PATH,
            preexec_fn=os.setsid,
        )
    except Exception as exc:
        await update.message.reply_text(f"❌ خطأ في تنفيذ الأمر: {exc}")
        return

    RUNNING_TERMINAL_PROCS[user_id] = proc
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=config.COMMAND_TIMEOUT)
        exit_code = proc.returncode
        timed_out = False
    except asyncio.TimeoutError:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            pass
        out = b""
        exit_code = -1
        timed_out = True
    finally:
        RUNNING_TERMINAL_PROCS.pop(user_id, None)

    elapsed = time.perf_counter() - start_t
    output_text = out.decode(errors="replace")

    if timed_out:
        await update.message.reply_text(f"⏱️ انتهت المهلة ({config.COMMAND_TIMEOUT} ثانية) وتم إيقاف الأمر.")
        return

    footer = f"⏱️ الوقت: {elapsed:.2f}ث | 🔚 Exit code: {exit_code}"
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
    proc = RUNNING_TERMINAL_PROCS.get(user_id)
    if not proc:
        await update.message.reply_text("لا توجد عملية قيد التشغيل حالياً.")
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGINT)
        await update.message.reply_text("⏹️ تم إرسال Ctrl+C للعملية الحالية.")
    except Exception as exc:
        await update.message.reply_text(f"❌ تعذر إيقاف العملية: {exc}")


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
            msg = start_bot_process(row["name"])
            if msg.startswith("✅"):
                restarted += 1
    report.append(
        f"✅ تم إعادة تشغيل {restarted} بوت كان متعطلاً" if restarted
        else "✅ لا توجد بوتات متعطلة تحتاج إعادة تشغيل"
    )

    stale = [uid for uid, p in RUNNING_TERMINAL_PROCS.items() if p.returncode is not None]
    for uid in stale:
        RUNNING_TERMINAL_PROCS.pop(uid, None)
    report.append(
        f"✅ تم تنظيف {len(stale)} عملية تريمنال معلّقة" if stale
        else "✅ لا توجد عمليات تريمنال معلّقة"
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
    results = check_environment()
    to_install = [r for r in results if r[2] != "installed"]
    if not to_install:
        return f"✅ تم فحص {len(results)} مكتبة\n✅ كل المكتبات محدثة\n✅ لا توجد أخطاء"

    updated = 0
    errors = []
    for pkg, ver, status, _installed in to_install:
        spec = f"{pkg}=={ver}" if ver else pkg
        try:
            r = subprocess.run(
                ["pip", "install", "--break-system-packages", spec],
                capture_output=True, text=True, timeout=180,
            )
            if r.returncode == 0:
                updated += 1
            else:
                errors.append(f"{pkg}: {r.stderr.strip()[-200:]}")
        except Exception as exc:
            errors.append(f"{pkg}: {exc}")

    report = f"✅ تم فحص {len(results)} مكتبة\n✅ تم تحديث {updated} مكتبة"
    report += ("\n❌ أخطاء:\n" + "\n".join(errors[:5])) if errors else "\n✅ لا توجد أخطاء"
    return report


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


async def build_monitor_text() -> str:
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    net = psutil.net_io_counters()
    uptime = fmt_duration(time.time() - psutil.boot_time())

    lines = [
        "📊 *مراقبة الموارد*\n",
        f"CPU: {progress_bar(psutil.cpu_percent(interval=0.3))}",
        f"RAM: {progress_bar(mem.percent)} ({human_size(mem.used)}/{human_size(mem.total)})",
        f"Disk: {progress_bar(disk.percent)} ({human_size(disk.used)}/{human_size(disk.total)})",
        f"Network: ⬆ {human_size(net.bytes_sent)} | ⬇ {human_size(net.bytes_recv)}",
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
                    cpu = pr.cpu_percent(interval=0.1)
                    ram = pr.memory_percent()
                    up = "-"
                    if r["started_at"]:
                        up = fmt_duration((datetime.now() - datetime.fromisoformat(r["started_at"])).total_seconds())
                    lines.append(
                        f"• {r['name']} [{r['runtime']}] 🟢 | PID {r['pid']} | CPU {cpu:.1f}% | RAM {ram:.1f}% | {up}"
                    )
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
            zf.extractall(config.SERVER_PATH)
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
        d["pending"] = "backup_restore"
        await update.message.reply_text("أرسل اسم ملف النسخة الاحتياطية (من مجلد backups):")
        return
    if text == BTN_BACKUP_SEND:
        d["pending"] = "backup_send"
        await update.message.reply_text("أرسل اسم ملف النسخة الاحتياطية لإرسالها:")
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
    markup, title = MENUS.get(name, (MAIN_MENU, "🏠 القائمة الرئيسية"))
    await show(update, title, markup)


async def handle_back(update: Update, d: dict) -> None:
    reset_pending(d)

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
        msg = start_bot_process(name)
        log_action(user_id, f"start bot {name}")
        await update.message.reply_text(msg)
        await refresh_bot_detail_message(update, name)
        return True
    if text == BOT_ACTION_STOP:
        msg = stop_bot_process(name)
        log_action(user_id, f"stop bot {name}")
        await update.message.reply_text(msg)
        await refresh_bot_detail_message(update, name)
        return True
    if text == BOT_ACTION_RESTART:
        stop_bot_process(name)
        await asyncio.sleep(1)
        msg = start_bot_process(name)
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
        name = text.strip()
        if db_get_bot(name):
            await update.message.reply_text("⚠️ يوجد بوت بهذا الاسم بالفعل. اختر اسماً آخر:")
            return
        d["data"]["bot_name"] = name
        d["pending"] = "bot_upload_file"
        await update.message.reply_text("الآن أرسل ملف ZIP يحتوي على كود البوت:")
        return

    if pending == "bot_rename":
        old = d["bot_selected"]
        new = text.strip()
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
            stop_bot_process(name)
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
    if pending == "backup_restore":
        reset_pending(d)
        await restore_backup(update, text)
        return
    if pending == "backup_send":
        reset_pending(d)
        await send_backup(update, text)
        return

    # --- file manager pending inputs ---------------------------------------
    if pending == "fm_mkdir":
        reset_pending(d)
        new_dir = Path(d["fm_path"]) / text.strip()
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
        parent = Path(d["fm_selected"])
        new_dir = parent / text.strip()
        new_dir.mkdir(parents=True, exist_ok=True)
        log_action(user_id, f"mkdir {new_dir}")
        await update.message.reply_text("✅ تم إنشاء المجلد.")
        return_to_filemanager(d)
        await render_fm(update, d)
        return

    if pending == "fm_rename_new_name":
        reset_pending(d)
        src = Path(d["fm_selected"])
        dst = src.parent / text.strip()
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
        dest = Path(d["fm_path"]) / doc.file_name
        tg_file = await doc.get_file()
        await tg_file.download_to_drive(str(dest))
        log_action(user_id, f"upload file {dest}")
        await update.message.reply_text(f"✅ تم رفع {doc.file_name}.")
        await render_fm(update, d)
        return

    if pending == "fm_upload_into_selected":
        reset_pending(d)
        parent = Path(d["fm_selected"])
        dest = parent / doc.file_name
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
                zf.extractall(bot_dir)
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
