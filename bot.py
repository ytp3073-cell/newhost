# wab.py
import telebot
import requests
import re
from telebot import types

# 🔑 Bot Token & Owner ID
BOT_TOKEN = "8563144181:AAG_36UamHSRFNGmIpgdjA94PF76uAGmEKE"
OWNER_ID = 7652176329

bot = telebot.TeleBot(BOT_TOKEN)
USERS = set()
WAITING_MODE = {}
BROADCAST_MODE = {}

# ────────────────────────────────
# 🔍 Validators
# ────────────────────────────────
def validate_mobile(num):
    s = num.strip().replace(" ", "").replace("-", "")
    if s.startswith("+91"): s = s[3:]
    elif s.startswith("91") and len(s) == 12: s = s[2:]
    return s if re.fullmatch(r"\d{10}", s) else None

def validate_aadhar(t): return t.strip().replace(" ", "") if re.fullmatch(r"\d{12}", t.strip().replace(" ", "")) else None
def validate_pincode(t): return t if re.fullmatch(r"\d{6}", t.strip()) else None
def validate_ifsc(t): s = t.strip().upper(); return s if re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", s) else None

# ────────────────────────────────
# 🌐 API Calls
# ────────────────────────────────
def get_json(url): 
    try:
        r = requests.get(url, timeout=10)
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def get_info(num):
    d = get_json(f"https://abbas-number-info.vercel.app/track?num={num}")
    if not d.get("success"): return "❌ कोई डेटा नहीं मिला।"
    d = d["data"]
    msg = (f"👤 *Name:* {d.get('name','N/A')}\n"
           f"👨‍🦳 *Father:* {d.get('father_name','N/A')}\n"
           f"📱 *Mobile:* {d.get('mobile','N/A')}\n"
           f"🆔 *Aadhar:* {d.get('id_number','N/A')}\n"
           f"🏠 *Address:* {d.get('address','N/A')}\n"
           f"📍 *Circle:* {d.get('circle','N/A')}\n")
    return msg

def get_aadhar_info(a):
    d = get_json(f"http://62.122.189.157:5000/aadhar?aadhar={a}")
    if not d or "name" not in d: return "❌ Aadhar info not found."
    return (f"👤 *Name:* {d.get('name','N/A')}\n"
            f"👨‍🦳 *Father:* {d.get('father','N/A')}\n"
            f"🎂 *DOB:* {d.get('dob','N/A')}\n"
            f"🏠 *Address:* {d.get('address','N/A')}\n"
            f"📍 *State:* {d.get('state','N/A')}\n"
            f"🆔 *Aadhar:* `{a}`")

def get_family_tree(a):
    d = get_json(f"https://chx-family-info.vercel.app/fetch?key=paidchx&aadhaar={a}")
    if "memberDetailsList" not in d: return "❌ Family info not found."
    members = d.get("memberDetailsList", [])
    msg = "👨‍👩‍👧‍👦 *Family Members:*\n"
    for i, m in enumerate(members, 1):
        msg += f"{i}. {m.get('memberName','N/A')} - {m.get('releationship_name','N/A')}\n"
    return msg.strip()

def get_city_info(c):
    d = get_json(f"https://api.postalpincode.in/postoffice/{c}")
    if not isinstance(d, list) or d[0]["Status"] != "Success": return "❌ कोई पोस्ट ऑफिस नहीं मिला।"
    p = d[0]["PostOffice"]
    msg = f"🏙️ *City:* {c.title()}\n📦 Offices: {len(p)}\n━━━━━━━━━━━━━━━\n"
    for i, o in enumerate(p[:10], 1):
        msg += f"{i}. {o['Name']} ({o['BranchType']}) - {o['District']}, {o['State']}\n"
    return msg

def get_pin_info(pin):
    d = get_json(f"https://api.postalpincode.in/pincode/{pin}")
    if not isinstance(d, list) or d[0]["Status"] != "Success": return "❌ Invalid PIN code."
    p = d[0]["PostOffice"]
    msg = f"📮 *Pincode:* {pin}\n🏙️ Offices: {len(p)}\n━━━━━━━━━━━━━━━\n"
    for i, o in enumerate(p[:10], 1):
        msg += f"{i}. {o['Name']} ({o['BranchType']}) - {o['District']}, {o['State']}\n"
    return msg

def get_ifsc_info(ifsc):
    d = get_json(f"https://ab-ifscinfoapi.vercel.app/info?ifsc={ifsc}")
    if "Bank Name" not in d: return "❌ Bank info not found."
    return (f"🏦 *Bank:* {d['Bank Name']}\n🏢 *Branch:* {d['Branch']}\n"
            f"🆔 *IFSC:* `{d['IFSC']}`\n🏠 *Address:* {d['Address']}\n"
            f"🏙️ *City:* {d['City']} | {d['State']}\n📞 *Contact:* {d['Contact']}")

# ────────────────────────────────
# 🧭 Keyboards
# ────────────────────────────────
def main_kb(uid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📱 Mobile Info", "🪪 Aadhar Info")
    kb.row("👨‍👩‍👧‍👦 Family", "🏙️ City → Post Offices")
    kb.row("📮 Pincode Info", "🏦 IFSC → Bank Info")
    if uid == OWNER_ID: kb.row("👑 Owner Panel")
    return kb

def owner_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📊 Stats", "📢 Broadcast")
    kb.row("♻️ Restart", "⬅️ Back")
    return kb

# ────────────────────────────────
# 🚀 Commands
# ────────────────────────────────
@bot.message_handler(commands=['start'])
def start(m):
    USERS.add(m.chat.id)
    bot.send_message(m.chat.id,
        "👋 *Welcome to Multi Info Bot!*\n\n"
        "📱 Mobile / 🪪 Aadhar / 👨‍👩‍👧‍👦 Family / 🏙️ City / 📮 Pincode / 🏦 IFSC\n\n"
        "👨‍💻 Developer ⏤͟͟͞͞ 𝙊𝙂𝙔𝙔 𝙋𝙍𝙄𝙈𝙀 (@ban8t)",
        parse_mode="Markdown", reply_markup=main_kb(m.chat.id))

# ────────────────────────────────
# 💬 Main Handler
# ────────────────────────────────
@bot.message_handler(func=lambda m: True)
def handler(m):
    global BROADCAST_MODE
    uid, text = m.chat.id, m.text.strip()
    USERS.add(uid)

    # 🧠 Owner Panel Actions
    if uid == OWNER_ID:
        if text == "👑 Owner Panel":
            bot.send_message(uid, "👑 *Owner Panel Activated*", parse_mode="Markdown", reply_markup=owner_kb()); return
        elif text == "📊 Stats":
            bot.send_message(uid, f"📈 *Total Users:* `{len(USERS)}`", parse_mode="Markdown"); return
        elif text == "📢 Broadcast":
            BROADCAST_MODE = True; bot.send_message(uid, "📩 Broadcast message भेजो:", reply_markup=types.ForceReply()); return
        elif text == "♻️ Restart":
            bot.send_message(uid, "🔁 Restart Done ✅", reply_markup=owner_kb()); return
        elif text == "⬅️ Back":
            BROADCAST_MODE = False; bot.send_message(uid, "↩️ Main Menu", reply_markup=main_kb(uid)); return

    # 📢 Broadcast Mode
    if BROADCAST_MODE and uid == OWNER_ID:
        for u in USERS:
            try: bot.send_message(u, text)
            except: pass
        BROADCAST_MODE = False
        bot.send_message(uid, "✅ Broadcast sent to all users!", reply_markup=owner_kb()); return

    # 🎯 Button Inputs
    if text == "📱 Mobile Info": WAITING_MODE[uid] = "mobile"; bot.send_message(uid, "📲 Number भेजो:", reply_markup=types.ReplyKeyboardRemove()); return
    if text == "🪪 Aadhar Info": WAITING_MODE[uid] = "aadhar"; bot.send_message(uid, "🪪 Aadhar Number भेजो:", reply_markup=types.ReplyKeyboardRemove()); return
    if text == "👨‍👩‍👧‍👦 Family": WAITING_MODE[uid] = "family"; bot.send_message(uid, "🪪 Aadhar Number भेजो:", reply_markup=types.ReplyKeyboardRemove()); return
    if text == "🏙️ City → Post Offices": WAITING_MODE[uid] = "city"; bot.send_message(uid, "🏙️ City Name भेजो:", reply_markup=types.ReplyKeyboardRemove()); return
    if text == "📮 Pincode Info": WAITING_MODE[uid] = "pincode"; bot.send_message(uid, "📮 Pincode भेजो:", reply_markup=types.ReplyKeyboardRemove()); return
    if text == "🏦 IFSC → Bank Info": WAITING_MODE[uid] = "ifsc"; bot.send_message(uid, "🏦 IFSC Code भेजो:", reply_markup=types.ReplyKeyboardRemove()); return

    # 🔄 Waiting Mode Handling
    if uid in WAITING_MODE:
        mode = WAITING_MODE.pop(uid)
        if mode == "mobile" and validate_mobile(text): bot.send_message(uid, get_info(text), parse_mode="Markdown", reply_markup=main_kb(uid))
        elif mode == "aadhar" and validate_aadhar(text): bot.send_message(uid, get_aadhar_info(text), parse_mode="Markdown", reply_markup=main_kb(uid))
        elif mode == "family" and validate_aadhar(text): bot.send_message(uid, get_family_tree(text), parse_mode="Markdown", reply_markup=main_kb(uid))
        elif mode == "city": bot.send_message(uid, get_city_info(text), parse_mode="Markdown", reply_markup=main_kb(uid))
        elif mode == "pincode" and validate_pincode(text): bot.send_message(uid, get_pin_info(text), parse_mode="Markdown", reply_markup=main_kb(uid))
        elif mode == "ifsc" and validate_ifsc(text): bot.send_message(uid, get_ifsc_info(text), parse_mode="Markdown", reply_markup=main_kb(uid))
        else: bot.send_message(uid, "⚠️ गलत इनपुट।", reply_markup=main_kb(uid))
        return

    # Default Fallback
    bot.send_message(uid, "⚠️ गलत इनपुट।", reply_markup=main_kb(uid))

# ────────────────────────────────
# 🚀 Run Bot
# ────────────────────────────────
if __name__ == "__main__":
    print("🤖 BOT STARTED — ALL COMMANDS + OWNER PANEL FIXED ✅")
    bot.infinity_polling()
