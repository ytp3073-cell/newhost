# bot.py
# Requirements:
#   pip install python-telegram-bot==20.6 cryptography
#
# Usage:
#   1) Set your bot token in BOT_TOKEN
#   2) python3 bot.py
#
# Behavior:
#   - /start दिखाता है और अपलोड करने को कहता है
#   - यूजर जब .py या .html (या .htm/.txt) फ़ाइल अपलोड करेगा तो बॉट उसे एन्क्रिप्ट करके एन्क्रिप्टेड फ़ाइल और key वापस भेज देगा.
#   - Key को संभाल कर रखें — बिना key के डिक्रिप्ट नहीं होगा.

import os
import tempfile
from cryptography.fernet import Fernet
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# === CONFIGURE ===
BOT_TOKEN = "8419880200:AAG5OpgB0BG7FOpN-XrUu_7y3hGJKmWimI4"
# maximum file size to accept (bytes). changed to 50 MB as requested.
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
ALLOWED_EXTS = {".py", ".html", ".htm", ".txt"}  # आप चाहें तो जोड़/घटा सकते हैं

# === HANDLERS ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Upload file", callback_data="upload")]
    ]
    # Note: अगर message None (callback) तो दिखाने का तरीका अलग होगा; सामान्य flow के लिए यही काफी है।
    if update.message:
        await update.message.reply_text(
            "File encrypt bot.\nButton दबाकर फ़ाइल भेजिए, या सीधे फ़ाइल भेजें (.py, .html)।",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    else:
        await update.effective_chat.send_message(
            "File encrypt bot. फ़ाइल भेजें (.py, .html)।",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

async def button_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Send me the file now (as Document). मैं उसे एन्क्रिप्ट कर दूँगा।")

def is_allowed_filename(filename: str) -> bool:
    if not filename:
        return False
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_EXTS

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    filename = doc.file_name or "file"
    userid = update.message.from_user.id

    if doc.file_size > MAX_FILE_SIZE:
        await update.message.reply_text(f"File बड़ा है (> {MAX_FILE_SIZE} bytes). छोटा फ़ाइल भेजें।")
        return

    if not is_allowed_filename(filename):
        await update.message.reply_text(f"Unsupported extension. Supported: {', '.join(sorted(ALLOWED_EXTS))}")
        return

    msg = await update.message.reply_text("फ़ाइल प्राप्त हुई — डाउनलोड कर रहा हूँ...")
    # download file to temp
    with tempfile.TemporaryDirectory() as td:
        local_path = os.path.join(td, filename)
        await doc.get_file().download_to_drive(custom_path=local_path)
        # read bytes
        with open(local_path, "rb") as f:
            data = f.read()

        # generate key and encrypt
        key = Fernet.generate_key()
        fernet = Fernet(key)
        encrypted = fernet.encrypt(data)

        enc_name = filename + ".enc"
        enc_path = os.path.join(td, enc_name)
        with open(enc_path, "wb") as ef:
            ef.write(encrypted)

        # send encrypted file
        await msg.edit_text("एन्क्रिप्ट कर रहा हूँ, भेज रहा हूँ...")
        # send as document
        with open(enc_path, "rb") as ef:
            await update.message.reply_document(document=InputFile(ef, filename=enc_name),
                                                caption="Encrypted file — इसे और key दोनों संभाल के रखें।")

        # send key as a small file and as a message (user can copy)
        key_filename = filename + ".key.txt"
        key_path = os.path.join(td, key_filename)
        with open(key_path, "wb") as kf:
            kf.write(key)

        with open(key_path, "rb") as kf:
            await update.message.reply_document(document=InputFile(kf, filename=key_filename),
                                                caption="यह आपकी symmetric key है (Fernet key). इसे खोने पर डिक्रिप्ट नहीं कर पाएँगे।")

        # Also send key as text (for convenience)
        await update.message.reply_text(f"Key (copy and save safely):\n`{key.decode()}`", parse_mode="MarkdownV2")

        await msg.edit_text("काम हो गया। Encrypted फ़ाइल और key भेज दी गई है।")

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("समझ नहीं आया। फ़ाइल भेजें या /start करें।")

# === MAIN ===
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
