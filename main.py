"""
Pyramid Server Manager
-----------------------
A single-owner Telegram bot that acts as a lightweight control panel for a
Linux VPS: bot process manager, file manager, terminal, resource monitor,
backups and settings. Reply-keyboard only UI, SQLite storage.

Run with:  python main.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import shlex
import shutil
import signal
import socket
import sqlite3
import subprocess
import time
import zipfile
from dataclasses import dataclass
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
# Buttons / menu labels
# =========================================================================

BTN_BACK = "⬅️ رجوع"
BTN_HOME = "🏠 الرئيسية"

BTN_BOTS = "🤖 إدارة البوتات"
BTN_FILES = "📁 إدارة الملفات"
BTN_SERVER_INFO = "🖥️ معلومات السيرفر"
BTN_TERMINAL = "💻 الطرفية"
BTN_MONITOR = "📊 مراقبة الموارد"
BTN_SETTINGS = "⚙️ الإعدادات"

BTN_BOT_START = "▶️ تشغيل بوت"
BTN_BOT_STOP = "⏹️ إيقاف بوت"
BTN_BOT_RESTART = "🔄 إعادة تشغيل بوت"
BTN_BOT_LOGS = "📄 عرض السجل"
BTN_BOT_LIST = "📋 عرض جميع البوتات"
BTN_BOT_UPLOAD = "⬆️ رفع بوت جديد"
BTN_BOT_DELETE = "🗑️ حذف بوت"

BTN_FILE_LIST = "📂 استعراض المجلد"
BTN_FILE_UPLOAD = "⬆️ رفع ملف"
BTN_FILE_DOWNLOAD = "⬇️ تنزيل ملف"
BTN_FILE_READ = "📖 قراءة ملف"
BTN_FILE_EDIT = "✏️ تعديل ملف"
BTN_FILE_NEW = "📄 إنشاء ملف"
BTN_FILE_MKDIR = "📁 إنشاء مجلد"
BTN_FILE_RENAME = "✏️ إعادة تسمية"
BTN_FILE_COPY = "📑 نسخ"
BTN_FILE_MOVE = "🚚 نقل"
BTN_FILE_DELETE = "🗑️ حذف"
BTN_FILE_ZIP = "🗜️ ضغط ZIP"
BTN_FILE_UNZIP = "📦 فك ضغط"
BTN_FILE_SEARCH = "🔍 بحث"
BTN_FILE_CLEAN = "🧹 تنظيف السيرفر"

BTN_BACKUP_CREATE = "💾 إنشاء نسخة احتياطية"
BTN_BACKUP_RESTORE = "♻️ استعادة نسخة"
BTN_BACKUP_SEND = "📤 إرسال نسخة"

BTN_SET_PASSWORD = "🔑 تغيير كلمة المرور"
BTN_SET_ADD_ADMIN = "➕ إضافة مدير"
BTN_SET_DEL_ADMIN = "➖ حذف مدير"
BTN_SET_NOTIFY = "🔔 تبديل الإشعارات"
BTN_SET_OPLOG = "🧾 سجل العمليات"
BTN_SET_BACKUP = "💾 النسخ الاحتياطي"

NAV_ROW = [BTN_BACK, BTN_HOME]


def kb(rows: list[list[str]]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(t) for t in row] for row in rows] + [NAV_ROW],
        resize_keyboard=True,
    )


MAIN_MENU = ReplyKeyboardMarkup(
    [
        [BTN_BOTS, BTN_FILES],
        [BTN_SERVER_INFO, BTN_TERMINAL],
        [BTN_MONITOR, BTN_SETTINGS],
    ],
    resize_keyboard=True,
)

BOTS_MENU = kb(
    [
        [BTN_BOT_START, BTN_BOT_STOP],
        [BTN_BOT_RESTART, BTN_BOT_LOGS],
        [BTN_BOT_LIST, BTN_BOT_UPLOAD],
        [BTN_BOT_DELETE],
    ]
)

FILES_MENU = kb(
    [
        [BTN_FILE_LIST, BTN_FILE_UPLOAD],
        [BTN_FILE_DOWNLOAD, BTN_FILE_READ],
        [BTN_FILE_EDIT, BTN_FILE_NEW],
        [BTN_FILE_MKDIR, BTN_FILE_RENAME],
        [BTN_FILE_COPY, BTN_FILE_MOVE],
        [BTN_FILE_DELETE, BTN_FILE_ZIP],
        [BTN_FILE_UNZIP, BTN_FILE_SEARCH],
        [BTN_FILE_CLEAN],
    ]
)

SETTINGS_MENU = kb(
    [
        [BTN_SET_PASSWORD],
        [BTN_SET_ADD_ADMIN, BTN_SET_DEL_ADMIN],
        [BTN_SET_NOTIFY, BTN_SET_OPLOG],
        [BTN_SET_BACKUP],
    ]
)

BACKUP_MENU = kb([[BTN_BACKUP_CREATE], [BTN_BACKUP_RESTORE], [BTN_BACKUP_SEND]])

LOCKED_KEYBOARD = None  # no keyboard for unauthenticated users

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
    cur = conn.execute("SELECT value FROM settings WHERE key='panel_password'")
    if cur.fetchone() is None:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('panel_password', ?)",
            (config.DEFAULT_PANEL_PASSWORD,),
        )
    cur = conn.execute("SELECT value FROM settings WHERE key='notifications'")
    if cur.fetchone() is None:
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
# In-memory session state (authenticated users, per-user navigation state)
# =========================================================================

AUTHENTICATED: set[int] = set()
USER_STATE: dict[int, dict] = {}  # user_id -> {"pending": str, "data": {...}}


def get_state(user_id: int) -> dict:
    return USER_STATE.setdefault(user_id, {"pending": None, "data": {}})


def reset_pending(user_id: int) -> None:
    USER_STATE.setdefault(user_id, {})["pending"] = None
    USER_STATE.setdefault(user_id, {})["data"] = {}


# =========================================================================
# Helpers
# =========================================================================


def safe_path(rel: str) -> Optional[Path]:
    """Resolve a user-supplied relative path inside SERVER_PATH, refusing
    anything that escapes the root directory."""
    base = Path(config.SERVER_PATH).resolve()
    try:
        target = (base / rel).resolve()
    except Exception:
        return None
    if base == target or base in target.parents:
        return target
    return None


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


async def run_shell(command: str, timeout: int = config.COMMAND_TIMEOUT) -> str:
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=config.SERVER_PATH,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return "⏱️ انتهت المهلة، تم إيقاف الأمر."
        text = out.decode(errors="replace")
        return text if text.strip() else "(لا يوجد ناتج)"
    except Exception as exc:  # noqa: BLE001
        return f"❌ خطأ: {exc}"


def trim(text: str) -> str:
    if len(text) > config.MAX_OUTPUT_CHARS:
        return text[: config.MAX_OUTPUT_CHARS] + "\n... (تم اقتصاص الناتج)"
    return text


async def notify_owner(app: Application, text: str) -> None:
    if get_setting("notifications", "1") == "1":
        try:
            await app.bot.send_message(chat_id=config.OWNER_ID, text=text)
        except Exception:  # noqa: BLE001
            log.exception("Failed to notify owner")


# =========================================================================
# Bot process management
# =========================================================================

RUNTIME_ENTRY = {
    "python": ("requirements.txt", ["python3", "{entry}"]),
    "node": ("package.json", ["node", "{entry}"]),
    "php": (None, ["php", "{entry}"]),
    "java": (None, ["java", "-jar", "{entry}"]),
}

RUNNING_PROCS: dict[str, subprocess.Popen] = {}


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
    rows = conn.execute("SELECT * FROM bots").fetchall()
    conn.close()
    return rows


def db_set_bot_status(name: str, status: str, pid: Optional[int]):
    conn = db_connect()
    conn.execute("UPDATE bots SET status=?, pid=? WHERE name=?", (status, pid, name))
    conn.commit()
    conn.close()


def db_delete_bot(name: str):
    conn = db_connect()
    conn.execute("DELETE FROM bots WHERE name=?", (name,))
    conn.commit()
    conn.close()


def start_bot_process(name: str) -> str:
    row = db_get_bot(name)
    if row is None:
        return "❌ البوت غير موجود."
    if name in RUNNING_PROCS and RUNNING_PROCS[name].poll() is None:
        return "⚠️ البوت يعمل بالفعل."
    template = RUNTIME_ENTRY[row["runtime"]][1]
    cmd = [part.format(entry=row["entry"]) for part in template]
    log_file = Path(row["path"]) / "bot.log"
    try:
        with open(log_file, "ab") as lf:
            proc = subprocess.Popen(
                cmd,
                cwd=row["path"],
                stdout=lf,
                stderr=lf,
                start_new_session=True,
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
            cwd=path,
            capture_output=True,
            text=True,
            timeout=300,
        )
        return r.stdout[-1500:] + r.stderr[-1500:]
    if runtime == "node" and (path / "package.json").exists():
        r = subprocess.run(
            ["npm", "install"], cwd=path, capture_output=True, text=True, timeout=300
        )
        return r.stdout[-1500:] + r.stderr[-1500:]
    return "(لا توجد متطلبات للتثبيت)"


async def watchdog_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Periodically checks running bots and restarts crashed ones."""
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


# =========================================================================
# Menu / navigation utilities
# =========================================================================


async def show(update: Update, text: str, markup) -> None:
    await update.message.reply_text(text, reply_markup=markup)


def push_menu(state: dict, name: str) -> None:
    state.setdefault("stack", ["main"])
    if state["stack"][-1] != name:
        state["stack"].append(name)


def pop_menu(state: dict) -> str:
    stack = state.setdefault("stack", ["main"])
    if len(stack) > 1:
        stack.pop()
    return stack[-1]


MENUS = {
    "main": (MAIN_MENU, "🏠 القائمة الرئيسية"),
    "bots": (BOTS_MENU, "🤖 إدارة البوتات"),
    "files": (FILES_MENU, "📁 إدارة الملفات"),
    "settings": (SETTINGS_MENU, "⚙️ الإعدادات"),
    "backup": (BACKUP_MENU, "💾 النسخ الاحتياطي"),
}


async def goto(update: Update, state: dict, name: str) -> None:
    push_menu(state, name)
    markup, title = MENUS[name]
    await show(update, title, markup)


# =========================================================================
# Command / message handlers
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

    if user_id in AUTHENTICATED:
        state = get_state(user_id)
        state["stack"] = ["main"]
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

    state = get_state(user_id)
    state["pending"] = "await_password"
    await update.message.reply_text("🔒 أدخل كلمة مرور لوحة التحكم.")


async def handle_password(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    user_id = update.effective_user.id
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
        reset_pending(user_id)
        get_state(user_id)["stack"] = ["main"]
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
        reset_pending(user_id)
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


# --- Text router ----------------------------------------------------------


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if not is_admin(user_id):
        return  # silently ignore, matches spec: stop responding entirely

    state = get_state(user_id)

    if user_id not in AUTHENTICATED:
        if state.get("pending") == "await_password":
            await handle_password(update, context, text)
        else:
            await start(update, context)
        return

    # Navigation
    if text == BTN_HOME:
        reset_pending(user_id)
        state["stack"] = ["main"]
        await show(update, "🏠 القائمة الرئيسية", MAIN_MENU)
        return
    if text == BTN_BACK:
        reset_pending(user_id)
        name = pop_menu(state)
        markup, title = MENUS[name]
        await show(update, title, markup)
        return

    # If a multi-step action is pending, route to its follow-up handler
    if state.get("pending"):
        await handle_pending(update, context, text)
        return

    # Main menu
    if text == BTN_BOTS:
        await goto(update, state, "bots")
        return
    if text == BTN_FILES:
        await goto(update, state, "files")
        return
    if text == BTN_SETTINGS:
        await goto(update, state, "settings")
        return
    if text == BTN_SERVER_INFO:
        await send_server_info(update)
        return
    if text == BTN_MONITOR:
        await send_monitor(update)
        return
    if text == BTN_TERMINAL:
        state["pending"] = "terminal_cmd"
        await update.message.reply_text("💻 أرسل أمر Linux لتنفيذه:")
        return

    # Bots submenu
    if text == BTN_BOT_LIST:
        await bot_list(update)
        return
    if text == BTN_BOT_START:
        state["pending"] = "bot_start"
        await update.message.reply_text("أرسل اسم البوت المراد تشغيله:")
        return
    if text == BTN_BOT_STOP:
        state["pending"] = "bot_stop"
        await update.message.reply_text("أرسل اسم البوت المراد إيقافه:")
        return
    if text == BTN_BOT_RESTART:
        state["pending"] = "bot_restart"
        await update.message.reply_text("أرسل اسم البوت المراد إعادة تشغيله:")
        return
    if text == BTN_BOT_LOGS:
        state["pending"] = "bot_logs"
        await update.message.reply_text("أرسل اسم البوت لعرض سجله:")
        return
    if text == BTN_BOT_DELETE:
        state["pending"] = "bot_delete"
        await update.message.reply_text("أرسل اسم البوت المراد حذفه:")
        return
    if text == BTN_BOT_UPLOAD:
        state["pending"] = "bot_upload_name"
        await update.message.reply_text("أرسل اسماً للبوت الجديد:")
        return

    # Files submenu
    if text == BTN_FILE_LIST:
        state["pending"] = "file_list"
        await update.message.reply_text("أرسل مسار المجلد (نسبةً للجذر) أو '.' للجذر:")
        return
    if text == BTN_FILE_UPLOAD:
        state["pending"] = "file_upload_path"
        await update.message.reply_text("أرسل مسار المجلد الوجهة ثم أرفق الملف:")
        return
    if text == BTN_FILE_DOWNLOAD:
        state["pending"] = "file_download"
        await update.message.reply_text("أرسل مسار الملف المراد تنزيله:")
        return
    if text == BTN_FILE_READ:
        state["pending"] = "file_read"
        await update.message.reply_text("أرسل مسار الملف النصي لقراءته:")
        return
    if text == BTN_FILE_EDIT:
        state["pending"] = "file_edit_path"
        await update.message.reply_text("أرسل مسار الملف المراد تعديله:")
        return
    if text == BTN_FILE_NEW:
        state["pending"] = "file_new_path"
        await update.message.reply_text("أرسل مسار الملف الجديد:")
        return
    if text == BTN_FILE_MKDIR:
        state["pending"] = "file_mkdir"
        await update.message.reply_text("أرسل مسار المجلد الجديد:")
        return
    if text == BTN_FILE_RENAME:
        state["pending"] = "file_rename_src"
        await update.message.reply_text("أرسل المسار الحالي:")
        return
    if text == BTN_FILE_COPY:
        state["pending"] = "file_copy_src"
        await update.message.reply_text("أرسل مسار المصدر:")
        return
    if text == BTN_FILE_MOVE:
        state["pending"] = "file_move_src"
        await update.message.reply_text("أرسل مسار المصدر:")
        return
    if text == BTN_FILE_DELETE:
        state["pending"] = "file_delete"
        await update.message.reply_text("أرسل مسار الملف/المجلد المراد حذفه:")
        return
    if text == BTN_FILE_ZIP:
        state["pending"] = "file_zip"
        await update.message.reply_text("أرسل مسار المجلد/الملف المراد ضغطه:")
        return
    if text == BTN_FILE_UNZIP:
        state["pending"] = "file_unzip"
        await update.message.reply_text("أرسل مسار ملف ZIP لفك ضغطه:")
        return
    if text == BTN_FILE_SEARCH:
        state["pending"] = "file_search"
        await update.message.reply_text("أرسل جزءاً من اسم الملف للبحث عنه:")
        return
    if text == BTN_FILE_CLEAN:
        await clean_server(update)
        return

    # Settings submenu
    if text == BTN_SET_PASSWORD:
        state["pending"] = "set_password"
        await update.message.reply_text("أرسل كلمة المرور الجديدة:")
        return
    if text == BTN_SET_ADD_ADMIN:
        state["pending"] = "add_admin"
        await update.message.reply_text("أرسل معرف المستخدم (ID) المراد إضافته كمدير:")
        return
    if text == BTN_SET_DEL_ADMIN:
        state["pending"] = "del_admin"
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
        await goto(update, state, "backup")
        return

    # Backup submenu
    if text == BTN_BACKUP_CREATE:
        await create_backup(update)
        return
    if text == BTN_BACKUP_RESTORE:
        state["pending"] = "backup_restore"
        await update.message.reply_text("أرسل اسم ملف النسخة الاحتياطية (من مجلد backups):")
        return
    if text == BTN_BACKUP_SEND:
        state["pending"] = "backup_send"
        await update.message.reply_text("أرسل اسم ملف النسخة الاحتياطية لإرسالها:")
        return

    await update.message.reply_text("لم أفهم الأمر، الرجاء استخدام الأزرار.")


# --- Pending (multi-step) action handling ---------------------------------


async def handle_pending(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    user_id = update.effective_user.id
    state = get_state(user_id)
    pending = state["pending"]

    if pending == "terminal_cmd":
        reset_pending(user_id)
        log_action(user_id, f"terminal: {text}")
        out = await run_shell(text)
        await update.message.reply_text(f"```\n{trim(out)}\n```", parse_mode=ParseMode.MARKDOWN)
        return

    if pending == "bot_start":
        reset_pending(user_id)
        msg = start_bot_process(text)
        log_action(user_id, f"start bot {text}")
        await update.message.reply_text(msg)
        return
    if pending == "bot_stop":
        reset_pending(user_id)
        msg = stop_bot_process(text)
        log_action(user_id, f"stop bot {text}")
        await update.message.reply_text(msg)
        return
    if pending == "bot_restart":
        reset_pending(user_id)
        stop_bot_process(text)
        await asyncio.sleep(1)
        msg = start_bot_process(text)
        log_action(user_id, f"restart bot {text}")
        await update.message.reply_text(msg)
        return
    if pending == "bot_logs":
        reset_pending(user_id)
        row = db_get_bot(text)
        if not row:
            await update.message.reply_text("❌ البوت غير موجود.")
            return
        log_file = Path(row["path"]) / "bot.log"
        if not log_file.exists():
            await update.message.reply_text("(لا يوجد سجل بعد)")
            return
        content = log_file.read_text(errors="replace")[-config.MAX_OUTPUT_CHARS :]
        await update.message.reply_text(f"```\n{content}\n```", parse_mode=ParseMode.MARKDOWN)
        return
    if pending == "bot_delete":
        reset_pending(user_id)
        row = db_get_bot(text)
        if not row:
            await update.message.reply_text("❌ البوت غير موجود.")
            return
        stop_bot_process(text)
        shutil.rmtree(row["path"], ignore_errors=True)
        db_delete_bot(text)
        log_action(user_id, f"delete bot {text}")
        await update.message.reply_text(f"🗑️ تم حذف {text}.")
        return
    if pending == "bot_upload_name":
        name = text.strip()
        if db_get_bot(name):
            await update.message.reply_text("⚠️ يوجد بوت بهذا الاسم بالفعل. اختر اسماً آخر:")
            return
        state["data"]["bot_name"] = name
        state["pending"] = "bot_upload_file"
        await update.message.reply_text("الآن أرسل ملف ZIP يحتوي على كود البوت:")
        return

    # File manager text-step handlers
    if pending == "file_list":
        reset_pending(user_id)
        await list_dir(update, text)
        return
    if pending == "file_upload_path":
        target = safe_path(text)
        if target is None:
            await update.message.reply_text("❌ مسار غير صالح.")
            reset_pending(user_id)
            return
        state["data"]["upload_dir"] = str(target)
        state["pending"] = "file_upload_file"
        await update.message.reply_text("الآن أرفق الملف لرفعه:")
        return
    if pending == "file_download":
        reset_pending(user_id)
        await download_file(update, text)
        return
    if pending == "file_read":
        reset_pending(user_id)
        await read_file(update, text)
        return
    if pending == "file_edit_path":
        p = safe_path(text)
        if p is None or not p.is_file():
            await update.message.reply_text("❌ ملف غير موجود.")
            reset_pending(user_id)
            return
        state["data"]["edit_path"] = str(p)
        state["pending"] = "file_edit_content"
        await update.message.reply_text("أرسل المحتوى الجديد الكامل للملف:")
        return
    if pending == "file_edit_content":
        reset_pending(user_id)
        p = Path(state["data"]["edit_path"])
        p.write_text(text, encoding="utf-8")
        log_action(user_id, f"edit file {p}")
        await update.message.reply_text("✅ تم حفظ الملف.")
        return
    if pending == "file_new_path":
        p = safe_path(text)
        if p is None:
            await update.message.reply_text("❌ مسار غير صالح.")
            reset_pending(user_id)
            return
        state["data"]["new_path"] = str(p)
        state["pending"] = "file_new_content"
        await update.message.reply_text("أرسل محتوى الملف (أو أرسل - لإنشاء ملف فارغ):")
        return
    if pending == "file_new_content":
        reset_pending(user_id)
        p = Path(state["data"]["new_path"])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("" if text == "-" else text, encoding="utf-8")
        log_action(user_id, f"create file {p}")
        await update.message.reply_text("✅ تم إنشاء الملف.")
        return
    if pending == "file_mkdir":
        reset_pending(user_id)
        p = safe_path(text)
        if p is None:
            await update.message.reply_text("❌ مسار غير صالح.")
            return
        p.mkdir(parents=True, exist_ok=True)
        log_action(user_id, f"mkdir {p}")
        await update.message.reply_text("✅ تم إنشاء المجلد.")
        return
    if pending == "file_rename_src":
        p = safe_path(text)
        if p is None or not p.exists():
            await update.message.reply_text("❌ غير موجود.")
            reset_pending(user_id)
            return
        state["data"]["rename_src"] = str(p)
        state["pending"] = "file_rename_dst"
        await update.message.reply_text("أرسل الاسم/المسار الجديد:")
        return
    if pending == "file_rename_dst":
        reset_pending(user_id)
        dst = safe_path(text)
        if dst is None:
            await update.message.reply_text("❌ مسار غير صالح.")
            return
        Path(state["data"]["rename_src"]).rename(dst)
        log_action(user_id, f"rename to {dst}")
        await update.message.reply_text("✅ تمت إعادة التسمية.")
        return
    if pending == "file_copy_src":
        p = safe_path(text)
        if p is None or not p.exists():
            await update.message.reply_text("❌ غير موجود.")
            reset_pending(user_id)
            return
        state["data"]["copy_src"] = str(p)
        state["pending"] = "file_copy_dst"
        await update.message.reply_text("أرسل المسار الوجهة:")
        return
    if pending == "file_copy_dst":
        reset_pending(user_id)
        dst = safe_path(text)
        if dst is None:
            await update.message.reply_text("❌ مسار غير صالح.")
            return
        src = Path(state["data"]["copy_src"])
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        log_action(user_id, f"copy {src} -> {dst}")
        await update.message.reply_text("✅ تم النسخ.")
        return
    if pending == "file_move_src":
        p = safe_path(text)
        if p is None or not p.exists():
            await update.message.reply_text("❌ غير موجود.")
            reset_pending(user_id)
            return
        state["data"]["move_src"] = str(p)
        state["pending"] = "file_move_dst"
        await update.message.reply_text("أرسل المسار الوجهة:")
        return
    if pending == "file_move_dst":
        reset_pending(user_id)
        dst = safe_path(text)
        if dst is None:
            await update.message.reply_text("❌ مسار غير صالح.")
            return
        shutil.move(state["data"]["move_src"], dst)
        log_action(user_id, f"move -> {dst}")
        await update.message.reply_text("✅ تم النقل.")
        return
    if pending == "file_delete":
        reset_pending(user_id)
        p = safe_path(text)
        if p is None or not p.exists():
            await update.message.reply_text("❌ غير موجود.")
            return
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        log_action(user_id, f"delete {p}")
        await update.message.reply_text("🗑️ تم الحذف.")
        return
    if pending == "file_zip":
        reset_pending(user_id)
        await zip_path(update, text)
        return
    if pending == "file_unzip":
        reset_pending(user_id)
        await unzip_path(update, text)
        return
    if pending == "file_search":
        reset_pending(user_id)
        await search_files(update, text)
        return

    if pending == "set_password":
        reset_pending(user_id)
        set_setting("panel_password", text)
        log_action(user_id, "changed panel password")
        await update.message.reply_text("✅ تم تغيير كلمة المرور.")
        return
    if pending == "add_admin":
        reset_pending(user_id)
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
        reset_pending(user_id)
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
        reset_pending(user_id)
        await restore_backup(update, text)
        return
    if pending == "backup_send":
        reset_pending(user_id)
        await send_backup(update, text)
        return

    reset_pending(user_id)
    await update.message.reply_text("تم إلغاء العملية.")


# --- File manager operations ------------------------------------------


async def list_dir(update: Update, rel: str) -> None:
    p = safe_path(rel)
    if p is None or not p.exists() or not p.is_dir():
        await update.message.reply_text("❌ مجلد غير صالح.")
        return
    entries = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    if not entries:
        await update.message.reply_text("(المجلد فارغ)")
        return
    lines = []
    for e in entries[:200]:
        tag = "📁" if e.is_dir() else "📄"
        size = "" if e.is_dir() else f" ({human_size(e.stat().st_size)})"
        lines.append(f"{tag} {e.name}{size}")
    await update.message.reply_text("\n".join(lines))


async def download_file(update: Update, rel: str) -> None:
    p = safe_path(rel)
    if p is None or not p.is_file():
        await update.message.reply_text("❌ ملف غير موجود.")
        return
    if p.stat().st_size > config.MAX_FILE_SIZE:
        await update.message.reply_text("❌ الملف كبير جداً للإرسال عبر تيليجرام.")
        return
    with open(p, "rb") as f:
        await update.message.reply_document(f, filename=p.name)


async def read_file(update: Update, rel: str) -> None:
    p = safe_path(rel)
    if p is None or not p.is_file():
        await update.message.reply_text("❌ ملف غير موجود.")
        return
    try:
        content = p.read_text(errors="replace")
    except Exception as exc:  # noqa: BLE001
        await update.message.reply_text(f"❌ لا يمكن قراءة الملف: {exc}")
        return
    await update.message.reply_text(f"```\n{trim(content)}\n```", parse_mode=ParseMode.MARKDOWN)


async def zip_path(update: Update, rel: str) -> None:
    p = safe_path(rel)
    if p is None or not p.exists():
        await update.message.reply_text("❌ غير موجود.")
        return
    out = p.with_suffix(p.suffix + ".zip") if p.is_file() else Path(str(p) + ".zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        if p.is_file():
            zf.write(p, p.name)
        else:
            for root, _, files in os.walk(p):
                for name in files:
                    full = Path(root) / name
                    zf.write(full, full.relative_to(p.parent))
    await update.message.reply_text(f"✅ تم إنشاء {out.name}")


async def unzip_path(update: Update, rel: str) -> None:
    p = safe_path(rel)
    if p is None or not p.is_file() or p.suffix != ".zip":
        await update.message.reply_text("❌ ملف ZIP غير صالح.")
        return
    dest = p.parent / p.stem
    try:
        with zipfile.ZipFile(p) as zf:
            zf.extractall(dest)
        await update.message.reply_text(f"✅ تم فك الضغط إلى {dest.name}/")
    except Exception as exc:  # noqa: BLE001
        await update.message.reply_text(f"❌ فشل فك الضغط: {exc}")


async def search_files(update: Update, term: str) -> None:
    base = Path(config.SERVER_PATH)
    matches = []
    for root, dirs, files in os.walk(base):
        for name in files:
            if term.lower() in name.lower():
                matches.append(str((Path(root) / name).relative_to(base)))
                if len(matches) >= 50:
                    break
        if len(matches) >= 50:
            break
    if not matches:
        await update.message.reply_text("لا توجد نتائج.")
        return
    await update.message.reply_text("\n".join(matches))


async def clean_server(update: Update) -> None:
    base = Path(config.SERVER_PATH)
    freed = 0
    removed = 0
    now = time.time()
    for root, dirs, files in os.walk(base):
        if "__pycache__" in dirs:
            pcache = Path(root) / "__pycache__"
            freed += sum(f.stat().st_size for f in pcache.rglob("*") if f.is_file())
            shutil.rmtree(pcache, ignore_errors=True)
            dirs.remove("__pycache__")
            removed += 1
        for name in list(files):
            fp = Path(root) / name
            try:
                st = fp.stat()
            except FileNotFoundError:
                continue
            is_pyc = name.endswith(".pyc")
            is_empty = st.st_size == 0
            is_old_log = name.endswith(".log") and (now - st.st_mtime) > 30 * 86400
            is_temp_zip = name.endswith(".tmp.zip") or name.endswith(".part")
            if is_pyc or is_empty or is_old_log or is_temp_zip:
                freed += st.st_size
                fp.unlink(missing_ok=True)
                removed += 1
    await update.message.reply_text(
        f"🧹 تم التنظيف.\nالملفات المحذوفة: {removed}\nالمساحة المحررة: {human_size(freed)}"
    )


# --- Bot management views ------------------------------------------------


async def bot_list(update: Update) -> None:
    rows = db_all_bots()
    if not rows:
        await update.message.reply_text("لا توجد بوتات مضافة بعد.")
        return
    lines = [f"• {r['name']} [{r['runtime']}] — {r['status']} (PID: {r['pid'] or '-'})" for r in rows]
    await update.message.reply_text("\n".join(lines))


# --- Server info / monitoring -------------------------------------------


def get_version(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr) else "غير مثبت"
    except Exception:
        return "غير مثبت"


async def send_server_info(update: Update) -> None:
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage(config.SERVER_PATH)
    uptime = timedelta(seconds=int(time.time() - psutil.boot_time()))
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        ip = "غير معروف"

    text = (
        f"🖥️ *معلومات السيرفر*\n"
        f"CPU: {cpu}%\n"
        f"RAM: {human_size(mem.used)} / {human_size(mem.total)} ({mem.percent}%)\n"
        f"Disk: {human_size(disk.used)} / {human_size(disk.total)} ({disk.percent}%)\n"
        f"Uptime: {uptime}\n"
        f"Python: {platform.python_version()}\n"
        f"PHP: {get_version(['php', '-v'])}\n"
        f"Node: {get_version(['node', '-v'])}\n"
        f"Java: {get_version(['java', '-version'])}\n"
        f"Kernel: {platform.release()}\n"
        f"Hostname: {socket.gethostname()}\n"
        f"IP: {ip}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def send_monitor(update: Update) -> None:
    procs = sorted(
        psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]),
        key=lambda p: p.info["cpu_percent"] or 0,
        reverse=True,
    )[:8]
    lines = ["📊 *أكثر العمليات استهلاكاً:*"]
    for p in procs:
        lines.append(
            f"PID {p.info['pid']} | {p.info['name']} | CPU {p.info['cpu_percent']:.1f}% | RAM {p.info['memory_percent']:.1f}%"
        )

    lines.append("\n🤖 *استهلاك البوتات:*")
    rows = db_all_bots()
    if not rows:
        lines.append("(لا توجد بوتات)")
    for r in rows:
        if r["pid"] and psutil.pid_exists(r["pid"]):
            try:
                pr = psutil.Process(r["pid"])
                lines.append(
                    f"{r['name']}: CPU {pr.cpu_percent(interval=0.1):.1f}% | "
                    f"RAM {pr.memory_percent():.1f}% | PID {r['pid']} | {r['status']}"
                )
                continue
            except Exception:
                pass
        lines.append(f"{r['name']}: {r['status']} (PID: -)")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def send_oplog(update: Update) -> None:
    conn = db_connect()
    rows = conn.execute("SELECT * FROM oplog ORDER BY id DESC LIMIT 30").fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("لا يوجد سجل عمليات بعد.")
        return
    lines = [f"[{r['ts']}] user {r['user_id']}: {r['action']}" for r in rows]
    await update.message.reply_text(trim("\n".join(lines)))


# --- Backups --------------------------------------------------------------


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
    except Exception as exc:  # noqa: BLE001
        await update.message.reply_text(f"❌ فشلت الاستعادة: {exc}")


async def send_backup(update: Update, name: str) -> None:
    src = Path(config.BACKUPS_DIR) / name
    if not src.exists():
        await update.message.reply_text("❌ الملف غير موجود.")
        return
    with open(src, "rb") as f:
        await update.message.reply_document(f, filename=src.name)


# --- Document (file/bot upload) handler -----------------------------------


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_admin(user_id) or user_id not in AUTHENTICATED:
        return
    state = get_state(user_id)
    pending = state.get("pending")
    doc = update.message.document

    if doc.file_size and doc.file_size > config.MAX_FILE_SIZE:
        await update.message.reply_text("❌ الملف أكبر من الحد المسموح.")
        return

    if pending == "file_upload_file":
        reset_pending(user_id)
        dest_dir = Path(state["data"]["upload_dir"])
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / doc.file_name
        tg_file = await doc.get_file()
        await tg_file.download_to_drive(str(dest))
        log_action(user_id, f"upload file {dest}")
        await update.message.reply_text(f"✅ تم رفع {doc.file_name}.")
        return

    if pending == "bot_upload_file":
        reset_pending(user_id)
        name = state["data"]["bot_name"]
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
        await update.message.reply_text(f"✅ تم إعداد البوت.\n```\n{trim(result)}\n```", parse_mode=ParseMode.MARKDOWN)
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

    app = Application.builder().token(config.BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.COMMAND, lambda u, c: start(u, c)))

    if app.job_queue:
        app.job_queue.run_repeating(watchdog_job, interval=config.WATCHDOG_INTERVAL, first=config.WATCHDOG_INTERVAL)

    log.info("Pyramid Server Manager starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
