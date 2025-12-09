# -*- coding: utf-8 -*-
# Final version (token removed) — includes malware approval system + owner-only "All User Files" button
# Replace placeholders before running.

import telebot
import subprocess
import os
import zipfile
import tempfile
import shutil
from telebot import types
import time
from datetime import datetime
import psutil
import sqlite3
import logging
import threading
import re
import sys
import requests
from flask import Flask
from threading import Thread

# ----------------- Flask Keep Alive -----------------
app = Flask('')

@app.route('/')
def home():
    return "I'AM OGGY BHAI FILE HOST"

def run_flask():
    port = int(os.environ.get("PORT", 8178))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

# ----------------- Configuration (PLACEHOLDERS) -----------------
TOKEN = 'YOUR_TELEGRAM_BOT_TOKEN_HERE'      # <-- replace with your bot token
OWNER_ID = 123456789                        # <-- replace with owner's Telegram ID (int)
ADMIN_ID = 123456789                        # <-- replace with admin's Telegram ID (int)
YOUR_USERNAME = 'your_username_here'        # <-- replace without @
UPDATE_CHANNEL = 'https://t.me/yourchannel' # <-- replace with your updates channel URL

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_BOTS_DIR = os.path.join(BASE_DIR, 'upload_bots')
IROTECH_DIR = os.path.join(BASE_DIR, 'inf')
DATABASE_PATH = os.path.join(IROTECH_DIR, 'bot_data.db')

FREE_USER_LIMIT = 10
SUBSCRIBED_USER_LIMIT = 50
ADMIN_LIMIT = 999
OWNER_LIMIT = float('inf')

os.makedirs(UPLOAD_BOTS_DIR, exist_ok=True)
os.makedirs(IROTECH_DIR, exist_ok=True)

bot = telebot.TeleBot(TOKEN)
bot_scripts = {}
user_subscriptions = {}
user_files = {}
active_users = set()
admin_ids = {ADMIN_ID, OWNER_ID}
bot_locked = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

DB_LOCK = threading.Lock()

# ----------------- Database -----------------
def init_db():
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('CREATE TABLE IF NOT EXISTS user_files (user_id INTEGER, file_name TEXT, file_type TEXT)')
        conn.commit()
        conn.close()

def load_data():
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('SELECT user_id, file_name, file_type FROM user_files')
        for uid, fname, ftype in c.fetchall():
            if uid not in user_files:
                user_files[uid] = []
            user_files[uid].append((fname, ftype))
        conn.close()

init_db()
load_data()

# ----------------- Helpers -----------------
def get_user_folder(uid):
    folder = os.path.join(UPLOAD_BOTS_DIR, str(uid))
    os.makedirs(folder, exist_ok=True)
    return folder

def save_user_file(uid, fname, ftype):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('INSERT INTO user_files (user_id, file_name, file_type) VALUES (?, ?, ?)', (uid, fname, ftype))
        conn.commit()
        conn.close()
    if uid not in user_files:
        user_files[uid] = []
    user_files[uid].append((fname, ftype))

# ----------------- Malware Detection -----------------
SUSPICIOUS_REGEXES = [
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\bos\.remove",
    r"\bsubprocess\.Popen",
    r"\bshutil\.rmtree",
    r"import\s+ctypes",
]

def is_suspicious_code_text(txt):
    for pat in SUSPICIOUS_REGEXES:
        try:
            if re.search(pat, txt):
                return True, pat
        except re.error:
            continue
    return False, None

def send_owner_alert_simple(owner_id, file_name, user_id, folder, path, reason, message):
    text = (f"⚠️ *Malware Alert*\nUser: `{user_id}`\nFile: `{file_name}`\nReason: {reason}\n\n"
            "File execution blocked. Owner approval required.")
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Approve & Run", callback_data=f"override_{user_id}_{file_name}"))
    markup.add(types.InlineKeyboardButton("❌ Reject & Quarantine", callback_data=f"quarantine_{user_id}_{file_name}"))
    try:
        bot.send_message(owner_id, text, parse_mode='Markdown', reply_markup=markup)
    except Exception as e:
        logger.exception("Failed sending owner alert: %s", e)
    # also notify other admins quietly (non-blocking)
    try:
        for aid in admin_ids:
            if aid != owner_id:
                try:
                    bot.send_message(aid, text, parse_mode='Markdown', reply_markup=markup)
                except:
                    pass
    except:
        pass

# ----------------- Owner Approval System -----------------
@bot.callback_query_handler(func=lambda c: c.data and (c.data.startswith("quarantine_") or c.data.startswith("override_")))
def owner_approval_cb(call):
    data = call.data
    try:
        bot.answer_callback_query(call.id)
        if data.startswith("quarantine_"):
            _, uid, fname = data.split("_", 2)
            ufolder = get_user_folder(int(uid))
            fpath = os.path.join(ufolder, fname)
            qdir = os.path.join(BASE_DIR, "quarantine")
            os.makedirs(qdir, exist_ok=True)
            if os.path.exists(fpath):
                try:
                    shutil.move(fpath, os.path.join(qdir, f"{uid}_{fname}_{int(time.time())}"))
                except Exception:
                    shutil.copy2(fpath, os.path.join(qdir, f"{uid}_{fname}_{int(time.time())}"))
                    try: os.remove(fpath)
                    except: pass
                bot.send_message(call.message.chat.id, f"🗄️ `{fname}` moved to quarantine.", parse_mode="Markdown")
                try: bot.send_message(int(uid), f"⚠️ Your file `{fname}` was rejected by owner.", parse_mode="Markdown")
                except: pass
            else:
                bot.send_message(call.message.chat.id, "File not found.")
        elif data.startswith("override_"):
            _, uid, fname = data.split("_", 2)
            ufolder = get_user_folder(int(uid))
            fpath = os.path.join(ufolder, fname)
            if not os.path.exists(fpath):
                bot.send_message(call.message.chat.id, "File not found.")
                return
            if fname.lower().endswith(".py"):
                subprocess.Popen([sys.executable, fpath])
            elif fname.lower().endswith(".js"):
                subprocess.Popen(["node", fpath])
            bot.send_message(call.message.chat.id, f"✅ `{fname}` approved & started.", parse_mode="Markdown")
            try: bot.send_message(int(uid), f"✅ Your file `{fname}` approved by owner & started.", parse_mode="Markdown")
            except: pass
    except Exception as e:
        logger.exception("Error in owner_approval_cb: %s", e)
        try: bot.answer_callback_query(call.id, "Error processing action.")
        except: pass

# ----------------- Owner Command: All User Files -----------------
@bot.message_handler(commands=['allfiles'])
def all_files(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⛔ You are not authorized.")
        return
    if not user_files:
        bot.reply_to(message, "No files found.")
        return
    text_lines = []
    for uid, flist in user_files.items():
        text_lines.append(f"👤 User: `{uid}`")
        for fname, ftype in flist:
            text_lines.append(f" └─ {fname} ({ftype})")
        text_lines.append("")  # spacer
    full_text = "\n".join(text_lines)
    for i in range(0, len(full_text), 3500):
        bot.send_message(message.chat.id, full_text[i:i+3500], parse_mode="Markdown")

# ----------------- Menu -----------------
def create_main_menu_inline(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton('📢 Updates Channel', url=UPDATE_CHANNEL))
    markup.add(types.InlineKeyboardButton('📤 Upload File', callback_data='upload'))
    markup.add(types.InlineKeyboardButton('📂 Check Files', callback_data='check_files'))
    markup.add(types.InlineKeyboardButton('⚡ Bot Speed', callback_data='speed'))
    markup.add(types.InlineKeyboardButton('📞 Contact Owner', url=f'https://t.me/{YOUR_USERNAME.replace("@","")}'))
    if user_id in admin_ids:
        markup.add(types.InlineKeyboardButton('📁 All User Files', callback_data='all_user_files'))
    return markup

@bot.callback_query_handler(func=lambda call: call.data == "all_user_files")
def all_user_files_button(call):
    try:
        bot.answer_callback_query(call.id)
    except:
        pass
    fake_msg = call.message
    fake_msg.from_user = call.from_user
    all_files(fake_msg)

# ----------------- Upload & ZIP handling -----------------
def run_script(path, owner_id=None, user_folder=None, file_name=None):
    try:
        proc = subprocess.Popen([sys.executable, path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        key = f"{owner_id}_{file_name}" if owner_id and file_name else path
        bot_scripts[key] = {'process': proc, 'started_at': time.time()}
        def watcher():
            try:
                out, err = proc.communicate()
                logger.info(f"Script {path} finished. out_len={len(out) if out else 0}, err_len={len(err) if err else 0}")
            except Exception as e:
                logger.exception("Watcher error: %s", e)
            finally:
                if key in bot_scripts:
                    del bot_scripts[key]
        threading.Thread(target=watcher, daemon=True).start()
    except Exception as e:
        logger.exception("Failed to start script: %s", e)

def run_js_script(path, owner_id=None, user_folder=None, file_name=None):
    try:
        proc = subprocess.Popen(['node', path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        key = f"{owner_id}_{file_name}" if owner_id and file_name else path
        bot_scripts[key] = {'process': proc, 'started_at': time.time()}
        def watcher():
            try:
                out, err = proc.communicate()
                logger.info(f"JS Script {path} finished.")
            except Exception as e:
                logger.exception("Watcher error js: %s", e)
            finally:
                if key in bot_scripts:
                    del bot_scripts[key]
        threading.Thread(target=watcher, daemon=True).start()
    except Exception as e:
        logger.exception("Failed to start js script: %s", e)

def handle_py_file(file_path, script_owner_id, user_folder, file_name, message):
    try:
        suspicious, matched = False, None
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as rf:
                sample = rf.read(30000)
            suspicious, matched = is_suspicious_code_text(sample)
        except Exception as e:
            logger.warning(f"Could not read Python file for scan: {e}")
            suspicious, matched = True, "unreadable"
        save_user_file(script_owner_id, file_name, 'py')
        if suspicious:
            reason = f"Pattern: {matched}" if matched else "Flagged by heuristic"
            send_owner_alert_simple(OWNER_ID, file_name, script_owner_id, user_folder, file_path, reason, message)
            bot.reply_to(message, f"⚠️ `{file_name}` appears suspicious and was blocked. Owner notified for approval.", parse_mode='Markdown')
            return
        threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name)).start()
        bot.reply_to(message, f"✅ `{file_name}` started.", parse_mode='Markdown')
    except Exception as e:
        logger.exception("Error processing python file: %s", e)
        try: bot.reply_to(message, f"❌ Error processing Python file: {e}")
        except: pass

def handle_js_file(file_path, script_owner_id, user_folder, file_name, message):
    try:
        suspicious, matched = False, None
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as rf:
                sample = rf.read(30000)
            suspicious, matched = is_suspicious_code_text(sample)
        except Exception as e:
            logger.warning(f"Could not read JS file for scan: {e}")
            suspicious, matched = True, "unreadable"
        save_user_file(script_owner_id, file_name, 'js')
        if suspicious:
            reason = f"Pattern: {matched}" if matched else "Flagged by heuristic"
            send_owner_alert_simple(OWNER_ID, file_name, script_owner_id, user_folder, file_path, reason, message)
            bot.reply_to(message, f"⚠️ `{file_name}` appears suspicious and was blocked. Owner notified for approval.", parse_mode='Markdown')
            return
        threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name)).start()
        bot.reply_to(message, f"✅ `{file_name}` started.", parse_mode='Markdown')
    except Exception as e:
        logger.exception("Error processing js file: %s", e)
        try: bot.reply_to(message, f"❌ Error processing JS file: {e}")
        except: pass

def handle_zip_file(zip_bytes, archive_name, message):
    user_id = message.from_user.id
    user_folder = get_user_folder(user_id)
    temp_dir = None
    tmpf = None
    try:
        temp_dir = tempfile.mkdtemp(prefix='zipextract_')
        tmpf = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
        tmpf.write(zip_bytes)
        tmpf.close()
        zfile = zipfile.ZipFile(tmpf.name, 'r')
    except Exception as e:
        logger.exception("Bad zip handling: %s", e)
        bot.reply_to(message, f"❌ Error: Invalid/corrupted ZIP. {e}")
        if tmpf and os.path.exists(tmpf.name):
            try: os.remove(tmpf.name)
            except: pass
        return

    try:
        zfile.extractall(temp_dir)
        py_files = []
        js_files = []
        for root, dirs, files in os.walk(temp_dir):
            for fn in files:
                if fn.lower().endswith('.py'):
                    rel = os.path.relpath(os.path.join(root, fn), start=temp_dir)
                    py_files.append(rel)
                elif fn.lower().endswith('.js'):
                    rel = os.path.relpath(os.path.join(root, fn), start=temp_dir)
                    js_files.append(rel)

        main_script_name = None; file_type = None
        preferred_py = ['main.py', 'bot.py', 'app.py']; preferred_js = ['index.js', 'main.js', 'bot.js', 'app.js']
        for p in preferred_py:
            if p in py_files:
                main_script_name = p; file_type = 'py'; break
        if not main_script_name:
            for p in preferred_js:
                if p in js_files:
                    main_script_name = p; file_type = 'js'; break
        if not main_script_name:
            if py_files:
                main_script_name = py_files[0]; file_type = 'py'
            elif js_files:
                main_script_name = js_files[0]; file_type = 'js'

        if not main_script_name:
            bot.reply_to(message, "❌ No `.py` or `.js` script found in archive!")
            return

        moved_count = 0
        for root, dirs, files in os.walk(temp_dir):
            for item in files:
                src_path = os.path.join(root, item)
                rel_path = os.path.relpath(src_path, temp_dir)
                dest_path = os.path.join(user_folder, rel_path)
                dest_dir = os.path.dirname(dest_path)
                os.makedirs(dest_dir, exist_ok=True)
                if os.path.exists(dest_path):
                    try:
                        if os.path.isdir(dest_path):
                            shutil.rmtree(dest_path)
                        else:
                            os.remove(dest_path)
                    except:
                        pass
                shutil.move(src_path, dest_path)
                moved_count += 1
        logger.info(f"Moved {moved_count} items to {user_folder}")

        save_user_file(user_id, main_script_name, file_type)
        main_script_path = os.path.join(user_folder, main_script_name)

        suspect_found = False
        suspect_reasons = []
        scan_targets = []
        for root, dirs, files in os.walk(user_folder):
            for fn in files:
                if fn.lower().endswith(('.py', '.js')):
                    abs_path = os.path.join(root, fn)
                    scan_targets.append(abs_path)
        for path in scan_targets:
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as rf:
                    txt = rf.read(30000)
                sus, matched = is_suspicious_code_text(txt)
                if sus:
                    suspect_found = True
                    suspect_reasons.append(f"{os.path.relpath(path, user_folder)}: {matched}")
            except Exception as e:
                suspect_found = True
                suspect_reasons.append(f"{os.path.relpath(path, user_folder)}: unreadable")

        reason_summary = ", ".join(suspect_reasons[:6]) if suspect_reasons else "No obvious suspicious patterns; owner review required."

        if suspect_found:
            send_owner_alert_simple(OWNER_ID, main_script_name, user_id, user_folder, main_script_path, reason_summary, message)
            bot.reply_to(message, f"⚠️ Suspicious content found in archive. Execution blocked. Owner notified for approval.\nReason: {reason_summary}", parse_mode='Markdown')
            return

        bot.reply_to(message, f"✅ Files extracted. Starting main script: `{main_script_name}`...", parse_mode='Markdown')
        if file_type == 'py':
            threading.Thread(target=run_script, args=(main_script_path, user_id, user_folder, main_script_name)).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(main_script_path, user_id, user_folder, main_script_name)).start()

    except zipfile.BadZipFile as e:
        logger.exception("Bad zip file: %s", e)
        bot.reply_to(message, f"❌ Error: Invalid/corrupted ZIP. {e}")
    except Exception as e:
        logger.exception("Error processing zip: %s", e)
        bot.reply_to(message, f"❌ Error processing zip: {e}")
    finally:
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass
        if tmpf and os.path.exists(tmpf.name):
            try: os.remove(tmpf.name)
            except: pass

# ----------------- Document handler -----------------
@bot.message_handler(content_types=['document'])
def handle_file_upload_doc(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    doc = message.document
    logger.info(f"Doc from {user_id}: {doc.file_name} ({doc.mime_type}), Size: {doc.file_size}")

    if bot_locked and user_id not in admin_ids:
        bot.reply_to(message, "⚠️ Bot locked, cannot accept files.")
        return

    file_limit = FREE_USER_LIMIT
    current_files = len(user_files.get(user_id, []))
    if current_files >= file_limit:
        bot.reply_to(message, f"⚠️ File limit reached ({current_files}/{file_limit}). Delete files first.")
        return

    file_name = doc.file_name
    if not file_name:
        bot.reply_to(message, "⚠️ No file name. Ensure file has a name.")
        return
    file_ext = os.path.splitext(file_name)[1].lower()
    if file_ext not in ['.py', '.js', '.zip']:
        bot.reply_to(message, "⚠️ Unsupported type! Only `.py`, `.js`, `.zip` allowed.")
        return
    max_file_size = 20 * 1024 * 1024
    if doc.file_size > max_file_size:
        bot.reply_to(message, f"⚠️ File too large (Max: {max_file_size // 1024 // 1024} MB).")
        return

    try:
        # forward to owner for visibility
        try:
            bot.forward_message(OWNER_ID, chat_id, message.message_id)
            bot.send_message(OWNER_ID, f"⬆️ File '{file_name}' from {message.from_user.first_name} (`{user_id}`)", parse_mode='Markdown')
        except Exception:
            pass

        download_wait_msg = bot.reply_to(message, f"⏳ Downloading `{file_name}`...")
        file_info_tg_doc = bot.get_file(doc.file_id)
        downloaded_file_content = bot.download_file(file_info_tg_doc.file_path)
        bot.edit_message_text(f"✅ Downloaded `{file_name}`. Processing...", chat_id, download_wait_msg.message_id)
        user_folder = get_user_folder(user_id)

        if file_ext == '.zip':
            handle_zip_file(downloaded_file_content, file_name, message)
        else:
            file_path = os.path.join(user_folder, file_name)
            with open(file_path, 'wb') as f:
                f.write(downloaded_file_content)
            logger.info(f"Saved single file to {file_path}")
            if file_ext == '.js':
                handle_js_file(file_path, user_id, user_folder, file_name, message)
            elif file_ext == '.py':
                handle_py_file(file_path, user_id, user_folder, file_name, message)
            else:
                bot.reply_to(message, "File uploaded.")
    except telebot.apihelper.ApiTelegramException as e:
        logger.exception("Telegram API Error handling file: %s", e)
        if "file is too big" in str(e).lower():
            bot.reply_to(message, f"❌ Telegram API Error: File too large to download (~20MB limit).")
        else:
            bot.reply_to(message, f"❌ Telegram API Error: {str(e)}. Try later.")
    except Exception as e:
        logger.exception("Unexpected error handling file: %s", e)
        bot.reply_to(message, f"❌ Unexpected error: {str(e)}")

# ----------------- Other callbacks / command examples -----------------
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = call.from_user.id
    data = call.data
    logger.info(f"Callback: User={user_id}, Data='{data}'")
    if bot_locked and user_id not in admin_ids and data not in ['back_to_main', 'speed', 'stats']:
        try: bot.answer_callback_query(call.id, "⚠️ Bot locked by admin.", show_alert=True)
        except: pass
        return
    try:
        if data == 'upload':
            bot.send_message(user_id, "📤 Send your Python (`.py`), JS (`.js`) or ZIP (`.zip`) file.")
        elif data == 'check_files':
            # reuse existing handler
            command_check_files = None
            try:
                # attempt to call /checkfiles handler logic if present
                bot.send_message(user_id, "Use /checkfiles command.")
            except:
                pass
        else:
            pass
    except Exception:
        pass

# ----------------- Ping -----------------
@bot.message_handler(commands=['ping'])
def ping(message):
    start = time.time()
    m = bot.reply_to(message, "Pong...")
    delay = round((time.time() - start) * 1000, 2)
    try:
        bot.edit_message_text(f"Pong! `{delay}ms`", message.chat.id, m.message_id, parse_mode="Markdown")
    except:
        pass

# ----------------- Start -----------------
if __name__ == '__main__':
    keep_alive()
    logger.info("Bot polling started...")
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
    except KeyboardInterrupt:
        logger.info("Stopped by keyboard interrupt.")
    except Exception as e:
        logger.exception("Bot crashed: %s", e)
