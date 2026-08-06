"""
Pyramid Server Manager - Configuration
Fill in your bot token, your Telegram numeric user ID, and a control-panel
password below before running main.py.
"""

import os

# --- Required settings -------------------------------------------------

# Token from @BotFather
BOT_TOKEN: str = "8933297746:AAEECEnJsqKSATbowWpu80i04oRZ2wdUt-o"

# Your numeric Telegram user ID (get it from @userinfobot). Only this user
# (plus any admins added later from inside the bot) can use the panel.
OWNER_ID: int = 0

# Default control-panel password. Can be changed later from the Settings
# menu (the new password is stored in the database, this value is only
# used the very first time the bot runs).
DEFAULT_PANEL_PASSWORD: str = "#13579@Pyr4mid#"

# --- Paths ---------------------------------------------------------------

# Root directory the file manager / bot manager will operate under.
SERVER_PATH: str = os.path.abspath(os.path.expanduser("~/pyramid_data"))

BOTS_DIR: str = os.path.join(SERVER_PATH, "bots")
BACKUPS_DIR: str = os.path.join(SERVER_PATH, "backups")
DB_PATH: str = os.path.join(SERVER_PATH, "pyramid.db")

# Root directory the real file manager browses from (whole-system browsing,
# not sandboxed to SERVER_PATH). Navigation cannot go above this directory.
FS_ROOT: str = "/root"

# Used to look up the VPS's external/public IP for the server info screen.
EXTERNAL_IP_SERVICE: str = "https://ifconfig.me/ip"

# --- Security / behaviour ------------------------------------------------

MAX_LOGIN_ATTEMPTS: int = 5
LOCKOUT_MINUTES: int = 15

# Max bytes for a single upload/download through Telegram (Telegram bot API
# hard limit is ~50MB for bot-uploaded files without a local Bot API server).
MAX_FILE_SIZE: int = 45 * 1024 * 1024

# Max characters of terminal / log output sent back in one Telegram message.
MAX_OUTPUT_CHARS: int = 3500

# Seconds a terminal command is allowed to run before being killed.
COMMAND_TIMEOUT: int = 60

# How often (seconds) the background watchdog checks on running bots.
WATCHDOG_INTERVAL: int = 60

for _d in (SERVER_PATH, BOTS_DIR, BACKUPS_DIR):
    os.makedirs(_d, exist_ok=True)
