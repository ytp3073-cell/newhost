# -*- coding: utf-8 -*-
# bot.py — Owner-exclusive runner with malware blocking + approval flow
# Merged full file (Parts 1-4)

import os
import sys
import re
import json
import time
import shutil
import sqlite3
import logging
import zipfile
import tempfile
import threading
import subprocess
from datetime import datetime, timedelta

# external libs
try:
    import telebot
    from telebot import types
except Exception as e:
    print("Missing telebot library. Install with: pip install pyTelegramBotAPI")
    raise

try:
    import psutil
except Exception:
    print("Missing psutil. Install with: pip install psutil")
    raise

# Flask for keepalive
try:
    from flask import Flask
    from threading import Thread
except Exception:
    Flask = None

# --- Flask Keep Alive (optional) ---
if Flask:
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
        print("Flask keep-alive started.")
else:
    def keep_alive():
        print("Flask not available; skipping keep-alive.")

# --- Configuration ---
TOKEN = os.environ.get('BOT_TOKEN') or '8341821928:AAEWHkJjKY_5r7Qkb3wp14-HEGDbYcGvtZw'
OWNER_ID = int(os.environ.get('OWNER_ID') or 7652176329)
ADMIN_ID = int(os.environ.get('ADMIN_ID') or 7652176329)
YOUR_USERNAME = os.environ.get('YOUR_USERNAME') or 'BAN8T'
UPDATE_CHANNEL = os.environ.get('UPDATE_CHANNEL') or 'https://t.me/BAN8T'

# Folders & DB
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_BOTS_DIR = os.path.join(BASE_DIR, 'upload_bots')
IROTECH_DIR = os.path.join(BASE_DIR, 'inf')
DATABASE_PATH = os.path.join(IROTECH_DIR, 'bot_data.db')
BLOCKED_FILES_PATH = os.path.join(IROTECH_DIR, 'blocked_files.json')
QUARANTINE_DIR = os.path.join(BASE_DIR, 'quarantine')

FREE_USER_LIMIT = 10
SUBSCRIBED_USER_LIMIT = 50
ADMIN_LIMIT = 999
OWNER_LIMIT = float('inf')

os.makedirs(UPLOAD_BOTS_DIR, exist_ok=True)
os.makedirs(IROTECH_DIR, exist_ok=True)
os.makedirs(QUARANTINE_DIR, exist_ok=True)

# Init bot
bot = telebot.TeleBot(TOKEN)

# Data structures
bot_scripts = {}          # map key -> process info
user_subscriptions = {}   # user_id -> {'expiry': datetime}
user_files = {}           # user_id -> [(file_name, file_type)]
active_users = set()
admin_ids = {ADMIN_ID, OWNER_ID}
bot_locked = False

# Logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB_LOCK = threading.Lock()

# --- DB init and load functions ---
def init_db():
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        try:
            c = conn.cursor()
            c.execute('CREATE TABLE IF NOT EXISTS user_files (user_id INTEGER, file_name TEXT, file_type TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS active_users (user_id INTEGER)')
            c.execute('CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)')
            c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (OWNER_ID,))
            if ADMIN_ID != OWNER_ID:
                c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (ADMIN_ID,))
            conn.commit()
        finally:
            conn.close()

def load_data():
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        try:
            c = conn.cursor()
            c.execute('SELECT user_id, file_name, file_type FROM user_files')
            for uid, fname, ftype in c.fetchall():
                if uid not in user_files:
                    user_files[uid] = []
                user_files[uid].append((fname, ftype))
            c.execute('SELECT user_id FROM active_users')
            for (uid,) in c.fetchall():
                active_users.add(uid)
            c.execute('SELECT user_id FROM admins')
            for (aid,) in c.fetchall():
                admin_ids.add(aid)
        finally:
            conn.close()

init_db()
load_data()

# blocked files persistence
def load_blocked_files():
    if os.path.exists(BLOCKED_FILES_PATH):
        try:
            with open(BLOCKED_FILES_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_blocked_files(data):
    try:
        with open(BLOCKED_FILES_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error("Failed to save blocked files: %s", e)

blocked_files = load_blocked_files()

# --- Helpers ---
def get_user_folder(user_id):
    path = os.path.join(UPLOAD_BOTS_DIR, str(user_id))
    os.makedirs(path, exist_ok=True)
    return path

def get_user_file_limit(user_id):
    if user_id == OWNER_ID:
        return OWNER_LIMIT
    if user_id in admin_ids:
        return ADMIN_LIMIT
    if user_id in user_subscriptions and user_subscriptions[user_id]['expiry'] > datetime.now():
        return SUBSCRIBED_USER_LIMIT
    return FREE_USER_LIMIT

def get_user_file_count(user_id):
    return len(user_files.get(user_id, []))

def save_user_file(user_id, file_name, file_type):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        try:
            c = conn.cursor()
            c.execute('INSERT INTO user_files (user_id, file_name, file_type) VALUES (?, ?, ?)', (user_id, file_name, file_type))
            conn.commit()
            user_files.setdefault(user_id, []).append((file_name, file_type))
        finally:
            conn.close()

def remove_user_file_db(user_id, file_name):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        try:
            c = conn.cursor()
            c.execute('DELETE FROM user_files WHERE user_id = ? AND file_name = ?', (user_id, file_name))
            conn.commit()
            if user_id in user_files:
                user_files[user_id] = [f for f in user_files[user_id] if f[0] != file_name]
                if not user_files[user_id]:
                    del user_files[user_id]
        finally:
            conn.close()

def add_active_user(user_id):
    active_users.add(user_id)
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        try:
            c = conn.cursor()
            c.execute('INSERT OR IGNORE INTO active_users (user_id) VALUES (?)', (user_id,))
            conn.commit()
        finally:
            conn.close()

# --- Malware heuristic scanner ---
SUSPICIOUS_REGEXES = [
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\bos\.remove\s*\(",
    r"\bshutil\.rmtree\s*\(",
    r"\bsubprocess\.Popen\s*\(",
    r"\bsocket\.",
    r"\brequests\.",
    r"\bftplib\.",
    r"open\s*\(.*['\"]/etc",
    r"import\s+ctypes",
    r"from\s+ctypes",
    r"import\s+cryptography",
]

def is_suspicious_code_text(text):
    for pat in SUSPICIOUS_REGEXES:
        try:
            if re.search(pat, text):
                return True, pat
        except re.error:
            continue
    return False, None

# --- Owner alert for suspicious files (approval buttons) ---
def send_owner_alert_simple(owner_id, file_name, user_id, user_folder, file_path, reason_summary, message_obj):
    text = (
        f"⚠️ *Malware Alert*\n\n"
        f"👤 User: `{user_id}`\n"
        f"📄 File: `{file_name}`\n"
        f"❗ Reason: {reason_summary}\n\n"
        "Execution blocked. Approve to run or quarantine."
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Approve & Run", callback_data=f"approve_run_{user_id}_{file_name}"))
    markup.add(types.InlineKeyboardButton("🚫 Reject (Quarantine)", callback_data=f"reject_quarantine_{user_id}_{file_name}"))
    try:
        bot.send_message(owner_id, text, parse_mode='Markdown', reply_markup=markup)
    except Exception as e:
        logger.exception("Failed sending owner alert: %s", e)


# --- Approval callback handler ---
@bot.callback_query_handler(func=lambda c: c.data and (c.data.startswith("approve_run_") or c.data.startswith("reject_quarantine_")))
def owner_approval_callback(call):
    try:
        bot.answer_callback_query(call.id)
        data = call.data
        if data.startswith("approve_run_"):
            parts = data.split('_', 3)
            if len(parts) < 4:
                bot.send_message(call.message.chat.id, "Invalid approval data.")
                return
            _, _, uid_s, fname = parts
            uid = int(uid_s)
            user_folder = get_user_folder(uid)
            path = os.path.join(user_folder, fname)
            if not os.path.exists(path):
                bot.send_message(call.message.chat.id, "File not found.")
                return
            bot.send_message(call.message.chat.id, f"✅ Approved. Starting `{fname}` for `{uid}`.")
            if fname.lower().endswith('.py'):
                threading.Thread(target=run_script, args=(path, uid, user_folder, fname, call.message)).start()
            elif fname.lower().endswith('.js'):
                threading.Thread(target=run_js_script, args=(path, uid, user_folder, fname, call.message)).start()
            try:
                bot.send_message(uid, f"✅ Your file `{fname}` was approved and started by owner.")
            except:
                pass
            return
        if data.startswith("reject_quarantine_"):
            parts = data.split('_', 3)
            if len(parts) < 4:
                bot.send_message(call.message.chat.id, "Invalid quarantine data.")
                return
            _, _, uid_s, fname = parts
            uid = int(uid_s)
            user_folder = get_user_folder(uid)
            path = os.path.join(user_folder, fname)
            if os.path.exists(path):
                dest = os.path.join(QUARANTINE_DIR, f"{uid}_{fname}_{int(time.time())}")
                try:
                    shutil.move(path, dest)
                except Exception as e:
                    bot.send_message(call.message.chat.id, f"Failed to move to quarantine: {e}")
                    return
                blocked_files[fname] = {"user_id": uid, "time": str(datetime.now()), "reason": "Rejected by owner"}
                save_blocked_files(blocked_files)
                bot.send_message(call.message.chat.id, f"🚫 `{fname}` quarantined.")
                try:
                    bot.send_message(uid, f"⚠️ Your file `{fname}` was rejected and quarantined by owner.")
                except:
                    pass
            else:
                bot.send_message(call.message.chat.id, "File not found.")
            return
    except Exception as e:
        logger.exception("Error in owner approval callback: %s", e)
        try:
            bot.answer_callback_query(call.id, "Error processing approval.")
        except:
            pass

# --- Runner utilities ---
def kill_process_tree(process_info):
    try:
        process = process_info.get('process')
        if not process or not hasattr(process, 'pid'):
            return
        pid = process.pid
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except:
                pass
        psutil.wait_procs(children, timeout=1)
        try:
            parent.terminate()
            parent.wait(timeout=1)
        except psutil.TimeoutExpired:
            try:
                parent.kill()
            except:
                pass
    except Exception as e:
        logger.exception("Error killing process tree: %s", e)

def attempt_install_pip(module_name, message):
    try:
        bot.reply_to(message, f"🐍 Installing missing module `{module_name}`...")
        cmd = [sys.executable, "-m", "pip", "install", module_name]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            bot.reply_to(message, f"✅ `{module_name}` installed.")
            return True
        else:
            bot.reply_to(message, f"❌ Pip install failed:\n{res.stderr or res.stdout}")
            return False
    except Exception as e:
        bot.reply_to(message, f"❌ Error installing `{module_name}`: {e}")
        return False

def attempt_install_npm(module_name, user_folder, message):
    try:
        bot.reply_to(message, f"🟠 Installing node package `{module_name}`...")
        cmd = ["npm", "install", module_name]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=user_folder)
        if res.returncode == 0:
            bot.reply_to(message, f"✅ `{module_name}` installed (npm).")
            return True
        else:
            bot.reply_to(message, f"❌ npm install failed:\n{res.stderr or res.stdout}")
            return False
    except FileNotFoundError:
        bot.reply_to(message, "❌ `npm` not found on server.")
        return False
    except Exception as e:
        bot.reply_to(message, f"❌ Error installing npm package: {e}")
        return False

# run python script
def run_script(path, owner_id, user_folder, file_name, message_or_context, attempt=1):
    max_attempts = 2
    if attempt > max_attempts:
        try:
            bot.reply_to(message_or_context, f"❌ Failed to start {file_name} after {max_attempts} attempts.")
        except:
            pass
        return
    script_key = f"{owner_id}_{file_name}"
    if not os.path.exists(path):
        try:
            bot.reply_to(message_or_context, f"❌ File not found: {path}")
        except:
            pass
        remove_user_file_db(owner_id, file_name)
        return
    # pre-check quick run to detect missing modules
    if attempt == 1:
        try:
            proc = subprocess.Popen([sys.executable, path], cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            _, stderr = proc.communicate(timeout=5)
            if proc.returncode != 0 and stderr:
                m = re.search(r"ModuleNotFoundError: No module named '(.+?)'", stderr)
                if m:
                    mod = m.group(1)
                    if attempt_install_pip(mod, message_or_context):
                        threading.Thread(target=run_script, args=(path, owner_id, user_folder, file_name, message_or_context, attempt+1)).start()
                        return
                    else:
                        bot.reply_to(message_or_context, f"❌ Could not install `{mod}`. Aborting.")
                        return
                else:
                    # other runtime issue — but don't block here; proceed to start real process and log
                    pass
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except:
                pass
        except FileNotFoundError:
            bot.reply_to(message_or_context, f"❌ Python interpreter not found: {sys.executable}")
            return
        except Exception as e:
            logger.exception("Precheck error: %s", e)
    # start process with log file
    log_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
    try:
        logf = open(log_path, 'a', encoding='utf-8', errors='ignore')
    except Exception as e:
        try:
            bot.reply_to(message_or_context, f"❌ Failed to open log file: {e}")
        except:
            pass
        return
    try:
        proc = subprocess.Popen([sys.executable, path], cwd=user_folder, stdout=logf, stderr=logf, stdin=subprocess.PIPE)
        bot_scripts[script_key] = {'process': proc, 'log_file': logf, 'file_name': file_name}
        try:
            bot.reply_to(message_or_context, f"✅ Started `{file_name}` (PID: {proc.pid}).")
        except:
            pass
    except Exception as e:
        try:
            bot.reply_to(message_or_context, f"❌ Failed to start script: {e}")
        except:
            pass
        try:
            logf.close()
        except:
            pass

# run node script
def run_js_script(path, owner_id, user_folder, file_name, message_or_context, attempt=1):
    max_attempts = 2
    if attempt > max_attempts:
        try:
            bot.reply_to(message_or_context, f"❌ Failed to start {file_name} after {max_attempts} attempts.")
        except:
            pass
        return
    script_key = f"{owner_id}_{file_name}"
    if not os.path.exists(path):
        try:
            bot.reply_to(message_or_context, f"❌ File not found: {path}")
        except:
            pass
        remove_user_file_db(owner_id, file_name)
        return
    if attempt == 1:
        try:
            proc = subprocess.Popen(["node", path], cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            _, stderr = proc.communicate(timeout=5)
            if proc.returncode != 0 and stderr:
                m = re.search(r"Cannot find module '(.+?)'", stderr)
                if m:
                    mod = m.group(1)
                    if not mod.startswith('.') and not mod.startswith('/'):
                        if attempt_install_npm(mod, user_folder, message_or_context):
                            threading.Thread(target=run_js_script, args=(path, owner_id, user_folder, file_name, message_or_context, attempt+1)).start()
                            return
                        else:
                            try:
                                bot.reply_to(message_or_context, f"❌ Could not npm install `{mod}`.")
                            except:
                                pass
                            return
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except:
                pass
        except FileNotFoundError:
            try:
                bot.reply_to(message_or_context, "❌ `node` not found. Install Node.js.")
            except:
                pass
            return
        except Exception as e:
            logger.exception("JS precheck error: %s", e)
    # open log file and start
    log_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
    try:
        logf = open(log_path, 'a', encoding='utf-8', errors='ignore')
    except Exception as e:
        try:
            bot.reply_to(message_or_context, f"❌ Failed to open log file: {e}")
        except:
            pass
        return
    try:
        proc = subprocess.Popen(["node", path], cwd=user_folder, stdout=logf, stderr=logf, stdin=subprocess.PIPE)
        bot_scripts[script_key] = {'process': proc, 'log_file': logf, 'file_name': file_name}
        try:
            bot.reply_to(message_or_context, f"✅ Started JS `{file_name}` (PID: {proc.pid}).")
        except:
            pass
    except Exception as e:
        try:
            bot.reply_to(message_or_context, f"❌ Failed to start JS script: {e}")
        except:
            pass
        try:
            logf.close()
        except:
            pass

# --- Zip handler (extract, install deps, move to user folder, scan) ---
def handle_zip_file(downloaded_file_content, file_name_zip, message):
    user_id = message.from_user.id
    user_folder = get_user_folder(user_id)
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp(prefix=f"user_{user_id}_zip_")
        zip_path = os.path.join(temp_dir, file_name_zip)
        with open(zip_path, 'wb') as f:
            f.write(downloaded_file_content)

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # safety: prevent zip slip
            for member in zip_ref.infolist():
                member_path = os.path.abspath(os.path.join(temp_dir, member.filename))
                if not member_path.startswith(os.path.abspath(temp_dir)):
                    raise zipfile.BadZipFile("Zip contains unsafe path.")
            zip_ref.extractall(temp_dir)

        # collect files
        extracted = []
        for root, dirs, files in os.walk(temp_dir):
            for fname in files:
                extracted.append(os.path.relpath(os.path.join(root, fname), temp_dir))

        py_files = [f for f in extracted if f.endswith('.py')]
        js_files = [f for f in extracted if f.endswith('.js')]
        req_file = next((f for f in extracted if os.path.basename(f).lower() == 'requirements.txt'), None)
        pkg_json = next((f for f in extracted if os.path.basename(f).lower() == 'package.json'), None)

        # install dependencies if present
        if req_file:
            req_path = os.path.join(temp_dir, req_file)
            bot.reply_to(message, f"🔄 Installing Python deps from `{req_file}`...")
            try:
                subprocess.run([sys.executable, "-m", "pip", "install", "-r", req_path], capture_output=True, text=True, check=True)
                bot.reply_to(message, "✅ Python deps installed.")
            except subprocess.CalledProcessError as e:
                bot.reply_to(message, f"❌ Failed to install Python deps.\n{e.stderr or e.stdout}")
                return

        if pkg_json:
            bot.reply_to(message, f"🔄 Installing Node deps from `{pkg_json}`...")
            try:
                subprocess.run(["npm", "install"], capture_output=True, text=True, check=True, cwd=temp_dir)
                bot.reply_to(message, "✅ Node deps installed.")
            except FileNotFoundError:
                bot.reply_to(message, "❌ `npm` not installed on server.")
                return
            except subprocess.CalledProcessError as e:
                bot.reply_to(message, f"❌ npm install failed.\n{e.stderr or e.stdout}")
                return

        # move extracted files to user folder
        for root, dirs, files in os.walk(temp_dir):
            for fname in files:
                src = os.path.join(root, fname)
                rel = os.path.relpath(src, temp_dir)
                dest = os.path.join(user_folder, rel)
                dest_dir = os.path.dirname(dest)
                os.makedirs(dest_dir, exist_ok=True)
                if os.path.exists(dest):
                    try:
                        if os.path.isdir(dest):
                            shutil.rmtree(dest)
                        else:
                            os.remove(dest)
                    except:
                        pass
                shutil.move(src, dest)

        # determine main script
        preferred_py = ['main.py', 'bot.py', 'app.py']
        preferred_js = ['index.js', 'main.js', 'bot.js', 'app.js']
        top_files = os.listdir(user_folder)
        main_script = None
        ftype = None
        for p in preferred_py:
            if p in top_files:
                main_script = p; ftype = 'py'; break
        if not main_script:
            for p in preferred_js:
                if p in top_files:
                    main_script = p; ftype = 'js'; break
        if not main_script:
            if py_files:
                main_script = py_files[0]; ftype = 'py'
            elif js_files:
                main_script = js_files[0]; ftype = 'js'

        if not main_script:
            bot.reply_to(message, "❌ No runnable `.py` or `.js` file found in zip.")
            return

        save_user_file(user_id, main_script, ftype)
        main_path = os.path.join(user_folder, main_script)

        # scan for suspicious content across moved files
        suspect = False
        reasons = []
        for root, dirs, files in os.walk(user_folder):
            for fn in files:
                if fn.lower().endswith(('.py', '.js')):
                    pth = os.path.join(root, fn)
                    try:
                        with open(pth, 'r', encoding='utf-8', errors='ignore') as fh:
                            txt = fh.read(20000)
                        sus, matched = is_suspicious_code_text(txt)
                        if sus:
                            suspect = True
                            reasons.append(f"{os.path.relpath(pth, user_folder)}: {matched}")
                    except Exception:
                        suspect = True
                        reasons.append(f"{os.path.relpath(pth, user_folder)}: unreadable")

        reason_summary = ", ".join(reasons[:6]) if reasons else "No obvious suspicious patterns."
        if suspect:
            blocked_files[main_script] = {"user_id": user_id, "time": str(datetime.now()), "reason": reason_summary}
            save_blocked_files(blocked_files)
            send_owner_alert_simple(OWNER_ID, main_script, user_id, user_folder, main_path, reason_summary, message)
            bot.reply_to(message, f"⚠️ Suspicious content detected. Execution blocked. Owner notified.\nReason: {reason_summary}", parse_mode='Markdown')
            return

        bot.reply_to(message, f"✅ Files extracted. Starting `{main_script}`...", parse_mode='Markdown')
        if ftype == 'py':
            threading.Thread(target=run_script, args=(main_path, user_id, user_folder, main_script, message)).start()
        else:
            threading.Thread(target=run_js_script, args=(main_path, user_id, user_folder, main_script, message)).start()

    except zipfile.BadZipFile as e:
        bot.reply_to(message, f"❌ Invalid ZIP: {e}")
    except Exception as e:
        logger.exception("Error processing zip: %s", e)
        bot.reply_to(message, f"❌ Error processing zip: {e}")
    finally:
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except:
                pass

# --- Single file handlers ---
def handle_js_file(file_path, script_owner_id, user_folder, file_name, message):
    try:
        # quick scan
        sus = False; matched = None
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as rf:
                txt = rf.read(30000)
            sus, matched = is_suspicious_code_text(txt)
        except Exception:
            sus = True; matched = "unreadable"
        save_user_file(script_owner_id, file_name, 'js')
        if sus:
            blocked_files[file_name] = {"user_id": script_owner_id, "time": str(datetime.now()), "reason": matched}
            save_blocked_files(blocked_files)
            send_owner_alert_simple(OWNER_ID, file_name, script_owner_id, user_folder, file_path, matched, message)
            bot.reply_to(message, f"⚠️ `{file_name}` suspicious — blocked. Owner notified.", parse_mode='Markdown')
            return
        threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, message)).start()
    except Exception as e:
        logger.exception("Error in handle_js_file: %s", e)
        bot.reply_to(message, f"❌ Error processing JS file: {e}")

def handle_py_file(file_path, script_owner_id, user_folder, file_name, message):
    try:
        sus = False; matched = None
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as rf:
                txt = rf.read(30000)
            sus, matched = is_suspicious_code_text(txt)
        except Exception:
            sus = True; matched = "unreadable"
        save_user_file(script_owner_id, file_name, 'py')
        if sus:
            blocked_files[file_name] = {"user_id": script_owner_id, "time": str(datetime.now()), "reason": matched}
            save_blocked_files(blocked_files)
            send_owner_alert_simple(OWNER_ID, file_name, script_owner_id, user_folder, file_path, matched, message)
            bot.reply_to(message, f"⚠️ `{file_name}` suspicious — blocked. Owner notified.", parse_mode='Markdown')
            return
        threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, message)).start()
    except Exception as e:
        logger.exception("Error in handle_py_file: %s", e)
        bot.reply_to(message, f"❌ Error processing Python file: {e}")

# --- UI / keyboards ---
def create_reply_keyboard_main_menu(user_id):
    # Owner sees full menu; admins see limited (we keep owner-exclusive advanced)
    layout_user = [
        ["📢 Updates Channel"],
        ["📤 Upload File", "📂 Check Files"],
        ["⚡ Bot Speed", "📞 Contact Owner"]
    ]
    layout_owner = [
        ["📢 Updates Channel"],
        ["📤 Upload File", "📂 Check Files"],
        ["⚡ Bot Speed", "📊 Statistics"],
        ["💳 Subscriptions", "📢 Broadcast"],
        ["🔒 Lock Bot", "🟢 Run All Code"],
        ["👑 Admin Panel", "📞 Contact Owner"]
    ]
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    if user_id == OWNER_ID:
        layout = layout_owner
    elif user_id in admin_ids:
        # admins get slightly more than normal users but less than owner
        layout = [
            ["📢 Updates Channel"],
            ["📤 Upload File", "📂 Check Files"],
            ["⚡ Bot Speed", "📊 Statistics"],
            ["📞 Contact Owner"]
        ]
    else:
        layout = layout_user
    for row in layout:
        markup.add(*[types.KeyboardButton(text) for text in row])
    return markup

def create_main_menu_inline(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    buttons.append(types.InlineKeyboardButton('📢 Updates Channel', url=UPDATE_CHANNEL))
    buttons.append(types.InlineKeyboardButton('📤 Upload File', callback_data='upload'))
    buttons.append(types.InlineKeyboardButton('📂 Check Files', callback_data='check_files'))
    buttons.append(types.InlineKeyboardButton('⚡ Bot Speed', callback_data='speed'))
    buttons.append(types.InlineKeyboardButton('📞 Contact Owner', url=f'https://t.me/{YOUR_USERNAME.replace("@","")}'))
    # Owner only advanced
    if user_id == OWNER_ID:
        admin_buttons = [
            types.InlineKeyboardButton('💳 Subscriptions', callback_data='subscription'),
            types.InlineKeyboardButton('📊 Statistics', callback_data='stats'),
            types.InlineKeyboardButton('🔒 Lock Bot', callback_data='lock_bot'),
            types.InlineKeyboardButton('🟢 Run All User Scripts', callback_data='run_all_scripts'),
            types.InlineKeyboardButton('👑 Admin Panel', callback_data='admin_panel')
        ]
        for b in admin_buttons:
            markup.add(b)
    # common
    markup.add(types.InlineKeyboardButton('📤 Upload File', callback_data='upload'), types.InlineKeyboardButton('📂 Check Files', callback_data='check_files'))
    return markup

@bot.message_handler(commands=['start', 'help'])
def command_start(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    name = message.from_user.first_name or "User"
    username = message.from_user.username or "Not set"
    if bot_locked and user_id not in admin_ids:
        bot.send_message(chat_id, "⚠️ Bot locked. Try later.")
        return
    is_new = False
    if user_id not in active_users:
        is_new = True
        add_active_user(user_id)
    # send owner new-user alert with profile photo + name
    if is_new:
        try:
            # get profile photos
            photos = bot.get_user_profile_photos(user_id, limit=1)
            caption = f"🆕 New user started\nName: {name}\nUser: @{username}\nID: `{user_id}`"
            if photos.total_count > 0:
                file_id = photos.photos[0][-1].file_id
                bot.send_photo(OWNER_ID, file_id, caption=caption, parse_mode='Markdown')
            else:
                bot.send_message(OWNER_ID, caption, parse_mode='Markdown')
        except Exception as e:
            logger.exception("Failed to notify owner about new user: %s", e)
    # welcome message with user's own profile photo
    try:
        photos = bot.get_user_profile_photos(user_id, limit=1)
        status = "👑 Owner" if user_id == OWNER_ID else ("🛡️ Admin" if user_id in admin_ids else "🆓 Free User")
        msg = (f"👋 *Hello, {name}*\n\n🆔 `{user_id}`\n✳️ @{username}\n🔰 {status}\n"
               f"📁 Files: {get_user_file_count(user_id)} / {get_user_file_limit(user_id)}\n\n"
               "Upload `.py`, `.js`, or `.zip` files to run.")
        if photos.total_count > 0:
            file_id = photos.photos[0][-1].file_id
            bot.send_photo(chat_id, file_id, caption=msg, parse_mode='Markdown', reply_markup=create_reply_keyboard_main_menu(user_id))
        else:
            bot.send_message(chat_id, msg, parse_mode='Markdown', reply_markup=create_reply_keyboard_main_menu(user_id))
    except Exception as e:
        logger.exception("Error sending welcome: %s", e)
        try:
            bot.send_message(chat_id, "Welcome! (failed to fetch photo)", reply_markup=create_reply_keyboard_main_menu(user_id))
        except:
            pass

@bot.message_handler(commands=['uploadfile'])
def command_upload_file(message):
    uid = message.from_user.id
    if bot_locked and uid not in admin_ids:
        bot.reply_to(message, "⚠️ Bot locked.")
        return
    flimit = get_user_file_limit(uid)
    if get_user_file_count(uid) >= flimit:
        bot.reply_to(message, f"⚠️ File limit reached ({flimit}). Delete old files via /checkfiles.")
        return
    bot.reply_to(message, "📤 Send your `.py`, `.js` or `.zip` file as document.")

@bot.message_handler(commands=['checkfiles'])
def command_check_files(message):
    uid = message.from_user.id
    files = user_files.get(uid, [])
    if not files:
        bot.reply_to(message, "📂 No files uploaded yet.")
        return
    markup = types.InlineKeyboardMarkup()
    for fname, ftype in files:
        status = "🟢 Running" if is_bot_running(uid, fname) else "🔴 Stopped"
        markup.add(types.InlineKeyboardButton(f"{fname} ({ftype}) - {status}", callback_data=f"file_{uid}_{fname}"))
    bot.reply_to(message, "📂 Your files:", reply_markup=markup)

@bot.message_handler(commands=['ping'])
def ping_cmd(message):
    t0 = time.time()
    m = bot.reply_to(message, "Pong...")
    t1 = time.time()
    latency = round((t1 - t0) * 1000, 2)
    try:
        bot.edit_message_text(f"Pong! Latency: {latency} ms", m.chat.id, m.message_id)
    except:
        pass

# --- Button text mapping for reply keyboard ---
def _logic_run_all_scripts(message_or_context):
    # only owner allowed
    uid = message_or_context.from_user.id if isinstance(message_or_context, telebot.types.Message) else message_or_context.from_user.id
    if uid != OWNER_ID:
        try:
            bot.reply_to(message_or_context, "⚠️ Owner only.")
        except:
            pass
        return
    bot.reply_to(message_or_context, "⏳ Running all user scripts...")
    started = 0; skipped = 0; errors = []
    snapshot = dict(user_files)
    for user_id, flist in snapshot.items():
        for fname, ftype in flist:
            path = os.path.join(get_user_folder(user_id), fname)
            if not os.path.exists(path):
                skipped += 1; errors.append(f"{fname} (not found)"); continue
            if is_bot_running(user_id, fname):
                skipped += 1; continue
            try:
                if ftype == 'py':
                    threading.Thread(target=run_script, args=(path, user_id, get_user_folder(user_id), fname, message_or_context)).start()
                    started += 1
                elif ftype == 'js':
                    threading.Thread(target=run_js_script, args=(path, user_id, get_user_folder(user_id), fname, message_or_context)).start()
                    started += 1
                time.sleep(0.2)
            except Exception as e:
                errors.append(f"{fname}: {e}")
    bot.reply_to(message_or_context, f"✅ Done. Started: {started}, Skipped: {skipped}\nErrors: {errors[:5]}")

BUTTON_TEXT_TO_LOGIC = {
    "📢 Updates Channel": lambda m: bot.reply_to(m, "Visit: " + UPDATE_CHANNEL),
    "📤 Upload File": lambda m: bot.reply_to(m, "📤 Send your `.py`, `.js` or `.zip` file."),
    "📂 Check Files": lambda m: command_check_files(m),
    "⚡ Bot Speed": lambda m: ping_cmd(m),
    "📞 Contact Owner": lambda m: bot.reply_to(m, f"Contact Owner: https://t.me/{YOUR_USERNAME.replace('@','')}"),
    "📊 Statistics": lambda m: bot.reply_to(m, "Use /stats (owner only)."),
    "🔒 Lock Bot": lambda m: bot.reply_to(m, "Use /lockbot (owner only)."),
    "🟢 Run All Code": lambda m: _logic_run_all_scripts(m) if m.from_user.id == OWNER_ID else bot.reply_to(m, "Owner only."),
    "👑 Admin Panel": lambda m: bot.reply_to(m, "Owner only.")
}

@bot.message_handler(func=lambda message: message.text in BUTTON_TEXT_TO_LOGIC)
def handle_button_text(message):
    func = BUTTON_TEXT_TO_LOGIC.get(message.text)
    if func:
        try:
            func(message)
        except Exception as e:
            logger.exception("Button handler error: %s", e)

# --- Document handler (entrypoint for uploads) ---
@bot.message_handler(content_types=['document'])
def handle_file_upload_doc(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    doc = message.document
    if bot_locked and user_id not in admin_ids:
        bot.reply_to(message, "⚠️ Bot locked; cannot accept files.")
        return
    # enforce limits
    if get_user_file_count(user_id) >= get_user_file_limit(user_id):
        bot.reply_to(message, "⚠️ File limit reached. Delete via /checkfiles.")
        return
    file_name = doc.file_name or f"uploaded_{int(time.time())}"
    ext = os.path.splitext(file_name)[1].lower()
    if ext not in ('.py', '.js', '.zip'):
        bot.reply_to(message, "⚠️ Unsupported file type. Allowed: .py .js .zip")
        return
    if doc.file_size and doc.file_size > 40 * 1024 * 1024:
        bot.reply_to(message, "⚠️ File too large (max 40MB).")
        return
    try:
        # forward to owner for info (not approval)
        try:
            bot.forward_message(OWNER_ID, chat_id, message.message_id)
            bot.send_message(OWNER_ID, f"⬆️ File '{file_name}' from {message.from_user.first_name} (`{user_id}`)", parse_mode='Markdown')
        except Exception:
            pass
        m = bot.reply_to(message, f"⏳ Downloading `{file_name}`...")
        file_info = bot.get_file(doc.file_id)
        downloaded = bot.download_file(file_info.file_path)
        bot.edit_message_text(f"✅ Downloaded `{file_name}`. Processing...", chat_id, m.message_id)
        user_folder = get_user_folder(user_id)
        if ext == '.zip':
            handle_zip_file(downloaded, file_name, message)
        else:
            fpath = os.path.join(user_folder, file_name)
            with open(fpath, 'wb') as fh:
                fh.write(downloaded)
            if ext == '.py':
                handle_py_file(fpath, user_id, user_folder, file_name, message)
            elif ext == '.js':
                handle_js_file(fpath, user_id, user_folder, file_name, message)
            else:
                bot.reply_to(message, "Uploaded.")
    except telebot.apihelper.ApiTelegramException as e:
        logger.exception("Telegram API error: %s", e)
        bot.reply_to(message, f"Telegram API Error: {e}")
    except Exception as e:
        logger.exception("Error handling upload: %s", e)
        bot.reply_to(message, f"Unexpected error: {e}")

# --- Admin / Owner commands (owner-exclusive for sensitive ops) ---
@bot.message_handler(commands=['lockbot'])
def cmd_lockbot(message):
    global bot_locked
    uid = message.from_user.id
    if uid != OWNER_ID:
        bot.reply_to(message, "⚠️ Owner only.")
        return
    if bot_locked:
        bot.reply_to(message, "🔒 Bot already locked.")
        return
    bot_locked = True
    bot.reply_to(message, "🔒 Bot locked. Only owner/admin can use commands.")
    try:
        bot.send_message(OWNER_ID, f"🔒 Bot locked by {uid}")
    except:
        pass

@bot.message_handler(commands=['unlockbot'])
def cmd_unlockbot(message):
    global bot_locked
    uid = message.from_user.id
    if uid != OWNER_ID:
        bot.reply_to(message, "⚠️ Owner only.")
        return
    if not bot_locked:
        bot.reply_to(message, "🟢 Bot already unlocked.")
        return
    bot_locked = False
    bot.reply_to(message, "🟢 Bot unlocked.")
    try:
        bot.send_message(OWNER_ID, f"🟢 Bot unlocked by {uid}")
    except:
        pass

@bot.message_handler(commands=['stats'])
def cmd_stats(message):
    uid = message.from_user.id
    if uid != OWNER_ID:
        bot.reply_to(message, "⚠️ Owner only.")
        return
    total_users = len(active_users)
    total_files = sum(len(v) for v in user_files.values())
    running = 0; stopped = 0; blocked = len(blocked_files)
    for user_id, flist in user_files.items():
        for fname, ftype in flist:
            if is_bot_running(user_id, fname):
                running += 1
            else:
                stopped += 1
    text = (f"📊 *System Statistics*\n\nUsers: {total_users}\nFiles total: {total_files}\n"
            f"Running: {running}\nStopped: {stopped}\nBlocked/Quarantined: {blocked}")
    bot.reply_to(message, text, parse_mode='Markdown')

# --- Callback handler for inline buttons (files, admin actions) ---
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    try:
        data = call.data or ""
        user = call.from_user
        uid = user.id
        # file_<owner>_<filename>
        if data.startswith("file_"):
            parts = data.split('_', 2)
            if len(parts) < 3:
                bot.answer_callback_query(call.id, "Invalid data.")
                return
            owner = int(parts[1]); fname = parts[2]
            if is_bot_running(owner, fname):
                bot.answer_callback_query(call.id, f"{fname} is running.")
            else:
                bot.answer_callback_query(call.id, f"{fname} is stopped.")
            return
        if data == 'upload':
            bot.send_message(uid, "📤 Send your `.py`, `.js` or `.zip` file.")
            return
        if data == 'check_files':
            bot.send_message(uid, "Use /checkfiles to view files.")
            return
        if data == 'run_all_scripts':
            _logic_run_all_scripts(call)
            bot.answer_callback_query(call.id, "Running all scripts (owner only).")
            return
        if data == 'lock_bot':
            if uid == OWNER_ID:
                global bot_locked
                bot_locked = True
                bot.answer_callback_query(call.id, "Bot locked.")
                bot.send_message(OWNER_ID, "🔒 Bot locked via inline.")
            else:
                bot.answer_callback_query(call.id, "Owner only.")
            return
        # default
        bot.answer_callback_query(call.id, "Action received.")
    except Exception as e:
        logger.exception("Callback handler error: %s", e)
        try:
            bot.answer_callback_query(call.id, "Error.")
        except:
            pass

# --- Graceful exit: kill running scripts on shutdown ---
def shutdown_hook():
    logger.info("Shutting down: terminating child scripts.")
    for key, info in list(bot_scripts.items()):
        try:
            kill_process_tree(info)
        except:
            pass
    logger.info("Shutdown complete.")

import atexit
atexit.register(shutdown_hook)

# --- Start the bot ---
if __name__ == '__main__':
    keep_alive()
    try:
        logger.info("Bot starting polling...")
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt — exiting.")
    except Exception as e:
        logger.exception("Bot crashed: %s", e)
        # attempt clean shutdown
        shutdown_hook()
