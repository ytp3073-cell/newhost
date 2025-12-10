# wab.py
import telebot
import requests
import re
from telebot import types

# 🔑 Telegram Bot Token
BOT_TOKEN = "8577640462:AAHhXUVxI9_A_749zMGndTj6Jyi-rvR_QK4"
bot = telebot.TeleBot(BOT_TOKEN)

# 👑 OWNER TELEGRAM ID (अपना डाल)
OWNER_ID = 8018964088  # <-- यहाँ अपना Telegram numeric ID डालना

# Local user list
USERS = set()

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
# 📡 APIs
# ────────────────────────────────
def get_info(number):
    try:
        r = requests.get(f"https://abbas-number-info.vercel.app/track?num={number}", timeout=10)
        data = r.json()
        if not data.get("success"):
            return None
        d = data.get("data", {})
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
            msg += "\n🪪 *Aadhar Lookup:*\n"
            msg += get_aadhar_info(d["id_number"])
        return msg
    except Exception as e:
        return f"⚠️ Error (Number Info): {e}"

def get_local_num_info(number):
    try:
        r = requests.get(f"http://62.122.189.157:5000/num?number={number}", timeout=10)
        if r.status_code != 200: return "❌ Local API error."
        data = r.json()
        if not data: return "❌ कोई डेटा नहीं मिला।"
        return (f"• 👤 *Name:* {data.get('name','N/A')}\n"
                f"• 🏠 *Address:* {data.get('address','N/A')}\n"
                f"• 📞 *Mobile:* {data.get('number','N/A')}\n"
                f"• 📍 *State:* {data.get('state','N/A')}")
    except Exception as e:
        return f"⚠️ Local API Error: {e}"

def get_aadhar_info(aadhar):
    try:
        r = requests.get(f"http://62.122.189.157:5000/aadhar?aadhar={aadhar}", timeout=10)
        if r.status_code != 200: return "❌ Aadhar API error."
        data = r.json()
        if not data or "name" not in data: return "❌ Aadhar info not found."
        return (f"• 👤 *Name:* {data.get('name','N/A')}\n"
                f"• 🧓 *Father:* {data.get('father','N/A')}\n"
                f"• 🎂 *DOB:* {data.get('dob','N/A')}\n"
                f"• 🏠 *Address:* {data.get('address','N/A')}\n"
                f"• 📍 *State:* {data.get('state','N/A')}\n"
                f"• 🆔 *Aadhar:* `{aadhar}`")
    except Exception as e:
        return f"⚠️ Aadhar Error: {e}"

def get_postoffices_by_city(city):
    try:
        r = requests.get(f"https://api.postalpincode.in/postoffice/{city}", timeout=10)
        data = r.json()[0]
        if data["Status"] != "Success": return "❌ कोई पोस्ट ऑफिस नहीं मिला।"
        offices = data["PostOffice"]
        msg = f"🏙️ *City:* {city.title()}\n📦 *Post Offices:* {len(offices)}\n━━━━━━━━━━━━━━━━━━━\n"
        for i, o in enumerate(offices[:10], start=1):
            msg += (f"{i}. {o['Name']} ({o['BranchType']})\n"
                    f"📮 PIN: {o['PINCode']} | {o['District']}, {o['State']}\n"
                    f"📦 {o['DeliveryStatus']}\n\n")
        return msg.strip()
    except Exception as e:
        return f"⚠️ City API Error: {e}"

def get_info_by_pincode(pin):
    try:
        r = requests.get(f"https://api.postalpincode.in/pincode/{pin}", timeout=10)
        data = r.json()[0]
        if data["Status"] != "Success": return "❌ Invalid PIN code."
        offices = data["PostOffice"]
        msg = f"📮 *Pincode:* {pin}\n🏙️ *Post Offices:* {len(offices)}\n━━━━━━━━━━━━━━━━━━━\n"
        for i, o in enumerate(offices[:10], start=1):
            msg += (f"{i}. {o['Name']} ({o['BranchType']})\n"
                    f"🏠 {o['District']}, {o['State']}\n"
                    f"📦 {o['DeliveryStatus']}\n\n")
        return msg.strip()
    except Exception as e:
        return f"⚠️ Pincode API Error: {e}"

def get_bank_info(ifsc):
    try:
        r = requests.get(f"https://ab-ifscinfoapi.vercel.app/info?ifsc={ifsc}", timeout=10)
        if r.status_code != 200: return "❌ IFSC API Error."
        data = r.json()
        if not data or "Bank Name" not in data: return "❌ Bank info not found."
        return (f"🏦 *Bank:* {data.get('Bank Name','N/A')}\n"
                f"🏢 *Branch:* {data.get('Branch','N/A')}\n"
                f"🆔 *IFSC:* `{data.get('IFSC','N/A')}`\n"
                f"🏠 *Address:* {data.get('Address','N/A')}\n"
                f"🏙️ *City:* {data.get('City','N/A')} | {data.get('State','N/A')}\n"
                f"📞 *Contact:* {data.get('Contact','N/A')}\n"
                f"💸 *RTGS:* {data.get('RTGS','N/A')}\n"
                f"💰 *NEFT:* {data.get('NEFT','N/A')}\n"
                f"⚡ *IMPS:* {data.get('IMPS','N/A')}\n"
                f"📲 *UPI:* {data.get('UPI','N/A')}")
    except Exception as e:
        return f"⚠️ Bank API Error: {e}"

# ────────────────────────────────
# 📋 Keyboards
# ────────────────────────────────
def main_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📱 Mobile Info", "🪪 Aadhar Info")
    kb.row("🏙️ City → Post Offices", "📮 Pincode Info")
    kb.row("🏦 IFSC → Bank Info")
    if OWNER_ID:
        kb.row("👑 Owner Panel")
    return kb

def owner_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📊 Stats", "📢 Broadcast")
    kb.row("♻️ Restart", "⬅️ Back")
    return kb

# ────────────────────────────────
# 🧠 Commands
# ────────────────────────────────
@bot.message_handler(commands=['start', 'help'])
def start_command(message):
    USERS.add(message.from_user.id)
    bot.send_message(
        message.chat.id,
        "👋 *Welcome to Multi Info Bot!*\n\n"
        "📱 Mobile / 🪪 Aadhar / 🏙️ City / 📮 Pincode / 🏦 IFSC\n\n"
        "💻 *Bot by ABBAS*",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

# ────────────────────────────────
# 👑 Owner Panel
# ────────────────────────────────
@bot.message_handler(commands=['owner'])
def owner_command(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "🚫 केवल Owner को अनुमति है।")
        return
    bot.send_message(message.chat.id, "👑 *Owner Panel Activated*", parse_mode="Markdown", reply_markup=owner_keyboard())

# ────────────────────────────────
# 🔥 Main Handler
# ────────────────────────────────
@bot.message_handler(func=lambda msg: True)
def handle_message(message):
    text = (message.text or "").strip()
    user_id = message.from_user.id
    USERS.add(user_id)

    # OWNER PANEL
    if user_id == OWNER_ID:
        if text == "📊 Stats":
            bot.reply_to(message, f"📈 *Total Users:* `{len(USERS)}`", parse_mode="Markdown", reply_markup=owner_keyboard())
            return
        elif text == "📢 Broadcast":
            bot.reply_to(message, "📩 Broadcast message भेजो:", reply_markup=types.ForceReply(selective=True))
            return
        elif text == "♻️ Restart":
            bot.reply_to(message, "🔁 Bot restart simulated.", reply_markup=main_keyboard())
            return
        elif text == "⬅️ Back":
            bot.reply_to(message, "↩️ Main menu पर लौटे।", reply_markup=main_keyboard())
            return

    # Normal buttons
    if text == "👑 Owner Panel" and user_id == OWNER_ID:
        bot.reply_to(message, "👑 *Welcome Owner!*", parse_mode="Markdown", reply_markup=owner_keyboard())
        return

    if text == "📱 Mobile Info":
        bot.reply_to(message, "📲 10-digit mobile number भेजो:", reply_markup=types.ReplyKeyboardRemove()); return
    elif text == "🪪 Aadhar Info":
        bot.reply_to(message, "🆔 12-digit Aadhaar number भेजो:", reply_markup=types.ReplyKeyboardRemove()); return
    elif text == "🏙️ City → Post Offices":
        bot.reply_to(message, "🏙️ City का नाम भेजो:", reply_markup=types.ReplyKeyboardRemove()); return
    elif text == "📮 Pincode Info":
        bot.reply_to(message, "📮 6-digit PIN code भेजो:", reply_markup=types.ReplyKeyboardRemove()); return
    elif text == "🏦 IFSC → Bank Info":
        bot.reply_to(message, "🏦 IFSC Code भेजो (e.g. SBIN0018386):", reply_markup=types.ReplyKeyboardRemove()); return

    # API Logic
    if validate_aadhar(text):
        res = get_aadhar_info(text)
        bot.reply_to(message, f"🪪 *Aadhar Info:*\n\n{res}", parse_mode="Markdown", reply_markup=main_keyboard()); return
    if validate_mobile(text):
        info1 = get_info(text) or "❌ कोई डेटा नहीं मिला।"
        info2 = get_local_num_info(text)
        bot.reply_to(message, f"📱 *Mobile Lookup:*\n\n{info1}\n━━━━━━━━━━━━━━━━━━━\n{info2}", parse_mode="Markdown", reply_markup=main_keyboard()); return
    if validate_pincode(text):
        res = get_info_by_pincode(text)
        bot.reply_to(message, res, parse_mode="Markdown", reply_markup=main_keyboard()); return
    if validate_ifsc(text):
        res = get_bank_info(text)
        bot.reply_to(message, f"🏦 *Bank Info:*\n\n{res}", parse_mode="Markdown", reply_markup=main_keyboard()); return
    if re.fullmatch(r"[A-Za-z ]{2,}", text):
        res = get_postoffices_by_city(text)
        bot.reply_to(message, res, parse_mode="Markdown", reply_markup=main_keyboard()); return

    # Broadcast (owner reply mode)
    if message.reply_to_message and user_id == OWNER_ID and "Broadcast message" in message.reply_to_message.text:
        for uid in USERS:
            try: bot.send_message(uid, f"📢 *Broadcast:*\n\n{text}", parse_mode="Markdown")
            except: pass
        bot.reply_to(message, f"✅ Broadcast sent to {len(USERS)} users.", reply_markup=owner_keyboard())
        return

    bot.reply_to(message, "⚠️ Invalid input.", reply_markup=main_keyboard())


# ────────────────────────────────
# 🚀 Run Bot
# ────────────────────────────────
if __name__ == "__main__":
    print("🤖 Bot is running with Owner Panel...")
    bot.infinity_polling()
