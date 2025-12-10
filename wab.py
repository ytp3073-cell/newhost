 import telebot
import requests
import json

# ─────────────────────────────────────
# BOT TOKEN डाल यहाँ
# ─────────────────────────────────────
BOT_TOKEN = "8577640462:AAFyZqfoqPJ-MtqFHCGKxdOtoD0xqPWwSlA"
bot = telebot.TeleBot(BOT_TOKEN)

# ─────────────────────────────────────
# API से डेटा लेने वाला फ़ंक्शन
# ─────────────────────────────────────
def get_info(number):
    url = f"https://abbas-number-info.vercel.app/track?num={number}"

    headers = {
        'User-Agent': "Mozilla/5.0 (Linux; Android 14; SM-X110 Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.7444.106 Safari/537.36",
        'Accept-Encoding': "gzip, deflate, br, zstd",
        'sec-ch-ua-platform': "\"Android\"",
        'sec-ch-ua': "\"Chromium\";v=\"142\", \"Android WebView\";v=\"142\", \"Not_A Brand\";v=\"99\"",
        'sec-ch-ua-mobile': "?1",
        'x-requested-with': "mark.via.gp",
        'sec-fetch-site': "same-origin",
        'sec-fetch-mode': "cors",
        'sec-fetch-dest': "empty",
        'referer': "https://abbas-number-info.vercel.app/",
        'accept-language': "en-IN,en-US;q=0.9,en;q=0.8",
        'priority': "u=1, i"
    }

    try:
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()

        if not data.get("success"):
            return "❌ कोई जानकारी नहीं मिली।"

        d = data["data"]

        info = (
            "✅ *Information Found*\n\n"
            f"🔢 *Target Number:* `{number}`\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📄 *Record:*\n"
            f"• 👤 *Full Name:* {d.get('name','')}\n"
            f"• 👨‍🦳 *Father Name:* {d.get('father_name','')}\n"
            f"• 📱 *Mobile Number:* {d.get('mobile','')}\n"
            f"• 🆔 *Aadhar Number:* {d.get('id_number','')}\n"
            f"• 🏠 *Complete Address:* {d.get('address','')}\n"
            f"• 📞 *Alternate Mobile:* {d.get('alt_mobile','')}\n"
            f"• 📍 *Telecom Circle:* {d.get('circle','')}\n"
            f"• 🔢 *User ID:* {d.get('id','')}\n"
            "──────────────────────────────\n"
            "💻 *Bot by ABBAS*\n"
            "📱 Join: @abbas_tech_india"
        )

        return info

    except Exception as e:
        return f"⚠️ Error: {e}"

# ─────────────────────────────────────
# START COMMAND
# ─────────────────────────────────────
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(
        message,
        "👋 Welcome to *Number Info Bot!*\n\n"
        "📱 बस कोई भी *mobile number* भेजो, और मैं उसकी जानकारी निकाल दूँ।\n\n"
        "💻 Powered by ABBAS\n"
        "Join 👉 @abbas_tech_india",
        parse_mode="Markdown"
    )

# ─────────────────────────────────────
# जब user कोई नंबर भेजे
# ─────────────────────────────────────
@bot.message_handler(func=lambda msg: msg.text and msg.text.strip().isdigit())
def handle_number(message):
    number = message.text.strip()
    bot.send_chat_action(message.chat.id, "typing")

    result = get_info(number)
    bot.reply_to(message, result, parse_mode="Markdown")

# ─────────────────────────────────────
# गलत इनपुट हैंडलर
# ─────────────────────────────────────
@bot.message_handler(func=lambda msg: True)
def invalid_input(message):
    bot.reply_to(message, "❗ सिर्फ नंबर भेजो (उदाहरण: 9876543210)")

# ─────────────────────────────────────
# RUN BOT
# ─────────────────────────────────────
print("🤖 Bot is running...")
bot.infinity_polling()
