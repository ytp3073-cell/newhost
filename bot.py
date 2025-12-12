# bot.py
# Requirements:
#   pip install python-telegram-bot==20.6 cryptography
#
# Function:
#   - /start पर अपलोड-बटन दिखाता है
#   - User .py / .html / .htm / .txt फाइल भेजेगा तो encrypt करके
#     encrypted फाइल और key दोनों वापस भेजेगा
#
# Limit: 50 MB per file

import os
import tempfile
import time
import traceback
from cryptography.fernet import Fernet
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ---------------- CONFIG ----------------
BOT_TOKEN = "8419880200:AAG5OpgB0BG7FOpN-XrUu_7y3hGJKmWimI4"
MAX_FILE_SIZE = 50 * 1024 * 1024   # 50 MB
ALLOWED_EXTS = {".py", ".html", ".htm", ".txt"}
# ----------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("Upload file", callback_data="upload")]]
    msg = "File-encrypt bot.\nUpload .py / .html file, I’ll encrypt it."
    if update.message:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.effective_chat.send_message(msg, reply_markup=InlineKeyboardMarkup(kb))

async def button_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Send the file now (as document).")

def is_allowed_filename(name: str) -> bool:
    if not name:
        return False
    _, ext = os.path.splitext(name.lower())
    return ext in ALLOWED_EXTS

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    filename = doc.file_name or "file"

    if doc.file_size and doc.file_size > MAX_FILE_SIZE:
        await update.message.reply_text(f"File too large (> {MAX_FILE_SIZE} bytes).")
        return

    if not is_allowed_filename(filename):
        await update.message.reply_text(f"Only {', '.join(ALLOWED_EXTS)} allowed.")
        return

    status = await update.message.reply_text("फ़ाइल प्राप्त हुई — डाउनलोड कर रहा हूँ...")

    try:
        with tempfile.TemporaryDirectory() as td:
            local_path = os.path.join(td, filename)

            # get and download file
            try:
                tg_file = await context.bot.get_file(doc.file_id)
            except Exception as e:
                await status.edit_text(f"Telegram से फ़ाइल लाने में समस्या: {e}")
                return

            for attempt in range(1, 4):
                try:
                    await status.edit_text(f"Downloading (try {attempt})...")
                    await tg_file.download_to_drive(custom_path=local_path)
                    break
                except Exception as e:
                    if attempt == 3:
                        await status.edit_text(f"Download failed: {e}")
                        return
                    time.sleep(1)

            if not os.path.exists(local_path):
                await status.edit_text("Download incomplete.")
                return

            fsize = os.path.getsize(local_path)
            await status.edit_text(f"डाउनलोड पूरा ({fsize} bytes). Encrypt कर रहा हूँ...")

            # encrypt
            key = Fernet.generate_key()
            fernet = Fernet(key)
            with open(local_path, "rb") as rf:
                data = rf.read()
            encrypted = fernet.encrypt(data)

            enc_path = os.path.join(td, filename + ".enc")
            with open(enc_path, "wb") as ef:
                ef.write(encrypted)

            await status.edit_text("Encryption done — भेज रहा हूँ...")

            # send encrypted file
            with open(enc_path, "rb") as ef:
                await update.message.reply_document(
                    document=InputFile(ef, filename=filename + ".enc"),
                    caption="Encrypted file — इसे और key दोनों संभाल के रखें।",
                )

            # send key
            key_path = os.path.join(td, filename + ".key.txt")
            with open(key_path, "wb") as kf:
                kf.write(key)

            with open(key_path, "rb") as kf:
                await update.message.reply_document(
                    document=InputFile(kf, filename=filename + ".key.txt"),
                    caption="यह आपकी symmetric key है (Fernet key).",
                )

            await update.message.reply_text(
                f"Key (save safely):\n`{key.decode()}`", parse_mode="MarkdownV2"
            )

            await status.edit_text("काम हो गया — Encrypted फ़ाइल और key भेज दी गई है।")

    except Exception as e:
        traceback.print_exc()
        await status.edit_text(f"Unexpected error: {e}")

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("फ़ाइल भेजें या /start करें।")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_cb))
    app.add_handler(MessageHandler(filters.Document.ALL & ~filters.COMMAND, handle_document))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, unknown))
    print("Bot started.")
    app.run_polling()

if __name__ == "__main__":
    main()
