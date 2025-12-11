#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import zipfile
import shutil
import subprocess
import re
import psutil
import telebot
from telebot.types import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton

# ================== CONFIG (EDIT THESE) ==================
BOT_TOKEN = "8419880200:AAG5OpgB0BG7FOpN-XrUu_7y3hGJKmWimI4"      # <- yahan apna bot token
VPS_IP   = "13.232.215.220"          # <- yahan apna VPS IP (e.g. 203.0.113.10)
OWNER_ID = 7652176329              # <- apna telegram user id
ADMINS   = [OWNER_ID]             # extra admins id list me add kar sakta hai

BASE_DIR = "user_apps"
LOG_DIR  = "logs"
PORT_START = 9000
# =========================================================

bot = telebot.TeleBot(BOT_TOKEN)

running        = {}      # uid -> subprocess.Popen
pending        = {}      # (uid, filename) -> metadata
user_logs      = {}      # uid -> username
notified_users = set()   # jinko owner ko already notify kiya

os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs("tmp_photos", exist_ok=True)


# ================== BASIC HELPERS ==================
def get_user_dir(uid: int) -> str:
    path = os.path.join(BASE_DIR, str(uid))
    os.makedirs(path, exist_ok=True)
    return path


def assign_port(uid: int) -> int:
    return PORT_START + (int(uid) % 1000)


def stop_app(uid: int):
    if uid in running:
        proc = running[uid]
        try:
            proc.terminate()
            time.sleep(0.5)
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass
        running.pop(uid, None)


def detect_and_run_safe(path: str, port: int):
    """
    Project folder ko dekh ke safe predefined commands se run karega.
    System me jo installed hai wahi use karega.
    Returns: (app_type, process, error_msg)
    """
    path = os.path.abspath(path)

    def exists(f):
        return os.path.exists(os.path.join(path, f))

    # 1) Static HTML
    if exists("index.html"):
        cmd = ["python3", "-m", "http.server", str(port)]
        proc = subprocess.Popen(cmd, cwd=path)
        return "HTML", proc, None

    # 2) Python (Flask/FastAPI) - app.py / main.py with "app"
    if exists("app.py") or exists("main.py"):
        pyfile = "app.py" if exists("app.py") else "main.py"
        module = pyfile.rsplit(".", 1)[0]
        gunicorn_path = shutil.which("gunicorn")
        uvicorn_path  = shutil.which("uvicorn")

        if gunicorn_path:
            cmd = [gunicorn_path, f"{module}:app", "--bind", f"0.0.0.0:{port}"]
            proc = subprocess.Popen(cmd, cwd=path)
            return "Python (gunicorn)", proc, None

        if uvicorn_path:
            cmd = [uvicorn_path, f"{module}:app", "--host", "0.0.0.0", "--port", str(port)]
            proc = subprocess.Popen(cmd, cwd=path)
            return "Python (uvicorn)", proc, None

        # fallback
        cmd = ["python3", pyfile]
        proc = subprocess.Popen(cmd, cwd=path)
        return "Python (direct)", proc, "gunicorn/uvicorn missing, running via python3 directly."

    # 3) Node.js (server.js)
    if exists("server.js"):
        node_path = shutil.which("node")
        if not node_path:
            return None, None, "Node.js (node) not installed on server."
        cmd = [node_path, "server.js"]
        proc = subprocess.Popen(cmd, cwd=path)
        return "Node.js", proc, None

    # 4) PHP (index.php)
    if exists("index.php"):
        php_path = shutil.which("php")
        if not php_path:
            return None, None, "PHP not installed on server."
        cmd = [php_path, "-S", f"0.0.0.0:{port}", "index.php"]
        proc = subprocess.Popen(cmd, cwd=path)
        return "PHP", proc, None

    return None, None, "No supported entry found (index.html, app.py/main.py, server.js, index.php)."


# ================== MALWARE / SUSPICIOUS CHECK ==================
def find_text_files(root_dir):
    """Common text-like files."""
    text_ext = ('.py', '.js', '.sh', '.php', '.html', '.css', '.json',
                '.yaml', '.yml', '.txt', '.env')
    for dirpath, _, filenames in os.walk(root_dir):
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            ext = os.path.splitext(fn)[1].lower()
            if ext in text_ext:
                yield fp
            else:
                try:
                    if os.path.getsize(fp) < 200000:
                        with open(fp, 'rb') as f:
                            chunk = f.read(4096)
                            if b'\0' not in chunk:
                                yield fp
                except Exception:
                    continue


def has_large_base64(fp):
    try:
        with open(fp, 'r', errors='ignore') as f:
            data = f.read()
        # long base64 blobs
        matches = re.findall(r'([A-Za-z0-9+/=]{200,})', data)
        return bool(matches)
    except Exception:
        return False


def contains_suspicious_strings(fp):
    patterns = [
        r'rm\s+-rf', r'wget\s+http', r'curl\s+http', r'base64\s+-d',
        r'openssl\s+enc', r'nc\s+-e', r'nc\s+.*-l', r'bash\s+-i',
        r'python\s+-c', r'os\.system\(', r'subprocess\.Popen',
        r'eval\(', r'exec\(', r'base64\.b64decode', r'socket\.', r'ReverseShell'
    ]
    try:
        with open(fp, 'r', errors='ignore') as f:
            txt = f.read()
        for pat in patterns:
            if re.search(pat, txt, flags=re.IGNORECASE):
                return True
    except Exception:
        return False
    return False


def has_executable_binaries(root_dir):
    exe_exts = ('.exe', '.dll', '.so', '.bin', '.elf', '.apk')
    for dirpath, _, filenames in os.walk(root_dir):
        for fn in filenames:
            if fn.lower().endswith(exe_exts):
                return True
    return False


def suspicious_filenames(root_dir):
    sus_names = ['payload', 'backdoor', 'reverse', 'shell', 'rat', 'dropper']
    for dirpath, _, filenames in os.walk(root_dir):
        for fn in filenames:
            nm = fn.lower()
            for s in sus_names:
                if s in nm:
                    return True
    return False


def is_malicious(root_dir):
    """
    Simple heuristic: true = suspicious / possible malware.
    Returns (bool_is_suspicious, reasons_list)
    """
    reasons = []
    if has_executable_binaries(root_dir):
        reasons.append("Binary/executable files found (.exe/.so/.elf/.apk).")
    if suspicious_filenames(root_dir):
        reasons.append("Suspicious filename like payload/backdoor/shell/etc.")
    for fp in find_text_files(root_dir):
        rel = os.path.relpath(fp, root_dir)
        if contains_suspicious_strings(fp):
            reasons.append(f"Suspicious code pattern in {rel}")
        if has_large_base64(fp):
            reasons.append(f"Large base64 blob in {rel}")
    reasons = list(dict.fromkeys(reasons))
    return (len(reasons) > 0, reasons)


# ================== PROFILE / OWNER NOTIFY ==================
def fetch_user_profile_info(uid: int):
    first = ""
    username = ""
    bio = ""
    photo_path = None
    try:
        chat = bot.get_chat(uid)
        first = chat.first_name or ""
        username = getattr(chat, "username", "") or ""
        bio = getattr(chat, "bio", "") or ""
    except Exception:
        pass

    try:
        photos = bot.get_user_profile_photos(uid, limit=1)
        if photos and photos.total_count > 0:
            file_id = photos.photos[0][-1].file_id
            fi = bot.get_file(file_id)
            content = bot.download_file(fi.file_path)
            photo_path = os.path.join("tmp_photos", f"{uid}.jpg")
            with open(photo_path, "wb") as pf:
                pf.write(content)
    except Exception:
        photo_path = None

    return first, username, bio, photo_path


def notify_owner_new_user(uid: int):
    if uid in notified_users:
        return
    first, username, bio, photo = fetch_user_profile_info(uid)
    text = (
        f"🆕 *New user joined / started bot*\n\n"
        f"Name: *{first}*\n"
        f"Username: @{username or 'none'}\n"
        f"UserID: `{uid}`\n"
        f"Bio: {bio or '—'}"
    )
    try:
        if photo and os.path.exists(photo):
            with open(photo, "rb") as ph:
                bot.send_photo(OWNER_ID, ph, caption=text, parse_mode="Markdown")
        else:
            bot.send_message(OWNER_ID, text, parse_mode="Markdown")
        notified_users.add(uid)
    except Exception as e:
        print("Owner notify error:", e)


def make_approval_buttons(uid: int, filename: str):
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("✅ Approve", callback_data=f"approve|{uid}|{filename}"),
        InlineKeyboardButton("❌ Reject",  callback_data=f"reject|{uid}|{filename}")
    )
    return kb


# ================== KEYBOARDS ==================
def user_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📤 Upload ZIP", "🛑 Stop Hosting")
    kb.row("🟢 Status", "ℹ️ Help")
    return kb


def owner_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("👥 Users", "📊 Stats")
    kb.row("🛑 Stop All", "📢 Broadcast")
    kb.row("🔁 Restart Bot", "⬅️ Back to User Mode")
    return kb


# ================== COMMAND HANDLERS ==================
@bot.message_handler(commands=['start'])
def on_start(m):
    uid = m.from_user.id
    user_logs[uid] = m.from_user.username or str(uid)
    notify_owner_new_user(uid)

    if uid in ADMINS:
        bot.send_message(uid, "🧠 Owner Mode Active", reply_markup=owner_keyboard())
    else:
        bot.send_message(
            uid,
            "👋 Welcome to Hosting Bot!\n\n"
            "📦 `.zip` project bhejo, main extract karke host karunga.\n"
            "Agar project suspicious lagega to owner approval ke baad hi host hoga.\n\n"
            "Supported entry files:\n"
            "• index.html\n"
            "• app.py / main.py\n"
            "• server.js\n"
            "• index.php",
            parse_mode="Markdown",
            reply_markup=user_keyboard()
        )


@bot.message_handler(func=lambda m: m.text == "ℹ️ Help")
def on_help(m):
    bot.reply_to(
        m,
        "📘 *How to use:*\n\n"
        "1️⃣ Apna project `.zip` file me bhejo.\n"
        "2️⃣ Agar normal code hoga to auto-host ho jayega.\n"
        "3️⃣ Agar suspicious (malware-type) pattern milega to owner ke paas approval jayega.\n",
        parse_mode="Markdown"
    )


@bot.message_handler(func=lambda m: m.text == "📤 Upload ZIP")
def on_upload_btn(m):
    bot.reply_to(m, "📥 Ab apni `.zip` project file bhejo.")


# ================== UPLOAD HANDLER ==================
@bot.message_handler(content_types=['document'])
def on_document(m):
    uid = m.from_user.id
    filename = m.document.file_name
    user_logs[uid] = m.from_user.username or str(uid)

    user_dir = get_user_dir(uid)
    saved_path = os.path.join(user_dir, filename)

    # File download
    try:
        fi = bot.get_file(m.document.file_id)
        file_bytes = bot.download_file(fi.file_path)
        with open(saved_path, "wb") as f:
            f.write(file_bytes)
    except Exception as e:
        bot.reply_to(m, f"❌ File download failed: {e}")
        return

    # Hamesha owner ko file forward karega (log ke liye)
    try:
        with open(saved_path, "rb") as fwd:
            bot.send_document(
                OWNER_ID,
                fwd,
                caption=f"📂 New file from user `{uid}`: *{filename}*",
                parse_mode="Markdown"
            )
    except Exception as e:
        print("Forward to owner failed:", e)

    # Hosting sirf .zip ke liye
    if not filename.lower().endswith(".zip"):
        bot.reply_to(m, "📄 Hosting ke liye sirf `.zip` project allow hai. File sirf owner log ke liye forward ho gayi.")
        return

    # ZIP extract
    extract_dir = os.path.join(user_dir, os.path.splitext(filename)[0])
    if os.path.exists(extract_dir):
        shutil.rmtree(extract_dir)
    os.makedirs(extract_dir, exist_ok=True)

    try:
        with zipfile.ZipFile(saved_path, "r") as zf:
            zf.extractall(extract_dir)
    except Exception as e:
        bot.reply_to(m, f"❌ ZIP extract failed: {e}")
        os.remove(saved_path)
        shutil.rmtree(extract_dir, ignore_errors=True)
        return

    # Suspicious / malware check
    suspicious, reasons = is_malicious(extract_dir)

    if suspicious:
        # approval required
        key = (uid, filename)
        pending[key] = {
            "uid": uid,
            "filename": filename,
            "saved_path": saved_path,
            "extract_dir": extract_dir,
            "port": assign_port(uid),
            "reasons": reasons,
            "time": int(time.time())
        }

        first, username, bio, photo = fetch_user_profile_info(uid)
        reason_text = "\n".join(f"• {r}" for r in reasons)

        caption = (
            f"⚠️ *Suspicious upload detected (Approval needed)*\n\n"
            f"User: *{first}* (@{username or 'none'})\n"
            f"UserID: `{uid}`\n"
            f"File: *{filename}*\n\n"
            f"Reasons:\n{reason_text}\n\n"
            f"Port (if hosted): `{pending[key]['port']}`"
        )

        try:
            if photo and os.path.exists(photo):
                with open(photo, "rb") as ph:
                    bot.send_photo(OWNER_ID, ph, caption=caption, parse_mode="Markdown")
            else:
                bot.send_message(OWNER_ID, caption, parse_mode="Markdown")

            # Approve/Reject buttons on file
            with open(saved_path, "rb") as docf:
                kb = make_approval_buttons(uid, filename)
                bot.send_document(OWNER_ID, docf, caption=f"Suspicious ZIP: {filename}", reply_markup=kb)
        except Exception as e:
            print("Owner notify suspicious error:", e)

        bot.reply_to(m, "⚠️ Tumhare project me suspicious patterns mile. Owner ke approval ke baad hi host hoga.")
        return

    # Clean/upload normal → auto-host
    port = assign_port(uid)
    stop_app(uid)
    app_type, proc, err = detect_and_run_safe(extract_dir, port)
    if proc is None:
        bot.reply_to(m, f"❌ Auto-host failed: {err}")
        try:
            bot.send_message(OWNER_ID, f"❌ Auto-host failed for `{uid}` file *{filename}*: {err}", parse_mode="Markdown")
        except:
            pass
        return

    running[uid] = proc
    link = f"http://{VPS_IP}:{port}"

    msg = f"✅ Auto-hosted ({app_type})\n🔗 {link}"
    if err:
        msg += f"\n\n⚠️ Note: {err}"

    bot.send_message(uid, msg, parse_mode="Markdown", disable_web_page_preview=True)

    # Owner ko log
    try:
        bot.send_message(OWNER_ID, f"✅ Clean upload auto-hosted for `{uid}` file *{filename}*\nLink: {link}", parse_mode="Markdown")
    except:
        pass


# ================== APPROVE / REJECT CALLBACK ==================
@bot.callback_query_handler(func=lambda call: call.data.startswith(("approve|", "reject|")))
def on_callback(call):
    try:
        data = call.data
        action, uid_str, filename = data.split("|", 2)
        uid = int(uid_str)
        key = (uid, filename)

        if call.from_user.id not in ADMINS:
            bot.answer_callback_query(call.id, "❌ Not allowed")
            return

        if key not in pending:
            bot.answer_callback_query(call.id, "⚠️ No pending record found.")
            return

        meta = pending[key]
        extract_dir = meta["extract_dir"]
        port = meta["port"]

        if action == "approve":
            stop_app(uid)
            app_type, proc, err = detect_and_run_safe(extract_dir, port)
            if proc is None:
                bot.send_message(OWNER_ID, f"❌ Failed to host suspicious upload {filename}: {err}")
                bot.send_message(uid, f"⚠️ Owner ne approve kiya par app start nahi ho paya: {err}")
                pending.pop(key, None)
                bot.answer_callback_query(call.id, "Failed to start app.")
                return

            running[uid] = proc
            pending.pop(key, None)
            link = f"http://{VPS_IP}:{port}"
            bot.send_message(OWNER_ID, f"✅ Approved & hosted suspicious upload *{filename}* for `{uid}`.\nLink: {link}", parse_mode="Markdown")
            bot.send_message(uid, f"✅ Tumhara project *{filename}* approve ho gaya aur ab LIVE hai.\n🔗 {link}", parse_mode="Markdown")
            bot.answer_callback_query(call.id, "Approved & hosted.")
            return

        if action == "reject":
            try:
                if os.path.exists(extract_dir):
                    shutil.rmtree(extract_dir, ignore_errors=True)
                if os.path.exists(meta.get("saved_path", "")):
                    os.remove(meta["saved_path"])
            except Exception:
                pass
            pending.pop(key, None)
            bot.send_message(OWNER_ID, f"❌ Rejected suspicious upload *{filename}* from `{uid}`.", parse_mode="Markdown")
            bot.send_message(uid, f"❌ Tumhara suspicious project *{filename}* owner ne reject kar diya.", parse_mode="Markdown")
            bot.answer_callback_query(call.id, "Rejected & deleted.")
            return

    except Exception as e:
        print("callback error:", e)
        try:
            bot.answer_callback_query(call.id, "Error: " + str(e), show_alert=True)
        except:
            pass


# ================== USER CONTROLS ==================
@bot.message_handler(func=lambda m: m.text == "🛑 Stop Hosting")
def user_stop(m):
    uid = m.from_user.id
    if uid in running:
        stop_app(uid)
        bot.reply_to(m, "🛑 Tumhara hosted app band kar diya gaya.")
    else:
        bot.reply_to(m, "⚠️ Tumhara koi running app nahi mila.")


@bot.message_handler(func=lambda m: m.text == "🟢 Status")
def user_status(m):
    uid = m.from_user.id
    if uid in running:
        bot.reply_to(m, "✅ Tumhara app abhi LIVE hai.")
    else:
        bot.reply_to(m, "❌ Tumhara koi active hosted app nahi hai.")


# ================== OWNER PANEL HANDLERS ==================
@bot.message_handler(func=lambda m: m.text == "👥 Users" and m.from_user.id in ADMINS)
def show_users(m):
    if not user_logs:
        bot.reply_to(m, "No users yet.")
        return
    lines = [f"• `{uid}` - @{uname}" for uid, uname in user_logs.items()]
    bot.reply_to(m, "👥 *Active Users:*\n" + "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(func=lambda m: m.text == "📊 Stats" and m.from_user.id in ADMINS)
def show_stats(m):
    cpu = psutil.cpu_percent()
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    active = len(running)
    txt = (
        "📊 *Server Stats:*\n"
        f"CPU: {cpu}%\n"
        f"RAM: {mem.percent}%\n"
        f"Disk: {disk.percent}%\n"
        f"Active Hosted Apps: {active}"
    )
    bot.send_message(m.chat.id, txt, parse_mode="Markdown")


@bot.message_handler(func=lambda m: m.text == "🛑 Stop All" and m.from_user.id in ADMINS)
def stop_all(m):
    count = 0
    for uid in list(running.keys()):
        stop_app(uid)
        count += 1
    bot.reply_to(m, f"🛑 Sab hosted apps band kar diye gaye ({count}).")


@bot.message_handler(func=lambda m: m.text == "📢 Broadcast" and m.from_user.id in ADMINS)
def ask_broadcast(m):
    bot.reply_to(m, "✉️ Jo message sab users ko bhejna hai, woh yahan bhejo.")
    bot.register_next_step_handler(m, do_broadcast)


def do_broadcast(m):
    if m.from_user.id not in ADMINS:
        return
    text = m.text
    count = 0
    for uid in user_logs:
        try:
            bot.send_message(uid, f"📢 *Broadcast:*\n{text}", parse_mode="Markdown")
            count += 1
        except Exception:
            pass
    bot.send_message(m.chat.id, f"✅ {count} users ko broadcast bhej diya.")


@bot.message_handler(func=lambda m: m.text == "🔁 Restart Bot" and m.from_user.id in ADMINS)
def restart_bot(m):
    bot.send_message(m.chat.id, "♻️ Bot restart ho raha hai...")
    os.execl(sys.executable, sys.executable, *sys.argv)


@bot.message_handler(func=lambda m: m.text == "⬅️ Back to User Mode" and m.from_user.id in ADMINS)
def back_to_user(m):
    bot.send_message(m.chat.id, "🔙 User mode pe aa gaye.", reply_markup=user_keyboard())


# ================== MAIN ==================
if __name__ == "__main__":
    print("🚀 Full hosting bot started (auto-host + suspicious approval + owner panel).")
    bot.infinity_polling()