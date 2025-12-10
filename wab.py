import telebot
import requests
import re

# 🔑 Telegram Bot Token यहाँ डाल
BOT_TOKEN = "8577640462:AAHhXUVxI9_A_749zMGndTj6Jyi-rvR_QK4"
bot = telebot.TeleBot(BOT_TOKEN)

# ────────────────────────────────
# 📡 Function: API से Info Fetch करना
# ────────────────────────────────
def get_info(number):
    url = f"https://abbas-number-info.vercel.app/track?num={number}"

    headers = {
        'User-Agent': "Mozilla/5.0 (Linux; Android 14; SM-X110 Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.7444.106 Safari/537.36",
        'Accept-Encoding': "gzip, deflate, br, zstd",
        'referer': "https://abbas-number-info.vercel.app/",
        'accept-language': "en-IN,en-US;q=0.9,en;q=0.8"
    }

    try:
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()

        if not data.get("success"):
            return "❌ कोई जानकारी नहीं मिली।"

        d = data["data"]

        msg = (
            "✅ *Information Found*\n\n"
            f"🔢 *Target Number:* `{number}`\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📄 *Record:*\n"
            f"• 👤 *Full Name:* {d.get('name', 'N/A')}\n"
            f"• 👨‍🦳 *Father Name:* {d.get('father_name', 'N/A')}\n"
            f"• 📱 *Mobile Number:* {d.get('mobile', 'N/A')}\n"
            f"• 🆔 *Aadhar Number:* {d.get('id_number', 'N/A')}\n"
            f"• 🏠 *Complete Address:* {d.get('address', 'N/A')}\n"
            f"• 📞 *Alternate Mobile:* {d.get('alt_mobile', 'N/A')}\n"
            f"• 📍 *Telecom Circle:* {d.get('circle', 'N/A')}\n"
            f"• 🔢 *User ID:* {d.get('id', 'N/A')}\n"
            "──────────────────────────────\n"
            "💻 *Bot by ABBAS*\n"
            "📱 Join: @abbas_tech_india"
        )
        return msg

    except Exception as e:
        return f"⚠️ Error: {e}"

# ────────────────────────────────
# 🧠 Function: नंबर Validate करना
# ────────────────────────────────
def validate_number(num):
    # सिर्फ digits रहने चाहिए
    num = num.strip().replace(" ", "")
    
    # +91 हटाओ अगर है
    if num.startswith("+91"):
        num = num[3:]
    elif num.startswith("91") and len(num) == 12:
        num = num[2:]

    # अब केवल 10 digit होने चाहिए
    if not re.fullmatch(r"\d{10}", num):
        return None
    return num

# ────────────────────────────────
# /start Command
# ────────────────────────────────
@bot.message_handler(commands=['start', 'help'])
def start_command(message):
    bot.reply_to(
        message,
        "👋 *Welcome to Number Info Bot!*\n\n"
        "📲 कोई भी *Indian Mobile Number* भेजो —\n"
        "उदाहरण: `9876543210` या `+919876543210`\n\n"
        "💻 *Bot by ABBAS*\n"
        "📱 Join: @abbas_tech_india",
        parse_mode="Markdown"
    )

# ────────────────────────────────
# जब User कोई Message भेजे
# ────────────────────────────────
@bot.message_handler(func=lambda msg: True)
def handle_message(message):
    text = message.text.strip()
    number = validate_number(text)

    if not number:
        bot.reply_to(
            message,
            "⚠️ गलत नंबर फॉर्मेट!\n\n"
            "📱 सही फॉर्मेट का उदाहरण:\n"
            "• 9876543210\n"
            "• +919876543210\n"
            "• 919876543210",
            parse_mode="Markdown"
        )
        return

    bot.send_chat_action(message.chat.id, "typing")
    result = get_info(number)
    bot.reply_to(message, result, parse_mode="Markdown")

# ────────────────────────────────
# BOT Run करो
# ────────────────────────────────
if __name__ == "__main__":
    print("🤖 Bot is running...")
    bot.infinity_polling()
