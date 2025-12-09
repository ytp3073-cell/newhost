# -*- coding: utf-8 -*-
# Patched bot.py — includes malware-block-only approval flow
# Based on uploaded original file.

import telebot
import subprocess
import os
import zipfile
import tempfile
import shutil
from telebot import types
import time
from datetime import datetime, timedelta
import psutil
import sqlite3
import json
import logging
import signal
import threading
import re
import sys
import atexit
import requests

# --- Flask Keep Alive ---
from flask import Flask
from threading import Thread

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
    print("Flask Keep-Alive server started.")

# --- Configuration ---
TOKEN = '8341821928:AAEWHkJjKY_5r7Qkb3wp14-HEGDbYcGvtZw'  # replace with real token
OWNER_ID = 7652176329
ADMIN_ID = 7652176329
YOUR_USERNAME = 'BAN8T'
UPDATE_CHANNEL = 'https://t.me/BAN8T'

# Folders & DB
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

# Init bot
bot = telebot.TeleBot(TOKEN)

# Data structures
bot_scripts = {}
user_subscriptions = {}
user_files = {}
active_users = set()
admin_ids = {ADMIN_ID, OWNER_ID}
bot_locked = False

# Logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- DB init ---
DB_LOCK = threading.Lock()

def init_db():
    with DB_LOCK:
        try:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute('CREATE TABLE IF NOT EXISTS user_files (user_id INTEGER, file_name TEXT, file_type TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS active_users (user_id INTEGER)')
            c.execute('CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)')
            c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (OWNER_ID,))
            if ADMIN_ID != OWNER_ID:
                c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (ADMIN_ID,))
            conn.commit()
        except Exception as e:
            logger.error(f"DB init error: {e}", exc_info=True)
        finally:
            try: conn.close()
            except: pass

def load_data():
    with DB_LOCK:
        try:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute('SELECT user_id, file_name, file_type FROM user_files')
            for user_id, file_name, file_type in c.fetchall():
                if user_id not in user_files:
                    user_files[user_id] = []
                user_files[user_id].append((file_name, file_type))
            c.execute('SELECT user_id FROM active_users')
            active_users.update(user_id for (user_id,) in c.fetchall())
            c.execute('SELECT user_id FROM admins')
            admin_ids.update(user_id for (user_id,) in c.fetchall())
        except Exception as e:
            logger.error(f"Error loading data: {e}", exc_info=True)
        finally:
            try: conn.close()
            except: pass

init_db()
load_data()

# --- Helpers ---
def get_user_folder(user_id):
    user_folder = os.path.join(UPLOAD_BOTS_DIR, str(user_id))
    os.makedirs(user_folder, exist_ok=True)
    return user_folder

def get_user_file_limit(user_id):
    if user_id == OWNER_ID: return OWNER_LIMIT
    if user_id in admin_ids: return ADMIN_LIMIT
    if user_id in user_subscriptions and user_subscriptions[user_id]['expiry'] > datetime.now():
        return SUBSCRIBED_USER_LIMIT
    return FREE_USER_LIMIT

def get_user_file_count(user_id):
    return len(user_files.get(user_id, []))

def is_bot_running(script_owner_id, file_name):
    script_key = f"{script_owner_id}_{file_name}"
    script_info = bot_scripts.get(script_key)
    if script_info and script_info.get('process'):
        try:
            proc = psutil.Process(script_info['process'].pid)
            is_running = proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
            if not is_running:
                if 'log_file' in script_info and hasattr(script_info['log_file'], 'close') and not script_info['log_file'].closed:
                    try: script_info['log_file'].close()
                    except: pass
                if script_key in bot_scripts:
                    del bot_scripts[script_key]
            return is_running
        except psutil.NoSuchProcess:
            if script_key in bot_scripts:
                del bot_scripts[script_key]
            return False
        except Exception as e:
            logger.error(f"Error checking process for {script_key}: {e}", exc_info=True)
            return False
    return False

def save_user_file(user_id, file_name, file_type):
    with DB_LOCK:
        try:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute('INSERT INTO user_files (user_id, file_name, file_type) VALUES (?, ?, ?)', (user_id, file_name, file_type))
            conn.commit()
            if user_id not in user_files:
                user_files[user_id] = []
            user_files[user_id].append((file_name, file_type))
        except Exception as e:
            logger.error(f"Error saving user file metadata: {e}", exc_info=True)
        finally:
            try: conn.close()
            except: pass

def remove_user_file_db(user_id, file_name):
    with DB_LOCK:
        try:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute('DELETE FROM user_files WHERE user_id = ? AND file_name = ?', (user_id, file_name))
            conn.commit()
            if user_id in user_files:
                user_files[user_id] = [f for f in user_files[user_id] if f[0] != file_name]
                if not user_files[user_id]:
                    del user_files[user_id]
        except Exception as e:
            logger.error(f"Error removing user file from DB: {e}", exc_info=True)
        finally:
            try: conn.close()
            except: pass

def add_active_user(user_id):
    active_users.add(user_id)
    with DB_LOCK:
        try:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute('INSERT OR IGNORE INTO active_users (user_id) VALUES (?)', (user_id,))
            conn.commit()
        except Exception as e:
            logger.error(f"Error adding active user: {e}", exc_info=True)
        finally:
            try: conn.close()
            except: pass

# --- Malware-scan helpers ---
SUSPICIOUS_REGEXES = [
    r"\beval\s*\(", r"\bexec\s*\(", r"\bos\.remove\s*\(", r"\bshutil\.rmtree\s*\(",
    r"\bsubprocess\.Popen\s*\(", r"\bsocket\.", r"\brequests\.", r"\bftplib\.",
    r"open\s*\(.*['\"]/etc", r"import\s+ctypes", r"from\s+ctypes", r"import\s+cryptography",
]

def is_suspicious_code_text(text):
    for pat in SUSPICIOUS_REGEXES:
        try:
            if re.search(pat, text):
                return True, pat
        except re.error:
            continue
    return False, None

def send_owner_alert_simple(owner_id, file_name, user_id, user_folder, file_path, reason_summary, message_obj):
    text = (f"⚠️ *Malware Alert*\nUser: `{user_id}`\nFile: `{file_name}`\nReason: {reason_summary}\n\n"
            "File execution WAS BLOCKED. Inspect or quarantine if needed.")
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🗄️ Quarantine", callback_data=f"quarantine_{user_id}_{file_name}"))
    markup.add(types.InlineKeyboardButton("✅ Allow (override)", callback_data=f"override_{user_id}_{file_name}"))
    try:
        bot.send_message(owner_id, text, parse_mode='Markdown', reply_markup=markup)
    except Exception as e:
        logger.exception("Failed sending owner alert: %s", e)
    try:
        for aid in admin_ids:
            if aid != owner_id:
                try:
                    bot.send_message(aid, text, parse_mode='Markdown', reply_markup=markup)
                except:
                    pass
    except:
        pass

@bot.callback_query_handler(func=lambda c: c.data and (c.data.startswith("quarantine_") or c.data.startswith("override_")))
def owner_quarantine_override_cb(call):
    try:
        bot.answer_callback_query(call.id)
        data = call.data
        if data.startswith("quarantine_"):
            _, user_id_s, file_name = data.split('_', 2)
            user_folder = os.path.join(BASE_DIR, str(user_id_s))
            possible = os.path.join(user_folder, file_name)
            quarantined_dir = os.path.join(BASE_DIR, 'quarantine')
            os.makedirs(quarantined_dir, exist_ok=True)
            if os.path.exists(possible):
                dest = os.path.join(quarantined_dir, f"{user_id_s}_{file_name}_{int(time.time())}")
                shutil.move(possible, dest)
                bot.send_message(call.message.chat.id, f"🗄️ `{file_name}` moved to quarantine.")
                try: bot.send_message(int(user_id_s), f"ℹ️ Your file `{file_name}` was quarantined by admin.")
                except: pass
            else:
                bot.send_message(call.message.chat.id, "File not found.")
            return
        if data.startswith("override_"):
            _, user_id_s, file_name = data.split('_', 2)
            user_folder = os.path.join(BASE_DIR, str(user_id_s))
            path = os.path.join(user_folder, file_name)
            if not os.path.exists(path):
                bot.send_message(call.message.chat.id, "File not found to override/run.")
                return
            if file_name.lower().endswith('.py'):
                threading.Thread(target=run_script, args=(path, int(user_id_s), user_folder, file_name, call.message)).start()
                bot.send_message(call.message.chat.id, f"✅ `{file_name}` started by override.")
                try: bot.send_message(int(user_id_s), f"✅ Admin overrode and started your file `{file_name}`.")
                except: pass
            elif file_name.lower().endswith('.js'):
                threading.Thread(target=run_js_script, args=(path, int(user_id_s), user_folder, file_name, call.message)).start()
                bot.send_message(call.message.chat.id, f"✅ `{file_name}` started by override.")
                try: bot.send_message(int(user_id_s), f"✅ Admin overrode and started your file `{file_name}`.")
                except: pass
            return
    except Exception as e:
        logger.exception(f"Error in approval callback: {e}", exc_info=True)
        try: bot.answer_callback_query(call.id, "❌ Error handling approval.")
        except: pass

# --- Runner functions ---
def kill_process_tree(process_info):
    try:
        process = process_info.get('process')
        if not process or not hasattr(process, 'pid'):
            return
        pid = process.pid
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            try: child.terminate()
            except: pass
        psutil.wait_procs(children, timeout=1)
        try:
            parent.terminate()
            parent.wait(timeout=1)
        except psutil.TimeoutExpired:
            try: parent.kill()
            except: pass
    except Exception as e:
        logger.error(f"Error killing process tree: {e}", exc_info=True)

def attempt_install_pip(module_name, message):
    package_name = module_name
    try:
        bot.reply_to(message, f"🐍 Module `{module_name}` not found. Installing `{package_name}`...", parse_mode='Markdown')
        command = [sys.executable, '-m', 'pip', 'install', package_name]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            bot.reply_to(message, f"✅ Package `{package_name}` installed.")
            return True
        else:
            bot.reply_to(message, f"❌ Failed to install `{package_name}`.\n{result.stderr or result.stdout}")
            return False
    except Exception as e:
        bot.reply_to(message, f"❌ Error installing package `{package_name}`: {e}")
        return False

def attempt_install_npm(module_name, user_folder, message):
    try:
        bot.reply_to(message, f"🟠 Node package `{module_name}` not found. Installing locally...", parse_mode='Markdown')
        command = ['npm', 'install', module_name]
        result = subprocess.run(command, capture_output=True, text=True, check=False, cwd=user_folder)
        if result.returncode == 0:
            bot.reply_to(message, f"✅ Node package `{module_name}` installed locally.")
            return True
        else:
            bot.reply_to(message, f"❌ Failed to install Node package `{module_name}`.\n{result.stderr or result.stdout}")
            return False
    except FileNotFoundError:
        bot.reply_to(message, "❌ Error: 'npm' not found. Ensure Node.js/npm are installed and in PATH.")
        return False
    except Exception as e:
        bot.reply_to(message, f"❌ Error installing Node package `{module_name}`: {e}")
        return False

def run_script(path, owner_id, user_folder, file_name, message_or_context, attempt=1):
    max_attempts = 2
    if attempt > max_attempts:
        bot.reply_to(message_or_context, f"❌ Failed to run '{file_name}' after {max_attempts} attempts.")
        return

    script_key = f"{owner_id}_{file_name}"
    try:
        if not os.path.exists(path):
            bot.reply_to(message_or_context, f"❌ Script not found: {path}")
            remove_user_file_db(owner_id, file_name)
            return

        if attempt == 1:
            check_proc = None
            try:
                check_proc = subprocess.Popen([sys.executable, path], cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                stdout, stderr = check_proc.communicate(timeout=5)
                if check_proc.returncode != 0 and stderr:
                    match = re.search(r"ModuleNotFoundError: No module named '(.+?)'", stderr)
                    if match:
                        module_name = match.group(1)
                        if attempt_install_pip(module_name, message_or_context):
                            threading.Thread(target=run_script, args=(path, owner_id, user_folder, file_name, message_or_context, attempt+1)).start()
                            return
                        else:
                            bot.reply_to(message_or_context, f"❌ Install failed for `{module_name}`. Cannot run.")
                            return
                    else:
                        bot.reply_to(message_or_context, f"❌ Error in script pre-check:\n```\n{stderr[:500]}\n```", parse_mode='Markdown')
                        return
            except subprocess.TimeoutExpired:
                if check_proc and check_proc.poll() is None:
                    check_proc.kill()
            except FileNotFoundError:
                bot.reply_to(message_or_context, f"❌ Python interpreter not found: {sys.executable}")
                return
            finally:
                try:
                    if check_proc and check_proc.poll() is None:
                        check_proc.kill()
                except:
                    pass

        log_file_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        try:
            log_file = open(log_file_path, 'w', encoding='utf-8', errors='ignore')
        except Exception as e:
            bot.reply_to(message_or_context, f"❌ Failed to open log file: {e}")
            return

        proc = subprocess.Popen([sys.executable, path], cwd=user_folder, stdout=log_file, stderr=log_file, stdin=subprocess.PIPE)
        bot_scripts[script_key] = {'process': proc, 'log_file': log_file, 'file_name': file_name}
        bot.reply_to(message_or_context, f"✅ Python script '{file_name}' started (PID: {proc.pid}).")
    except Exception as e:
        bot.reply_to(message_or_context, f"❌ Unexpected error running script: {e}")
        if script_key in bot_scripts:
            kill_process_tree(bot_scripts[script_key])
            del bot_scripts[script_key]

def run_js_script(path, owner_id, user_folder, file_name, message_or_context, attempt=1):
    max_attempts = 2
    if attempt > max_attempts:
        bot.reply_to(message_or_context, f"❌ Failed to run '{file_name}' after {max_attempts} attempts.")
        return

    script_key = f"{owner_id}_{file_name}"
    try:
        if not os.path.exists(path):
            bot.reply_to(message_or_context, f"❌ Script not found: {path}")
            remove_user_file_db(owner_id, file_name)
            return

        if attempt == 1:
            check_proc = None
            try:
                check_proc = subprocess.Popen(['node', path], cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                stdout, stderr = check_proc.communicate(timeout=5)
                if check_proc.returncode != 0 and stderr:
                    match = re.search(r"Cannot find module '(.+?)'", stderr)
                    if match:
                        module_name = match.group(1)
                        if not module_name.startswith('.') and not module_name.startswith('/'):
                            if attempt_install_npm(module_name, user_folder, message_or_context):
                                threading.Thread(target=run_js_script, args=(path, owner_id, user_folder, file_name, message_or_context, attempt+1)).start()
                                return
                            else:
                                bot.reply_to(message_or_context, f"❌ NPM install failed for `{module_name}`.")
                                return
                    else:
                        bot.reply_to(message_or_context, f"❌ Error in JS pre-check:\n```\n{stderr[:500]}\n```", parse_mode='Markdown')
                        return
            except subprocess.TimeoutExpired:
                if check_proc and check_proc.poll() is None:
                    check_proc.kill()
            except FileNotFoundError:
                bot.reply_to(message_or_context, "❌ 'node' not found. Install Node.js to run JS files.")
                return
            finally:
                try:
                    if check_proc and check_proc.poll() is None:
                        check_proc.kill()
                except:
                    pass

        log_file_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        try:
            log_file = open(log_file_path, 'w', encoding='utf-8', errors='ignore')
        except Exception as e:
            bot.reply_to(message_or_context, f"❌ Failed to open log file: {e}")
            return

        proc = subprocess.Popen(['node', path], cwd=user_folder, stdout=log_file, stderr=log_file, stdin=subprocess.PIPE)
        bot_scripts[script_key] = {'process': proc, 'log_file': log_file, 'file_name': file_name}
        bot.reply_to(message_or_context, f"✅ JS script '{file_name}' started (PID: {proc.pid}).")
    except Exception as e:
        bot.reply_to(message_or_context, f"❌ Unexpected error running JS script: {e}")
        if script_key in bot_scripts:
            kill_process_tree(bot_scripts[script_key])
            del bot_scripts[script_key]

# --- Zip / File handlers (modified to include suspicious check on single files) ---
def handle_zip_file(downloaded_file_content, file_name_zip, message):
    user_id = message.from_user.id
    user_folder = get_user_folder(user_id)
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp(prefix=f"user_{user_id}_zip_")
        zip_path = os.path.join(temp_dir, file_name_zip)
        with open(zip_path, 'wb') as new_file:
            new_file.write(downloaded_file_content)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for member in zip_ref.infolist():
                member_path = os.path.abspath(os.path.join(temp_dir, member.filename))
                if not member_path.startswith(os.path.abspath(temp_dir)):
                    raise zipfile.BadZipFile(f"Zip has unsafe path: {member.filename}")
            zip_ref.extractall(temp_dir)

        extracted_items = []
        for root, dirs, files in os.walk(temp_dir):
            for f in files:
                extracted_items.append(os.path.relpath(os.path.join(root, f), temp_dir))

        py_files = [f for f in extracted_items if f.endswith('.py')]
        js_files = [f for f in extracted_items if f.endswith('.js')]
        req_file = next((f for f in extracted_items if os.path.basename(f).lower() == 'requirements.txt'), None)
        pkg_json = next((f for f in extracted_items if os.path.basename(f).lower() == 'package.json'), None)

        if req_file:
            req_path = os.path.join(temp_dir, req_file)
            bot.reply_to(message, f"🔄 Installing Python deps from `{req_file}`...")
            try:
                command = [sys.executable, '-m', 'pip', 'install', '-r', req_path]
                result = subprocess.run(command, capture_output=True, text=True, check=True)
                bot.reply_to(message, f"✅ Python deps installed.")
            except subprocess.CalledProcessError as e:
                bot.reply_to(message, f"❌ Failed to install Python deps.\n{e.stderr or e.stdout}")
                return
        if pkg_json:
            bot.reply_to(message, f"🔄 Installing Node deps from `{pkg_json}`...")
            try:
                command = ['npm', 'install']
                result = subprocess.run(command, capture_output=True, text=True, check=True, cwd=temp_dir)
                bot.reply_to(message, f"✅ Node deps installed.")
            except FileNotFoundError:
                bot.reply_to(message, "❌ 'npm' not found. Cannot install Node deps.")
                return
            except subprocess.CalledProcessError as e:
                bot.reply_to(message, f"❌ Failed to install Node deps.\n{e.stderr or e.stdout}")
                return

        # move files to user_folder
        moved_count = 0
        for root, dirs, files in os.walk(temp_dir):
            for item in files:
                rel_path = os.path.relpath(os.path.join(root, item), temp_dir)
                src_path = os.path.join(root, item)
                dest_path = os.path.join(user_folder, rel_path)
                dest_dir = os.path.dirname(dest_path)
                os.makedirs(dest_dir, exist_ok=True)
                if os.path.exists(dest_path):
                    try:
                        if os.path.isdir(dest_path): shutil.rmtree(dest_path)
                        else: os.remove(dest_path)
                    except: pass
                shutil.move(src_path, dest_path)
                moved_count += 1

        # choose main script
        main_script_name = None; file_type = None
        preferred_py = ['main.py', 'bot.py', 'app.py']; preferred_js = ['index.js', 'main.js', 'bot.js', 'app.js']
        existing_top = os.listdir(user_folder)
        for p in preferred_py:
            if p in existing_top:
                main_script_name = p; file_type = 'py'; break
        if not main_script_name:
            for p in preferred_js:
                if p in existing_top:
                    main_script_name = p; file_type = 'js'; break
        if not main_script_name:
            if py_files:
                main_script_name = py_files[0]; file_type = 'py'
            elif js_files:
                main_script_name = js_files[0]; file_type = 'js'
        if not main_script_name:
            bot.reply_to(message, "❌ No `.py` or `.js` script found in archive!")
            return

        save_user_file(user_id, main_script_name, file_type)
        main_script_path = os.path.join(user_folder, main_script_name)

        # scan all scripts moved; if any suspicious -> block and notify owner
        suspect_found = False
        suspect_reasons = []
        for root, dirs, files in os.walk(user_folder):
            for fn in files:
                if fn.lower().endswith(('.py', '.js')):
                    path = os.path.join(root, fn)
                    try:
                        with open(path, 'r', encoding='utf-8', errors='ignore') as rf:
                            txt = rf.read(20000)
                        sus, matched = is_suspicious_code_text(txt)
                        if sus:
                            suspect_found = True
                            suspect_reasons.append(f"{os.path.relpath(path, user_folder)}: {matched}")
                    except Exception:
                        suspect_found = True
                        suspect_reasons.append(f"{os.path.relpath(path, user_folder)}: unreadable")

        reason_summary = ", ".join(suspect_reasons[:6]) if suspect_reasons else "No obvious suspicious patterns."
        if suspect_found:
            send_owner_alert_simple(OWNER_ID, main_script_name, user_id, user_folder, main_script_path, reason_summary, message)
            bot.reply_to(message, f"⚠️ Suspicious content found in archive. Execution blocked. Admin notified.\nReason: {reason_summary}", parse_mode='Markdown')
            return

        bot.reply_to(message, f"✅ Files extracted. Starting main script: `{main_script_name}`...", parse_mode='Markdown')
        if file_type == 'py':
            threading.Thread(target=run_script, args=(main_script_path, user_id, user_folder, main_script_name, message)).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(main_script_path, user_id, user_folder, main_script_name, message)).start()

    except zipfile.BadZipFile as e:
        bot.reply_to(message, f"❌ Error: Invalid/corrupted ZIP. {e}")
    except Exception as e:
        logger.error(f"Error processing zip: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Error processing zip: {e}")
    finally:
        if temp_dir and os.path.exists(temp_dir):
            try: shutil.rmtree(temp_dir)
            except: pass

def handle_js_file(file_path, script_owner_id, user_folder, file_name, message):
    try:
        # scan small chunk
        suspicious = False; matched = None
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as rf:
                sample = rf.read(30000)
            suspicious, matched = is_suspicious_code_text(sample)
        except Exception:
            suspicious = True; matched = "unreadable"

        save_user_file(script_owner_id, file_name, 'js')

        if suspicious:
            reason = f"Pattern: {matched}" if matched else "Flagged by heuristic"
            send_owner_alert_simple(OWNER_ID, file_name, script_owner_id, user_folder, file_path, reason, message)
            bot.reply_to(message, f"⚠️ `{file_name}` appears suspicious and was blocked. Admin notified.", parse_mode='Markdown')
            return

        threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, message)).start()
    except Exception as e:
        logger.error(f"Error processing JS file: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Error processing JS file: {e}")

def handle_py_file(file_path, script_owner_id, user_folder, file_name, message):
    try:
        suspicious = False; matched = None
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as rf:
                sample = rf.read(30000)
            suspicious, matched = is_suspicious_code_text(sample)
        except Exception:
            suspicious = True; matched = "unreadable"

        save_user_file(script_owner_id, file_name, 'py')

        if suspicious:
            reason = f"Pattern: {matched}" if matched else "Flagged by heuristic"
            send_owner_alert_simple(OWNER_ID, file_name, script_owner_id, user_folder, file_path, reason, message)
            bot.reply_to(message, f"⚠️ `{file_name}` appears suspicious and was blocked. Admin notified.", parse_mode='Markdown')
            return

        threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, message)).start()
    except Exception as e:
        logger.error(f"Error processing Python file: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Error processing Python file: {e}")

# --- UI / Command logic ---
def create_main_menu_inline(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton('📢 Updates Channel', url=UPDATE_CHANNEL),
        types.InlineKeyboardButton('📤 Upload File', callback_data='upload'),
        types.InlineKeyboardButton('📂 Check Files', callback_data='check_files'),
        types.InlineKeyboardButton('⚡ Bot Speed', callback_data='speed'),
        types.InlineKeyboardButton('📞 Contact Owner', url=f'https://t.me/{YOUR_USERNAME.replace("@", "")}')
    ]
    if user_id in admin_ids:
        admin_buttons = [
            types.InlineKeyboardButton('💳 Subscriptions', callback_data='subscription'),
            types.InlineKeyboardButton('📊 Statistics', callback_data='stats'),
            types.InlineKeyboardButton('🔒 Lock Bot' if not bot_locked else '🔓 Unlock Bot',
                                     callback_data='lock_bot' if not bot_locked else 'unlock_bot'),
            types.InlineKeyboardButton('📢 Broadcast', callback_data='broadcast'),
            types.InlineKeyboardButton('👑 Admin Panel', callback_data='admin_panel'),
            types.InlineKeyboardButton('🟢 Run All User Scripts', callback_data='run_all_scripts')
        ]
        markup.add(buttons[0])
        markup.add(buttons[1], buttons[2])
        markup.add(buttons[3], admin_buttons[0])
        markup.add(admin_buttons[1], admin_buttons[3])
        markup.add(admin_buttons[2], admin_buttons[5])
        markup.add(admin_buttons[4])
        markup.add(buttons[4])
    else:
        markup.add(buttons[0], buttons[1])
        markup.add(buttons[3], buttons[2])
        markup.add(types.InlineKeyboardButton('📊 Statistics', callback_data='stats'))
        markup.add(buttons[4])
    return markup

def create_reply_keyboard_main_menu(user_id):
    layout_user = [
        ["📢 Updates Channel"],
        ["📤 Upload File", "📂 Check Files"],
        ["⚡ Bot Speed", "📊 Statistics"],
        ["📞 Contact Owner"]
    ]
    layout_admin = [
        ["📢 Updates Channel"],
        ["📤 Upload File", "📂 Check Files"],
        ["⚡ Bot Speed", "📊 Statistics"],
        ["💳 Subscriptions", "📢 Broadcast"],
        ["🔒 Lock Bot", "🟢 Run All Code"],
        ["👑 Admin Panel", "📞 Contact Owner"]
    ]
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    layout = layout_admin if user_id in admin_ids else layout_user
    for row in layout:
        markup.add(*[types.KeyboardButton(text) for text in row])
    return markup

# --- Command handlers ---
@bot.message_handler(commands=['start', 'help'])
def command_start(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    user_name = message.from_user.first_name
    user_username = message.from_user.username
    if bot_locked and user_id not in admin_ids:
        bot.send_message(chat_id, "⚠️ Bot locked by admin. Try later.")
        return
    if user_id not in active_users:
        add_active_user(user_id)
        try:
            owner_notification = (f"🎉 New user!\n👤 Name: {user_name}\n✳️ User: @{user_username or 'N/A'}\n"
                                  f"🆔 ID: `{user_id}`")
            bot.send_message(OWNER_ID, owner_notification, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Failed to notify owner: {e}", exc_info=True)
    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
    user_status = "👑 Owner" if user_id == OWNER_ID else ("🛡️ Admin" if user_id in admin_ids else "🆓 Free User")
    welcome_msg = (f"〽️ Welcome, {user_name}!\n\n🆔 Your User ID: `{user_id}`\n"
                   f"✳️ Username: `@{user_username or 'Not set'}`\n"
                   f"🔰 Your Status: {user_status}\n"
                   f"📁 Files Uploaded: {current_files} / {limit_str}\n\n"
                   f"🤖 Upload `.py`, `.js`, or `.zip` files to run.")
    try:
        bot.send_message(chat_id, welcome_msg, reply_markup=create_reply_keyboard_main_menu(user_id), parse_mode='Markdown')
    except Exception:
        try:
            bot.send_message(chat_id, welcome_msg, parse_mode='Markdown')
        except Exception:
            logger.error("Failed to send welcome", exc_info=True)

@bot.message_handler(commands=['uploadfile'])
def command_upload_file(message):
    user_id = message.from_user.id
    if bot_locked and user_id not in admin_ids:
        bot.reply_to(message, "⚠️ Bot locked by admin, cannot accept files.")
        return
    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    if current_files >= file_limit:
        limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
        bot.reply_to(message, f"⚠️ File limit ({current_files}/{limit_str}) reached.")
        return
    bot.reply_to(message, "📤 Send your Python (`.py`), JS (`.js`), or ZIP (`.zip`) file.")

@bot.message_handler(commands=['checkfiles'])
def command_check_files(message):
    user_id = message.from_user.id
    user_files_list = user_files.get(user_id, [])
    if not user_files_list:
        bot.reply_to(message, "📂 Your files:\n\n(No files uploaded yet)")
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for file_name, file_type in sorted(user_files_list):
        is_running = is_bot_running(user_id, file_name)
        status_icon = "🟢 Running" if is_running else "🔴 Stopped"
        btn_text = f"{file_name} ({file_type}) - {status_icon}"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f'file_{user_id}_{file_name}'))
    bot.reply_to(message, "📂 Your files:\nClick to manage.", reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(commands=['ping'])
def ping_cmd(message):
    start_ping = time.time()
    m = bot.reply_to(message, "Pong!")
    latency = round((time.time() - start_ping) * 1000, 2)
    bot.edit_message_text(f"Pong! Latency: {latency} ms", message.chat.id, m.message_id)

# Button text map
BUTTON_TEXT_TO_LOGIC = {
    "📢 Updates Channel": lambda m: bot.reply_to(m, "Visit updates: " + UPDATE_CHANNEL),
    "📤 Upload File": lambda m: bot.reply_to(m, "📤 Send your `.py`, `.js` or `.zip` file."),
    "📂 Check Files": lambda m: command_check_files(m),
    "⚡ Bot Speed": lambda m: bot.reply_to(m, "Use /ping to test speed."),
    "📞 Contact Owner": lambda m: bot.reply_to(m, "Contact Owner: " + f"https://t.me/{YOUR_USERNAME.replace('@','')}"),
    "📊 Statistics": lambda m: command_check_files(m),
    "💳 Subscriptions": lambda m: bot.reply_to(m, "Subscriptions panel (admin only)."),
    "📢 Broadcast": lambda m: bot.reply_to(m, "Broadcast (admin only)."),
    "🔒 Lock Bot": lambda m: bot.reply_to(m, "Use /lockbot to toggle."),
    "🟢 Run All Code": lambda m: _logic_run_all_scripts(m) if m.from_user.id in admin_ids else bot.reply_to(m, "Admin only."),
    "👑 Admin Panel": lambda m: bot.reply_to(m, "Admin panel.")
}

@bot.message_handler(func=lambda message: message.text in BUTTON_TEXT_TO_LOGIC)
def handle_button_text(message):
    func = BUTTON_TEXT_TO_LOGIC.get(message.text)
    if func:
        try: func(message)
        except Exception as e: logger.error(f"Error in button handler: {e}", exc_info=True)

# --- Document handler (entrypoint) ---
@bot.message_handler(content_types=['document'])
def handle_file_upload_doc(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    doc = message.document
    logger.info(f"Doc from {user_id}: {doc.file_name} ({doc.mime_type}), Size: {doc.file_size}")

    if bot_locked and user_id not in admin_ids:
        bot.reply_to(message, "⚠️ Bot locked, cannot accept files.")
        return

    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    if current_files >= file_limit:
        limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
        bot.reply_to(message, f"⚠️ File limit ({current_files}/{limit_str}) reached. Delete files via /checkfiles.")
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
        # forward to owner for info (not approval)
        try:
            bot.forward_message(OWNER_ID, chat_id, message.message_id)
            bot.send_message(OWNER_ID, f"⬆️ File '{file_name}' from {message.from_user.first_name} (`{user_id}`)", parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Failed to forward uploaded file to OWNER_ID {OWNER_ID}: {e}")

        downloading = bot.reply_to(message, f"⏳ Downloading `{file_name}`...")
        file_info = bot.get_file(doc.file_id)
        downloaded_file_content = bot.download_file(file_info.file_path)
        bot.edit_message_text(f"✅ Downloaded `{file_name}`. Processing...", chat_id, downloading.message_id)
        user_folder = get_user_folder(user_id)

        if file_ext == '.zip':
            handle_zip_file(downloaded_file_content, file_name, message)
        else:
            file_path = os.path.join(user_folder, file_name)
            with open(file_path, 'wb') as f:
                f.write(downloaded_file_content)
            if file_ext == '.py':
                handle_py_file(file_path, user_id, user_folder, file_name, message)
            elif file_ext == '.js':
                handle_js_file(file_path, user_id, user_folder, file_name, message)
            else:
                bot.reply_to(message, "File uploaded.")
    except telebot.apihelper.ApiTelegramException as e:
        logger.error(f"Telegram API Error handling file for {user_id}: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Telegram API Error: {e}")
    except Exception as e:
        logger.error(f"General error handling file for {user_id}: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Unexpected error: {e}")

# --- Admin: run all scripts function (keeps original behavior) ---
def _logic_run_all_scripts(message_or_call):
    if isinstance(message_or_call, telebot.types.Message):
        admin_user_id = message_or_call.from_user.id
        reply_func = lambda text, **kwargs: bot.reply_to(message_or_call, text, **kwargs)
        admin_message_obj_for_script_runner = message_or_call
    else:
        admin_user_id = message_or_call.from_user.id
        reply_func = lambda text, **kwargs: bot.send_message(message_or_call.message.chat.id, text, **kwargs)
        admin_message_obj_for_script_runner = message_or_call.message

    if admin_user_id not in admin_ids:
        reply_func("⚠️ Admin permissions required."); return

    reply_func("⏳ Starting to run all user scripts...")
    started_count = 0; attempted_users = 0; skipped_files = 0; error_files = []

    all_user_files_snapshot = dict(user_files)
    for target_user_id, files_for_user in all_user_files_snapshot.items():
        if not files_for_user: continue
        attempted_users += 1
        user_folder = get_user_folder(target_user_id)
        for file_name, file_type in files_for_user:
            if not is_bot_running(target_user_id, file_name):
                file_path = os.path.join(user_folder, file_name)
                if os.path.exists(file_path):
                    try:
                        if file_type == 'py':
                            threading.Thread(target=run_script, args=(file_path, target_user_id, user_folder, file_name, admin_message_obj_for_script_runner)).start()
                            started_count += 1
                        elif file_type == 'js':
                            threading.Thread(target=run_js_script, args=(file_path, target_user_id, user_folder, file_name, admin_message_obj_for_script_runner)).start()
                            started_count += 1
                        else:
                            skipped_files += 1
                            error_files.append(f"{file_name} (unknown type)")
                        time.sleep(0.6)
                    except Exception as e:
                        skipped_files += 1
                        error_files.append(f"{file_name} (error)")
                else:
                    skipped_files += 1
                    error_files.append(f"{file_name} (not found)")

    summary = (f"✅ Run All Scripts finished.\nStarted: {started_count}\nUsers processed: {attempted_users}\nSkipped: {skipped_files}")
    if error_files:
        summary += "\nErrors (sample):\n" + "\n".join(error_files[:5])
    reply_func(summary)

# --- Generic callback handler skeleton (file control etc.) ---
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    data = call.data
    user_id = call.from_user.id
    try:
        if data.startswith('file_'):
            # format: file_<owner>_<filename>
            parts = data.split('_', 2)
            if len(parts) < 3:
                bot.answer_callback_query(call.id, "Invalid callback data.")
                return
            owner = int(parts[1]); fname = parts[2]
            running = is_bot_running(owner, fname)
            if running:
                bot.answer_callback_query(call.id, f"{fname} is running.")
            else:
                bot.answer_callback_query(call.id, f"{fname} is stopped.")
        elif data.startswith('stop_') or data.startswith('start_') or data.startswith('restart_') or data.startswith('delete_') or data.startswith('logs_'):
            # Implement control actions if needed - left minimal to avoid accidental destructive ops
            bot.answer_callback_query(call.id, "Action received. (Admin-only operations.)")
        elif data == 'upload':
            bot.send_message(user_id, "📤 Send your `.py`, `.js` or `.zip` file.")
        else:
            bot.answer_callback_query(call.id, "Unhandled action.")
    except Exception as e:
        logger.error(f"Error handling callback '{data}': {e}", exc_info=True)
        try: bot.answer_callback_query(call.id, "Error processing action.")
        except: pass

# --- Start ---
if __name__ == '__main__':
    keep_alive()
    try:
        logger.info("Bot starting polling...")
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
    except KeyboardInterrupt:
        logger.info("Bot stopped by KeyboardInterrupt.")
    except Exception as e:
        logger.error(f"Bot crash: {e}", exc_info=True)
