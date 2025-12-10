# wab.py
import telebot
import requests
import re
from telebot import types

# 🔑 Telegram Bot Token (NEW)
BOT_TOKEN = "8563144181:AAG_36UamHSRFNGmIpgdjA94PF76uAGmEKE"
bot = telebot.TeleBot(BOT_TOKEN)

# 👑 OWNER TELEGRAM ID (NEW)
OWNER_ID = 7652176329  

USERS = set()
BROADCAST_MODE = False

# ────────────────────────────────
# ✅ Validators
# ────────────────────────────────
def validate_mobile(num):
    s = num.strip().replace(" ", "").replace("-", "")
    if s.startswith("+91"):
        s = s[3:]
    elif s.startswith("91") and len(s) == 12:
        s = s[2:]
    return s if re.fullmatch(r"\d{10}", s) else None

def validate_aadhar(text):
    s = text.strip().replace(" ", "").replace("-", "")
    return s if re.fullmatch(r"\d{12}", s) else None

def validate_pincode(text):
    return text if re.fullmatch(r"\d{6}", text.strip()) else None

def validate_ifsc(text):
    s = text.strip().upper()
    return s if re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", s) else None

# ────────────────────────────────
# 📡 API Functions
# ────────────────────────────────
def get_info(number):
    try:
        r = requests.get(f"https://abbas-number-info.vercel.app/track?num={number}", timeout=10)
        data = r.json()
        if not data.get("success"):
            return "❌ कोई डेटा नहीं मिला।"
        d = data["data"]
        msg = (
            f"👤 *Name:* {d.get('name','N/A')}\n"
            f"👨‍🦳 *Father:* {d.get('father_name','N/A')}\n"
            f"📱 *Mobile:* {d.get('mobile','N/A')}\n"
            f"🆔 *Aadhar:* {d.get('id_number','N/A')}\n"
            f"🏠 *Address:* {d.get('address','N/A')}\n"
            f"📞 *Alt Mobile:* {d.get('alt_mobile','N/A')}\n"
            f"📍 *Circle:* {d.get('circle','N/A')}\n"
        )
        if d.get("id_number") and re.fullmatch(r"\d{12}", str(d["id_number"])):
            aadhar = str(d["id_number"])
            msg += "\n🪪 *Aadhar Lookup:*\n"
            msg += get_aadhar_info(aadhar)
            msg += "\n\n👨‍👩‍👧‍👦 *Family Tree:*\n"
            msg += get_family_tree(aadhar)
        return msg
    except Exception as e:
        return f"⚠️ Error (Number Info): {e}"

def get_local_num_info(number):
    try:
        r = requests.get(f"http://62.122.189.157:5000/num?number={number}", timeout=10)
        data = r.json()
        if not data:
            return "❌ कोई डेटा नहीं मिला।"
        return (
            f"• 👤 *Name:* {data.get('name','N/A')}\n"
            f"• 🏠 *Address:* {data.get('address','N/A')}\n"
            f"• 📞 *Mobile:* {data.get('number','N/A')}\n"
            f"• 📍 *State:* {data.get('state','N/A')}"
        )
    except Exception as e:
        return f"⚠️ Local API Error: {e}"

def get_aadhar_info(aadhar):
    try:
        r = requests.get(f"http://62.122.189.157:5000/aadhar?aadhar={aadhar}", timeout=10)
        data = r.json()
        if not data or "name" not in data:
            return "❌ Aadhar info not found."
        return (
            f"• 👤 *Name:* {data.get('name','N/A')}\n"
            f"• 🧓 *Father:* {data.get('father','N/A')}\n"
            f"• 🎂 *DOB:* {data.get('dob','N/A')}\n"
            f"• 🏠 *Address:* {data.get('address','N/A')}\n"
            f"• 📍 *State:* {data.get('state','N/A')}\n"
            f"• 🆔 *Aadhar:* `{aadhar}`"
        )
    except Exception as e:
        return f"⚠️ Aadhar Error: {e}"

def get_family_tree(aadhar):
    try:
        r = requests.get(f"https://chx-family-info.vercel.app/fetch?key=paidchx&aadhaar={aadhar}", timeout=10)
        data = r.json()
        if not isinstance(data, dict) or "memberDetailsList" not in data:
            return "❌ Family info not found."
        members = data.get("memberDetailsList", [])
        if not members:
            return "❌ Family list empty."
        msg = (
            f"🏠 *Address:* {data.get('address','N/A')}\n"
            f"🏙️ *District:* {data.get('homeDistName','N/A')}\n"
            f"🌏 *State:* {data.get('homeStateName','N/A')}\n"
            f"📄 *RC ID:* {data.get('rcId','N/A')}\n"
            f"🎯 *Scheme:* {data.get('schemeName','N/A')}\n\n"
            "👨‍👩‍👧‍👦 *Family Members:*\n"
        )
        for i, m in enumerate(members, start=1):
            msg += f"{i}. {m.get('memberName','N/A')} - {m.get('releationship_name','N/A')}\n"
        return msg.strip()
    except Exception as e:
        return f"⚠️ Family Tree Error: {e}"

def get_postoffices_by_city(city):
    try:
        r = requests.get(f"https://api.postalpincode.in/postoffice/{city}", timeout=10)
        data = r.json()[0]
        if data["Status"] != "Success":
            return "❌ कोई पोस्ट ऑफिस नहीं मिला।"
        offices = data["PostOffice"]
        msg = f"🏙️ *City:* {city.title()}\n📦 *Post Offices:* {len(offices)}\n━━━━━━━━━━━━━━━━━━━\n"
        for i, o in enumerate(offices[:10], start=1):
            msg += f"{i}. {o['Name']} ({o['BranchType']}) - {o['District']}, {o['State']}\n"
        return msg
    except Exception as e:
        return f"⚠️ City API Error: {e}"

def get_info_by_pincode(pin):
    try:
        r = requests.get(f"https://api.postalpincode.in/pincode/{pin}", timeout=10)
        data = r.json()[0]
        if data["Status"] != "Success":
            return "❌ Invalid PIN code."
        offices = data["PostOffice"]
        msg = f"📮 *Pincode:* {pin}\n🏙️ *Post Offices:* {len(offices)}\n━━━━━━━━━━━━━━━━━━━\n"
        for i, o in enumerate(offices[:10], start=1):
            msg += f"{i}. {o['Name']} ({o['BranchType']}) - {o['District']}, {o['State']}\n"
        return msg
    except Exception as e:
        return f"⚠️ Pincode API Error: {e}"

def get_bank_info(ifsc):
    try:
        r = requests.get(f"https://ab-ifscinfoapi.vercel.app/info?ifsc={ifsc}", timeout=10)
        data = r.json()
        if not data or "Bank Name" not in data:
            return "❌ Bank info not found."
        return (
            f"🏦 *Bank:* {data.get('Bank Name','N/A')}\n"
            f"🏢 *Branch:* {data.get('Branch','N/A')}\n"
            f"🆔 *IFSC:* `{data.get('IFSC','N/A')}`\n"
            f"🏠 *Address:* {data.get('Address','N/A')}\n"
            f"🏙️ *City:* {data.get('City','N/A')} | {data.get('State','N/A')}\n"
            f"📞 *Contact:* {data.get('Contact','N/A')}\n"
            f"💸 *RTGS:* {data.get('RTGS','N/A')}\n"
            f"💰 *NEFT:* {data.get('NEFT','N/A')}\n"
            f"⚡ *IMPS:* {data.get('IMPS','N/A')}\n"
            f"📲 *UPI:* {data.get('UPI','N/A')}"
        )
    except Exception as e:
        return f"⚠️ Bank API Error: {e}"

# ────────────────────────────────
# 📋 Keyboards
# ────────────────────────────────
def main_keyboard(user_id):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📱 Mobile Info", "🪪 Aadhar Info")
    kb.row("👨‍👩‍👧‍👦 Family", "🏙️ City → Post Offices")
    kb.row("📮 Pincode Info", "🏦 IFSC → Bank Info")
    if user_id == OWNER_ID:
        kb.row("👑 Owner Panel")
    return kb

def owner_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📊 Stats", "📢 Broadcast")
    kb.row("♻️ Restart", "⬅️ Back")
    return kb

# ────────────────────────────────
# /start
# ────────────────────────────────
@bot.message_handler(commands=['start'])
def start_cmd(message):
    USERS.add(message.from_user.id)
    bot.send_message(
        message.chat.id,
        "👋 *Welcome to Multi Info Bot!*\n\n"
        "📱 Mobile / 🪪 Aadhar / 👨‍👩‍👧‍👦 Family / 🏙️ City / 📮 Pincode / 🏦 IFSC\n\n"
        "👨‍💻 Developer ⏤͟͟͞͞ 𝙊𝙂𝙔𝙔 𝙋𝙍𝙄𝙈𝙀 (@ban8t)",
        parse_mode="Markdown",
        reply_markup=main_keyboard(message.from_user.id)
    )

# ────────────────────────────────
# MAIN HANDLER
# ────────────────────────────────
@bot.message_handler(func=lambda msg: True)
def handler(message):
    global BROADCAST_MODE
    text = (message.text or "").strip()
    uid = message.from_user.id
    USERS.add(uid)

    # Owner panel
    if uid == OWNER_ID:
        if text == "👑 Owner Panel":
            bot.send_message(uid, "👑 *Owner Panel Activated*", parse_mode="Markdown", reply_markup=owner_keyboard())
            return
        elif text == "📊 Stats":
            bot.reply_to(message, f"📈 *Total Users:* `{len(USERS)}`", parse_mode="Markdown", reply_markup=owner_keyboard())
            return
        elif text == "📢 Broadcast":
            BROADCAST_MODE = True
            bot.reply_to(message, "📩 अब Broadcast message भेजो:", reply_markup=types.ForceReply(selective=True))
            return
        elif text == "♻️ Restart":
            bot.reply_to(message, "🔁 Bot restart simulated.", reply_markup=main_keyboard(uid))
            return
        elif text == "⬅️ Back":
            BROADCAST_MODE = False
            bot.reply_to(message, "↩️ Main menu पर लौटे।", reply_markup=main_keyboard(uid))
            return

    # Broadcast Mode
    if BROADCAST_MODE and uid == OWNER_ID:
        for user in USERS:
            try:
                bot.send_message(user, text)
            except:
                continue
        BROADCAST_MODE = False
        bot.reply_to(message, "✅ Broadcast Sent to all users.", reply_markup=owner_keyboard())
        return

    # Family Button
    if text == "👨‍👩‍👧‍👦 Family":
        bot.reply_to(message, "🪪 Aadhaar Number भेजो (12-digit):", reply_markup=types.ReplyKeyboardRemove())
        return

    # Input Handling
    if validate_mobile(text):
        bot.reply_to(message, get_info(text), parse_mode="Markdown", reply_markup=main_keyboard(uid))
        return
    if validate_aadhar(text):
        bot.reply_to(message, f"🪪 *Aadhar Info:*\n\n{get_aadhar_info(text)}\n\n👨‍👩‍👧‍👦 *Family Tree:*\n\n{get_family_tree(text)}", parse_mode="Markdown", reply_markup=main_keyboard(uid))
        return
    if validate_pincode(text):
        bot.reply_to(message, get_info_by_pincode(text), parse_mode="Markdown", reply_markup=main_keyboard(uid))
        return
    if validate_ifsc(text):
        bot.reply_to(message, get_bank_info(text), parse_mode="Markdown", reply_markup=main_keyboard(uid))
        return
    if re.fullmatch(r"[A-Za-z ]{2,}", text):
        bot.reply_to(message, get_postoffices_by_city(text), parse_mode="Markdown", reply_markup=main_keyboard(uid))
        return

    bot.reply_to(message, "⚠️ गलत इनपुट।", reply_markup=main_keyboard(uid))

# ────────────────────────────────
# RUN
# ────────────────────────────────
if __name__ == "__main__":
    print("🤖 Bot running — all commands active.")
    bot.infinity_polling()
