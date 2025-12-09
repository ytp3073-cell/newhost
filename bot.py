# wab.py
import os
import asyncio
import zipfile
import shutil
import platform
import mimetypes
import json
import socket
import subprocess
import uuid
from pathlib import Path
from datetime import datetime
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import logging

# ========== Logging ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)
logging.getLogger('telegram.ext').setLevel(logging.WARNING)
logging.getLogger('apscheduler').setLevel(logging.WARNING)

# ========== Config ==========
BOT_TOKEN = "7938482334:AAF82rRWiput8sccOSeptJ0NRK5ucaluBFQ"
ALLOWED_CHAT_IDS = ["8018964088"]  # owner/admin chat IDs

TEMP_DIR = "./temp_files"
HOST_DIR = "./hosted_files"
SEARCH_LIMIT = 150  # max search results
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(HOST_DIR, exist_ok=True)

# ========== Size limits ==========
OWNER_MAX_SIZE = None         # Unlimited for owner
USER_MAX_SIZE = 400 * 1024 * 1024  # 400 MB limit

def get_max_size(chat_id: str):
    if str(chat_id) in ALLOWED_CHAT_IDS:
        return OWNER_MAX_SIZE  # unlimited
    return USER_MAX_SIZE

# ========== Globals ==========
user_browsing_state = {}
user_sessions = {}
pending_approvals = {}

# ========== Extension sets ==========
FILE_EXTENSIONS = {
    'py': ['.py', '.pyw'],
    'zip': ['.zip', '.rar', '.7z', '.tar', '.gz', '.tar.gz', '.iso'],
    'txt': ['.txt', '.log', '.md', '.csv', '.json', '.xml', '.html', '.css', '.js'],
    'img': ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.webp', '.ico', '.tiff'],
    'video': ['.mp4', '.avi', '.mkv', '.mov', '.flv', '.wmv', '.webm', '.m4v'],
    'audio': ['.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma', '.m4a'],
    'doc': ['.pdf', '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt', '.odt'],
    'code': ['.py', '.js', '.html', '.css', '.php', '.java', '.cpp', '.c', '.go', '.rb', '.sh']
}

HIGH_RISK_EXTS = {
    '.exe', '.dll', '.bat', '.sh', '.js', '.jar', '.scr', '.msi', '.php', '.py',
    '.pl', '.com', '.bin', '.zip', '.rar', '.7z', '.tar', '.gz', '.iso'
}
SUSPICIOUS_KEYWORDS = ['trojan', 'malware', 'virus', 'payload', 'rat', 'backdoor', 'exploit']

# ========== Platform directories helper ==========
def get_platform_directories():
    system = platform.system()
    base = [os.path.expanduser("~"), "./", os.getcwd()]
    if system == "Linux":
        extra = ["/home", "/root", "/var/www", "/usr/local", "/opt", "/srv", "/tmp"]
    elif system == "Windows":
        extra = ["C:\\Users", "D:\\", "E:\\", os.getenv("USERPROFILE", "")]
    else:
        extra = ["/Users", "/Applications", "/var", "/tmp"]
    dirs = list(set([d for d in base + extra if d and os.path.exists(d)]))
    return dirs

def is_authorized(cid): return str(cid) in ALLOWED_CHAT_IDS

# ========== Keyboard Menus ==========
def main_menu():
    kb = [
        [InlineKeyboardButton("📁 Browse", callback_data="browse"),
         InlineKeyboardButton("🔍 Search", callback_data="search_menu")],
        [InlineKeyboardButton("💾 System", callback_data="system_info"),
         InlineKeyboardButton("📦 Backup", callback_data="quick_backup")],
        [InlineKeyboardButton("🛡️ Host File", callback_data="host_file"),
         InlineKeyboardButton("🗑️ Clean", callback_data="clean_temp")],
        [InlineKeyboardButton("❌ Exit", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(kb)

def back_btn(): return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_main")]])

# ========== Commands ==========
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = str(update.effective_chat.id)
    if not is_authorized(cid):
        await update.message.reply_text("❌ Unauthorized.")
        return
    txt = f"🤖 File Manager Bot\n\n📂 Working dir: `{os.getcwd()}`\nChoose an option:"
    await update.message.reply_text(txt, parse_mode='Markdown', reply_markup=main_menu())

# ========== File operations (simplified to show size logic) ==========
async def download(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = str(update.effective_chat.id)
    if not is_authorized(cid):
        await update.message.reply_text("❌ Unauthorized.")
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /download /path/to/file")
        return
    path = " ".join(ctx.args)
    if not os.path.exists(path):
        await update.message.reply_text("❌ Not found.")
        return
    fsize = os.path.getsize(path)
    limit = get_max_size(cid)
    if limit and fsize > limit:
        await update.message.reply_text(f"❌ File {fsize/1e6:.2f} MB exceeds limit {limit/1e6:.0f} MB")
        return
    with open(path, 'rb') as f:
        await update.message.reply_document(f, filename=os.path.basename(path))
    await update.message.reply_text("✅ Sent.")

# ========== Callback (only host logic shown for brevity) ==========
async def button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    cid = str(q.from_user.id)
    if not is_authorized(cid):
        await q.message.reply_text("❌ Unauthorized."); return
    d = q.data
    if d == "back_main":
        await q.message.edit_text("🏠 Main Menu", reply_markup=main_menu())
    elif d == "host_file":
        ctx.user_data['mode'] = 'host_file'
        await q.message.edit_text("📤 Send the file to host.", reply_markup=back_btn())
    elif d.startswith("approve_") or d.startswith("reject_"):
        act, aid = d.split("_", 1)
        info = pending_approvals.pop(aid, None)
        if not info: await q.message.edit_text("Expired."); return
        uid, tmp, fname = info['uploader_id'], info['temp'], info['name']
        if act == "approve":
            shutil.move(tmp, os.path.join(HOST_DIR, fname))
            await ctx.bot.send_message(uid, f"✅ Owner approved `{fname}`", parse_mode='Markdown')
            await q.message.edit_text(f"✅ Hosted `{fname}`")
        else:
            os.remove(tmp)
            await ctx.bot.send_message(uid, f"❌ Owner rejected `{fname}`", parse_mode='Markdown')
            await q.message.edit_text(f"❌ Rejected `{fname}`")

# ========== Document upload & approval ==========
async def doc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = str(update.effective_chat.id)
    doc = update.message.document
    fname = doc.file_name
    fext = os.path.splitext(fname)[1].lower()
    tmp = os.path.join(TEMP_DIR, f"{uuid.uuid4().hex}_{fname}")
    await (await doc.get_file()).download_to_drive(tmp)
    need_approval = fext in HIGH_RISK_EXTS or any(k in fname.lower() for k in SUSPICIOUS_KEYWORDS)
    if need_approval:
        aid = uuid.uuid4().hex
        pending_approvals[aid] = {'uploader_id': cid, 'temp': tmp, 'name': fname}
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f"approve_{aid}"),
                                    InlineKeyboardButton("❌ Reject", callback_data=f"reject_{aid}")]])
        msg = f"🔔 Approval request from `{cid}`\nFile: `{fname}`"
        for owner in ALLOWED_CHAT_IDS:
            await ctx.bot.send_message(owner, msg, parse_mode='Markdown', reply_markup=kb)
        await update.message.reply_text("⏳ Sent for approval.")
    else:
        lim = get_max_size(cid)
        if lim and os.path.getsize(tmp) > lim:
            os.remove(tmp)
            await update.message.reply_text(f"❌ File exceeds {lim/1e6:.0f} MB limit.")
            return
        shutil.move(tmp, os.path.join(HOST_DIR, fname))
        await update.message.reply_text("✅ Hosted directly.")

# ========== Error handler & main ==========
async def err(update, ctx): logger.error(ctx.error)

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("download", download))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.Document.ALL, doc))
    app.add_error_handler(err)
    app.run_polling()

if __name__ == "__main__":
    print("🚀 Running wab.py ...")
    main()
