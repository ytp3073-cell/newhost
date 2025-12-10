# wab.py
import telebot
import requests
import re
from telebot import types

# 🔑 Telegram Bot Token
BOT_TOKEN = "8563144181:AAG_36UamHSRFNGmIpgdjA94PF76uAGmEKE"
bot = telebot.TeleBot(BOT_TOKEN)

# 👑 OWNER TELEGRAM ID
OWNER_ID = 7652176329  # यहाँ अपना Telegram numeric ID डालना

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
# ⚙️ Safe Request Wrapper
# ────────────────────────────────
def safe_get(url, timeout=10):
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r
    except requests.exceptions.Timeout:
        return f"⚠️ *Error:* Connection timeout.\n🌐 URL: {url}"
    except requests.exceptions.ConnectionError:
        return f"⚠️ *Error:* Failed to connect.\n🌐 URL: {url}"
    except requests.exceptions.HTTPError as e:
        return f"⚠️ *Error:* HTTP {r.status_code} — {e}\n🌐 URL: {url}"
    except Exception as e:
        return f"⚠️ *Unexpected Error:* {e}\n🌐 URL: {url}"


# ────────────────────────────────
# 📡 APIs
# ────────────────────────────────
def get_info(number):
    res = safe_get(f"https://abbas-number-info.vercel.app/track?num={number}")
    if isinstance(res, str): return res
    try:
        data = res.json()
        if not data.get("success"): return "❌ कोई जानकारी नहीं मिली।"
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
        return msg
    except Exception as e:
        return f"⚠️ *Error (Number API):* {e}"


def get_local_num_info(number):
    res = safe_get(f"http://62.122.189.157:5000/num?number={number}")
    if isinstance(res, str): return res
    try:
        data = res.json()
        if not data: return "❌ Local API empty."
        return (
            f"👤 *Name:* {data.get('name','N/A')}\n"
            f"🏠 *Address:* {data.get('address','N/A')}\n"
            f"📞 *Mobile:* {data.get('number','N/A')}\n"
            f"📍 *State:* {data.get('state','N/A')}"
        )
    except Exception as e:
        return f"⚠️ *Error (Local API):* {e}"


def get_aadhar_info(aadhar):
    res = safe_get(f"http://62.122.189.157:5000/aadhar?aadhar={aadhar}")
    if isinstance(res, str): return res
    try:
        data = res.json()
        if not data or "name" not in data:
            return "❌ कोई Aadhar जानकारी नहीं मिली।"
        return (
            f"👤 *Name:* {data.get('name','N/A')}\n"
            f"🧓 *Father:* {data.get('father','N/A')}\n"
            f"🎂 *DOB:* {data.get('dob','N/A')}\n"
            f"🏠 *Address:* {data.get('address','N/A')}\n"
            f"📍 *State:* {data.get('state','N/A')}\n"
            f"🆔 *Aadhar:* `{aadhar}`"
        )
    except Exception as e:
        return f"⚠️ *Error (Aadhar API):* {e}"


def get_family_tree(aadhar):
    res = safe_get(f"https://chx-family-info.vercel.app/fetch?key=paidchx&aadhaar={aadhar}")
    if isinstance(res, str): return res
    try:
        data = res.json()
        if not isinstance(data, dict) or "memberDetailsList" not in data:
            return "❌ Family info not found."
        members = data.get("memberDetailsList", [])
        if not members: return "❌ Family list empty."
        msg = (
            f"🏠 *Address:* {data.get('address','N/A')}\n"
            f"🏙️ *District:* {data.get('homeDistName','N/A')}\n"
            f"🌏 *State:* {data.get('homeStateName','N/A')}\n"
            f"📄 *RC ID:* {data.get('rcId','N/A')}\n"
            f"🎯 *Scheme:* {data.get('schemeName','N/A')}\n\n"
            "👨‍👩‍👧‍👦 *Family Members:*\n"
        )
        for i, m in enumerate(members, start=1):
            msg += f"{i}. {m.get('memberName','N/A')} — {m.get('releationship_name','N/A')}\n"
        return msg.strip()
    except Exception as e:
        return f"⚠️ *Error (Family API):* {e}"


def get_postoffices_by_city(city):
    res = safe_get(f"https://api.postalpincode.in/postoffice/{city}")
    if isinstance(res, str): return res
    try:
        data = res.json()[0]
        if data["Status"] != "Success": return "❌ कोई पोस्ट ऑफिस नहीं मिला।"
        offices = data["PostOffice"]
        msg = f"🏙️ *City:* {city.title()}\n📦 *Post Offices:* {len(offices)}\n━━━━━━━━━━━━━━━━━━━\n"
        for i, o in enumerate(offices[:10], start=1):
            msg += f"{i}. {o['Name']} ({o['BranchType']}) — {o['District']}, {o['State']}\n"
        return msg
    except Exception as e:
        return f"⚠️ *Error (City API):* {e}"


def get_info_by_pincode(pin):
    res = safe_get(f"https://api.postalpincode.in/pincode/{pin}")
    if isinstance(res, str): return res
    try:
        data = res.json()[0]
        if data["Status"] != "Success": return "❌ Invalid PIN code."
        offices = data["PostOffice"]
        msg = f"📮 *Pincode:* {pin}\n🏙️ *Post Offices:* {len(offices)}\n━━━━━━━━━━━━━━━━━━━\n"
        for i, o in enumerate(offices[:10], start=1):
            msg += f"{i}. {o['Name']} ({o['BranchType']}) — {o['District']}, {o['State']}\n"
        return msg
    except Exception as e:
        return f"⚠️ *Error (Pincode API):* {e}"


def get_bank_info(ifsc):
    res = safe_get(f"https://ab-ifscinfoapi.vercel.app/info?ifsc={ifsc}")
    if isinstance(res, str): return res
    try:
        data = res.json()
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
        return f"⚠️ *Error (Bank API):* {e}"


# ────────────────────────────────
# 🧭 Keyboards
# ────────────────────────────────
def main_keyboard(uid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📱 Mobile Info", "🪪 Aadhar Info")
    kb.row("🏙️ City → Post Offices", "📮 Pincode Info")
    kb.row("🏦 IFSC → Bank Info")
    if uid == OWNER_ID:
        kb.row("👑 Owner Panel")
    return kb


# ────────────────────────────────
# /start
# ────────────────────────────────
@bot.message_handler(commands=['start'])
def start_cmd(msg):
    USERS.add(msg.from_user.id)
    bot.send_message(
        msg.chat.id,
        "👋 *Welcome to Multi Info Bot!*\n\n"
        "📱 Mobile / 🪪 Aadhar / 👨‍👩‍👧‍👦 Family / 🏙️ City / 📮 Pincode / 🏦 IFSC\n\n"
        "👨‍💻 Developer ⏤͟͟͞͞ 𝙊𝙂𝙔𝙔 𝙋𝙍𝙄𝙈𝙀 (@ban8t)",
        parse_mode="Markdown",
        reply_markup=main_keyboard(msg.from_user.id)
    )


# ────────────────────────────────
# MAIN HANDLER
# ────────────────────────────────
@bot.message_handler(func=lambda m: True)
def handler(msg):
    text = (msg.text or "").strip()
    uid = msg.from_user.id
    USERS.add(uid)

    try:
        if validate_mobile(text):
            res1 = get_info(text)
            res2 = get_local_num_info(text)
            bot.reply_to(msg, f"📱 *Mobile Info:*\n{res1}\n\n📍 *Local Data:*\n{res2}", parse_mode="Markdown", reply_markup=main_keyboard(uid))
            return
        if validate_aadhar(text):
            res = f"🪪 *Aadhar Info:*\n{get_aadhar_info(text)}\n\n👨‍👩‍👧‍👦 *Family Tree:*\n{get_family_tree(text)}"
            bot.reply_to(msg, res, parse_mode="Markdown", reply_markup=main_keyboard(uid))
            return
        if validate_pincode(text):
            bot.reply_to(msg, get_info_by_pincode(text), parse_mode="Markdown", reply_markup=main_keyboard(uid))
            return
        if validate_ifsc(text):
            bot.reply_to(msg, get_bank_info(text), parse_mode="Markdown", reply_markup=main_keyboard(uid))
            return
        if re.fullmatch(r"[A-Za-z ]{2,}", text):
            bot.reply_to(msg, get_postoffices_by_city(text), parse_mode="Markdown", reply_markup=main_keyboard(uid))
            return

        bot.reply_to(
            msg,
            "⚠️ *गलत इनपुट!* सही फ़ॉर्मेट ऐसे इस्तेमाल करो 👇\n\n"
            "📱 Mobile: 9876543210\n"
            "🪪 Aadhar: 202372727238\n"
            "🏙️ City: Delhi\n"
            "📮 Pincode: 400001\n"
            "🏦 IFSC: SBIN0018386\n\n"
            "👨‍💻 Developer ⏤͟͟͞͞ 𝙊𝙂𝙔𝙔 𝙋𝙍𝙄𝙈𝙀 (@ban8t)",
            parse_mode="Markdown",
            reply_markup=main_keyboard(uid)
        )

    except Exception as e:
        bot.reply_to(msg, f"⚠️ *Unexpected Error:* {e}", parse_mode="Markdown", reply_markup=main_keyboard(uid))


# ────────────────────────────────
# RUN
# ────────────────────────────────
if __name__ == "__main__":
    print("🤖 Safe Bot running with full error protection...")
    bot.infinity_polling(skip_pending=True)
