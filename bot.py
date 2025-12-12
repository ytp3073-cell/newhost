#!/usr/bin/env python3
# bot.py
# Async python-telegram-bot v20+ — Obfuscate uploaded files into a Python reconstructor.
# SECURITY: Bot token must be provided via environment variable BOT_TOKEN (do NOT hardcode).
# USAGE:
#   export BOT_TOKEN="your_new_token_here"
#   export OWNER_ID=7652176329   # optional, defaults to value below if not set
#   pip install python-telegram-bot>=20.0
#   python3 bot.py

import os
import zlib
import random
import logging
from io import BytesIO
from pathlib import Path
from telegram import InputFile, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------------- CONFIG ----------------
# Read token from environment for safety
BOT_TOKEN = os.environ.get("8513005164:AAHSB3MEuhcWAZSESON3gc8JfIYgY_dCDIk")
# Fallback owner id — replace or set OWNER_ID env instead
OWNER_ID = int(os.environ.get("OWNER_ID", "7652176329"))
MIN_SIZE_KB_DEFAULT = 50   # default minimum output size (KB)
INTS_PER_LINE = 16         # integers per line in generated .py
MAX_UPLOAD_MB = 30         # maximum allowed upload file size (MB)
TEMP_DIR = "tmp_bot_files" # temp dir for any local file ops
# ----------------------------------------

if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN environment variable not set. Export it before running.")
    raise SystemExit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

RECONSTRUCTOR_TEMPLATE = '''#!/usr/bin/env python3
# Auto-generated reconstructor. Run to recreate the original file.
import zlib, sys
data = [{data_array}]
KEY = {key}
out_path = "{out_name}"
b = bytes(d & 0xff for d in data)
b = bytes((x ^ KEY) for x in b)
try:
    orig = zlib.decompress(b)
except Exception:
    orig = None
    # If padding was appended, try trimming progressively from the end
    for cut in range(len(b)):
        try:
            maybe = zlib.decompress(b[:len(b)-cut])
            orig = maybe
            break
        except Exception:
            continue
    if orig is None:
        print("Failed to decompress. Possibly corrupted or wrong key.")
        sys.exit(2)
with open(out_path, "wb") as f:
    f.write(orig)
print("Wrote output:", out_path)
'''

def ensure_temp_dir():
    Path(TEMP_DIR).mkdir(exist_ok=True)

def process_file_bytes(orig_bytes: bytes, min_size_kb: int = MIN_SIZE_KB_DEFAULT):
    """
    Compress -> XOR with single-byte key -> pad to min_size_kb -> return int list and key.
    Note: single-byte XOR is weak (obfuscation only).
    """
    compressed = zlib.compress(orig_bytes, level=9)
    key = random.randint(1, 255)
    xord = bytes(b ^ key for b in compressed)
    target_len = max(len(xord), min_size_kb * 1024)
    if len(xord) < target_len:
        pad_len = target_len - len(xord)
        xord += os.urandom(pad_len)
    int_list = list(xord)
    return int_list, key, len(compressed), len(orig_bytes)

def make_reconstructor_py(int_list, key, original_filename):
    lines = []
    for i in range(0, len(int_list), INTS_PER_LINE):
        chunk = int_list[i:i+INTS_PER_LINE]
        lines.append(", ".join(str(x) for x in chunk))
    data_array = ",\n    ".join(lines)
    out_name = os.path.basename(original_filename).replace('"', '_').replace("'", "_")
    content = RECONSTRUCTOR_TEMPLATE.format(data_array=data_array, key=key, out_name=out_name)
    return content.encode("utf-8")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != OWNER_ID:
        await update.message.reply_text("Unauthorized.")
        return
    await update.message.reply_text(
        "Bot ready. Send a file (document). Optional caption: minkb=100 to force minimum output size in KB."
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send a file to obfuscate. Caption example: minkb=120\n"
        "Max upload size enforced on server."
    )

async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != OWNER_ID:
        await update.message.reply_text("Unauthorized.")
        return

    msg = update.message
    doc = msg.document
    if not doc:
        await update.message.reply_text("No document found.")
        return

    # Check file size limit
    file_size = doc.file_size or 0
    if file_size > MAX_UPLOAD_MB * 1024 * 1024:
        await update.message.reply_text(f"File too large. Max allowed {MAX_UPLOAD_MB} MB.")
        return

    caption = msg.caption or ""
    minkb = MIN_SIZE_KB_DEFAULT
    for part in caption.split():
        if part.lower().startswith("minkb="):
            try:
                minkb = int(part.split("=",1)[1])
            except:
                pass

    filename = doc.file_name or "input.bin"
    await update.message.reply_text(f"Downloading '{filename}' ({file_size} bytes)...")
    try:
        file_obj = await doc.get_file()
        bio = BytesIO()
        await file_obj.download_to_memory(out=bio)
        bio.seek(0)
        data = bio.read()
    except Exception as e:
        logging.exception("Download failed")
        await update.message.reply_text("Download failed: " + str(e))
        return

    if len(data) == 0:
        await update.message.reply_text("Empty file received.")
        return

    await update.message.reply_text("Processing file (compress + obfuscate) ...")
    try:
        int_list, key, comp_len, orig_len = process_file_bytes(data, min_size_kb=minkb)
        recon_bytes = make_reconstructor_py(int_list, key, filename)
    except Exception as e:
        logging.exception("Processing failed")
        await update.message.reply_text("Processing failed: " + str(e))
        return

    out_filename = f"reconstructor__{os.path.splitext(filename)[0]}.py"
    bio_out = BytesIO(recon_bytes)
    bio_out.name = out_filename
    bio_out.seek(0)

    try:
        await update.message.reply_document(
            document=InputFile(bio_out, filename=out_filename),
            filename=out_filename,
            caption=f"Run: python3 {out_filename}  (orig {orig_len} bytes)"
        )
    except Exception:
        logging.exception("Send failed")
        await update.message.reply_text("Failed to send generated file.")
        return

    logging.info(f"User {uid} obfuscated {filename} -> {out_filename} (orig {orig_len}, comp {comp_len}, key {key})")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.exception("Exception while handling update")

def main():
    ensure_temp_dir()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_error_handler(error_handler)
    print("Bot started. Listening ...")
    app.run_polling()

if __name__ == "__main__":
    main()
