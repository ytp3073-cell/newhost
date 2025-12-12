#!/usr/bin/env python3
# bot.py
# Simple Telegram bot that obfuscates an uploaded file into a Python "reconstructor".
# USAGE: set BOT_TOKEN and OWNER_ID below, then run: python3 bot.py
# WARNING: For educational use only. Don't use for illegal purposes.

import os
import zlib
import random
import textwrap
import logging
from io import BytesIO
from telegram import Update, InputFile
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# ------------- CONFIG -------------
BOT_TOKEN = "8513005164:AAHSB3MEuhcWAZSESON3gc8JfIYgY_dCDIk"
OWNER_ID = 7652176329  # replace with your Telegram numeric id
# Minimal output size (in KB). If resulting obfuscated code is smaller, bot will pad random bytes.
MIN_SIZE_KB = 50
# How many integers per output line for readability (affects generated file size)
INTS_PER_LINE = 16
# -----------------------------------

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def start(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    if uid != OWNER_ID:
        update.message.reply_text("Unauthorized. This bot is private.")
        return
    update.message.reply_text(
        "Send a file (any type). Bot will return an obfuscated Python file that reconstructs it.\n"
        "Use /help for options."
    )

def help_cmd(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Commands:\n"
        "/start - check access\n"
        "Send a file to obfuscate.\n\n"
        "You can optionally send a caption like: minkb=100 to force minimum output size in KB.\n"
        "Example: send file with caption `minkb=120`"
    )

def process_file_bytes(orig_bytes: bytes, min_size_kb: int = MIN_SIZE_KB):
    # Step 1: compress (zlib)
    compressed = zlib.compress(orig_bytes, level=9)

    # Step 2: generate a random single-byte key for XOR and apply
    key = random.randint(1, 255)
    xord = bytes(b ^ key for b in compressed)

    # Step 3: optionally pad with random bytes so that final list size (approx) >= min_size_kb
    target_len = max(len(xord), min_size_kb * 1024)
    if len(xord) < target_len:
        pad_len = target_len - len(xord)
        xord += os.urandom(pad_len)

    # Convert to list of ints (0-255)
    int_list = list(xord)
    return int_list, key, len(compressed), len(orig_bytes)

RECONSTRUCTOR_TEMPLATE = '''#!/usr/bin/env python3
# reconstructed_file_creator.py
# This file was auto-generated. Running it will recreate the original file produced by the bot.
import zlib
import sys
def main():
    data = [{data_array}]
    KEY = {key}
    out_path = "{out_name}"
    # Convert to bytes
    b = bytes(d & 0xff for d in data)
    # Reverse XOR
    b = bytes((x ^ KEY) for x in b)
    # Try to decompress; if padding present, find first valid decompression slice
    try:
        orig = zlib.decompress(b)
    except Exception:
        # If padding was added, search for valid decompress start from 0 up to small offset
        orig = None
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

if __name__ == "__main__":
    main()
'''

def make_reconstructor_py(int_list, key, original_filename):
    # Format the integer list into readable lines
    lines = []
    for i in range(0, len(int_list), INTS_PER_LINE):
        chunk = int_list[i:i+INTS_PER_LINE]
        lines.append(", ".join(str(x) for x in chunk))
    data_array = ",\n    ".join(lines)
    out_name = os.path.basename(original_filename)
    # sanitize out_name
    out_name = out_name.replace('"', '_').replace("'", "_")
    content = RECONSTRUCTOR_TEMPLATE.format(data_array=data_array, key=key, out_name=out_name)
    return content.encode("utf-8")

def on_document(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    if uid != OWNER_ID:
        update.message.reply_text("Unauthorized.")
        return
    msg = update.message
    caption = msg.caption or ""
    # parse caption for minkb
    minkb = MIN_SIZE_KB
    for part in caption.split():
        if part.lower().startswith("minkb="):
            try:
                minkb = int(part.split("=",1)[1])
            except:
                pass

    doc = msg.document
    filename = doc.file_name or "input.bin"
    msg.reply_text(f"Downloading file: {filename} ...")
    file_obj = context.bot.get_file(doc.file_id)
    bio = BytesIO()
    file_obj.download(out=bio)
    bio.seek(0)
    data = bio.read()
    msg.reply_text(f"Read {len(data)} bytes. Processing ...")

    int_list, key, comp_len, orig_len = process_file_bytes(data, min_size_kb=minkb)
    recon_bytes = make_reconstructor_py(int_list, key, filename)

    # Prepare a reasonable output filename
    out_filename = f"reconstructor__{os.path.splitext(filename)[0]}.py"
    # Send back
    msg.reply_text(f"Generated reconstructor ({len(recon_bytes)} bytes). Sending now.")
    bio_out = BytesIO(recon_bytes)
    bio_out.name = out_filename
    bio_out.seek(0)
    update.message.reply_document(document=InputFile(bio_out, filename=out_filename),
                                  filename=out_filename,
                                  caption="Reconstructor file. Run it with `python3 " + out_filename + "` to get the original file back.")
    logging.info(f"User {uid} obfuscated {filename} -> {out_filename} (orig {orig_len} bytes, compressed {comp_len} bytes, key {key})")

def error_handler(update: Update, context: CallbackContext):
    logging.exception("Error handling update")

def main():
    if BOT_TOKEN == "PUT_YOUR_BOT_TOKEN_HERE":
        print("Set BOT_TOKEN in the script before running.")
        return
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_cmd))
    dp.add_handler(MessageHandler(Filters.document, on_document))
    dp.add_error_handler(error_handler)

    print("Bot started. Listening...")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
