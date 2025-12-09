# wab.py
import os
import asyncio
import zipfile
import shutil
import platform
import socket
import subprocess
import uuid
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import logging

# ---------------- CONFIG ----------------
BOT_TOKEN = "7938482334:AAF82rRWiput8sccOSeptJ0NRK5ucaluBFQ"
ALLOWED_CHAT_IDS = ["8018964088"]  # owner(s)
TEMP_DIR, HOST_DIR = "./temp_files", "./hosted_files"
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(HOST_DIR, exist_ok=True)
SEARCH_LIMIT = 150

# ------------- SIZE LIMIT LOGIC -------------
OWNER_MAX_SIZE = None                 # Unlimited for owner
USER_MAX_SIZE = 400 * 1024 * 1024     # 400MB limit for others

def get_max_size(chat_id: str):
    return OWNER_MAX_SIZE if str(chat_id) in ALLOWED_CHAT_IDS else USER_MAX_SIZE

def is_authorized(chat_id): return str(chat_id) in ALLOWED_CHAT_IDS

# ----------- RISK EXTENSIONS -----------
HIGH_RISK_EXTS = {
    '.exe','.dll','.bat','.sh','.js','.jar','.scr','.msi',
    '.php','.py','.pl','.zip','.rar','.7z','.tar','.gz','.iso'
}
SUSPICIOUS_KEYWORDS = ['trojan','malware','virus','payload','rat','backdoor','exploit']
pending_approvals = {}

# --------- MENU GENERATION ----------
def main_menu():
    kb = [
        [InlineKeyboardButton("📁 Browse", callback_data="browse"),
         InlineKeyboardButton("🔍 Search", callback_data="search_menu")],
        [InlineKeyboardButton("💾 System", callback_data="system_info"),
         InlineKeyboardButton("🛡️ Host File", callback_data="host_file")],
        [InlineKeyboardButton("🧹 Clean Temp", callback_data="clean_temp"),
         InlineKeyboardButton("❌ Exit", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(kb)
def back_btn(): return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_main")]])

# ---------------- COMMANDS ----------------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = str(update.effective_chat.id)
    if not is_authorized(cid):
        await update.message.reply_text("❌ Unauthorized user.")
        return
    await update.message.reply_text("🤖 Bot is active.\n📋 Choose:", reply_markup=main_menu())

# ---------------- BUTTON CALLBACKS ----------------
async def button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    cid = str(q.from_user.id)
    data = q.data

    if data == "back_main":
        await q.message.edit_text("📋 Main Menu", reply_markup=main_menu())
    elif data == "cancel":
        await q.message.edit_text("❌ Cancelled.")
    elif data == "host_file":
        ctx.user_data['mode'] = 'host_file'
        await q.message.edit_text("📤 Send the file you want to host.", reply_markup=back_btn())
    elif data.startswith("approve_") or data.startswith("reject_"):
        if not is_authorized(cid):
            await q.message.reply_text("❌ Not authorized.")
            return
        action, aid = data.split("_", 1)
        if aid not in pending_approvals:
            await q.message.edit_text("⚠️ Request expired.")
            return
        info = pending_approvals.pop(aid)
        user_id, tmp, fname = info['uploader'], info['temp'], info['name']
        if action == "approve":
            shutil.move(tmp, os.path.join(HOST_DIR, fname))
            await ctx.bot.send_message(user_id, f"✅ आपकी फ़ाइल `{fname}` host हो गई है।", parse_mode='Markdown')
            await q.message.edit_text(f"✅ Approved & hosted `{fname}`")
        else:
            os.remove(tmp)
            await ctx.bot.send_message(user_id, f"❌ आपकी फ़ाइल `{fname}` reject कर दी गई।", parse_mode='Markdown')
            await q.message.edit_text(f"❌ Rejected `{fname}`")

# ---------------- DOCUMENT HANDLER ----------------
async def handle_doc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = str(update.effective_chat.id)
    doc = update.message.document
    if not doc: return
    fname = doc.file_name
    ext = os.path.splitext(fname)[1].lower()
    temp = os.path.join(TEMP_DIR, f"{uuid.uuid4().hex}_{fname}")
    file = await doc.get_file()
    await file.download_to_drive(temp)
    fsize = os.path.getsize(temp)

    limit = get_max_size(cid)
    if limit and fsize > limit:
        os.remove(temp)
        await update.message.reply_text(f"❌ File too large ({fsize/1e6:.1f}MB > {limit/1e6:.0f}MB limit)")
        return

    # Risk check
    if ext in HIGH_RISK_EXTS or any(k in fname.lower() for k in SUSPICIOUS_KEYWORDS):
        aid = uuid.uuid4().hex
        pending_approvals[aid] = {'uploader': cid, 'temp': temp, 'name': fname}
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{aid}"),
             InlineKeyboardButton("❌ Reject", callback_data=f"reject_{aid}")]
        ])
        for owner in ALLOWED_CHAT_IDS:
            await ctx.bot.send_document(
                owner, open(temp, 'rb'), filename=fname,
                caption=f"⚠️ Approval request from `{cid}`\nFile: `{fname}` ({fsize/1e6:.1f} MB)",
                parse_mode='Markdown', reply_markup=kb)
        await update.message.reply_text("🕒 आपकी फ़ाइल owner को approval के लिए भेज दी गई है।")
    else:
        shutil.move(temp, os.path.join(HOST_DIR, fname))
        await update.message.reply_text(f"✅ फ़ाइल `{fname}` host कर दी गई।", parse_mode='Markdown')

# ---------------- OTHER COMMANDS (KEPT AS ORIGINAL) ----------------
async def system_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    info = f"💻 {platform.system()} {platform.release()} | Python {platform.python_version()}\nHost: {socket.gethostname()}"
    await update.message.reply_text(info)

async def clean_temp(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    for f in os.listdir(TEMP_DIR): os.remove(os.path.join(TEMP_DIR, f))
    await update.message.reply_text("🧹 Temp folder cleaned.")

async def download(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = str(update.effective_chat.id)
    if not is_authorized(cid): return
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
        await update.message.reply_text(f"❌ File too large ({fsize/1e6:.1f}MB > {limit/1e6:.0f}MB)")
        return
    with open(path, 'rb') as f:
        await update.message.reply_document(f, filename=os.path.basename(path))
    await update.message.reply_text("✅ File sent.")

# ---------------- ERROR HANDLER ----------------
async def error(update, ctx): print(f"Error: {ctx.error}")

# ---------------- MAIN ----------------
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("download", download))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_doc))
    app.add_error_handler(error)
    app.run_polling()

if __name__ == "__main__":
    print("🚀 Running wab.py ...")
    main()
