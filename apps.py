import os
import asyncio
import logging
from telethon import TelegramClient, sessions
from telethon.errors import SessionPasswordNeededError
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import pymongo
from datetime import datetime
import time
import sys

# ==================== المتغيرات البيئية ====================
TOKEN = os.environ.get("TOKEN")
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
MONGO_URL = os.environ.get("MONGO_URL")

if not all([TOKEN, API_ID, API_HASH, MONGO_URL]):
    print("⚠️ المتغيرات البيئية ناقصة!")
    sys.exit(1)

API_ID = int(API_ID)

# ==================== اتصال MongoDB ====================
try:
    client_mongo = pymongo.MongoClient(MONGO_URL)
    db = client_mongo["telegram_sessions"]
    collection = db["sessions"]
    print("✅ اتصال MongoDB ناجح")
except Exception as e:
    print(f"❌ فشل اتصال MongoDB: {e}")
    sys.exit(1)

# ==================== إعداد البوت ====================
bot = telebot.TeleBot(TOKEN)
logging.basicConfig(level=logging.INFO)

user_data = {}

# ==================== الأوامر ====================
@bot.message_handler(commands=['start'])
def start(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ موافق وشروط الاستخدام", callback_data="agree"))
    bot.send_message(message.chat.id, 
                     "⚠️ **تحذير:** ملف الجلسة يمنح وصول كامل لحسابك.\n"
                     "لا ترسله لأي شخص.\n\n"
                     "📌 الأوامر المتاحة:\n"
                     "/start - القائمة الرئيسية\n"
                     "/gensession - إنشاء جلسة جديدة\n"
                     "/mysessions - عرض جلساتي المحفوظة\n"
                     "/revoke - حذف جلسة معينة",
                     reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(commands=['gensession'])
def gen_session(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ موافق وشروط الاستخدام", callback_data="agree"))
    bot.send_message(message.chat.id, 
                     "⚠️ **تنبيه أمان:**\n"
                     "سيتم إنشاء جلسة جديدة وحفظها في قاعدة البيانات.\n"
                     "أنت وحدك من يستطيع الوصول إليها.\n\n"
                     "هل توافق؟",
                     reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data == "agree")
def agree(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, 
                          "📱 أرسل رقم هاتفك مع المفتاح الدولي\n"
                          "مثال: `+966501234567`\n\n"
                          "أو اضغط /cancel للإلغاء", 
                          parse_mode='Markdown')
    bot.register_next_step_handler(msg, get_phone)

def get_phone(message):
    if message.text == '/cancel':
        bot.send_message(message.chat.id, "❌ تم الإلغاء.")
        return
    
    phone = message.text.strip()
    chat_id = message.chat.id
    user_data[chat_id] = {'phone': phone}
    
    bot.send_message(chat_id, "⏳ جاري إرسال رمز التحقق...")
    # استخدام asyncio مباشرة
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(send_code(chat_id, phone))
        loop.close()
    except Exception as e:
        bot.send_message(chat_id, f"❌ فشل الإرسال: {str(e)}")

async def send_code(chat_id, phone):
    try:
        client = TelegramClient(sessions.StringSession(), API_ID, API_HASH)
        await client.connect()
        result = await client.send_code_request(phone)
        user_data[chat_id]['client'] = client
        user_data[chat_id]['phone_code_hash'] = result.phone_code_hash
        bot.send_message(chat_id, "🔑 أرسل رمز التحقق (5 أرقام) الذي وصل إليك في Telegram:")
    except Exception as e:
        bot.send_message(chat_id, f"❌ فشل الإرسال: {str(e)}")

@bot.message_handler(func=lambda m: True)
def handle_code(message):
    chat_id = message.chat.id
    if chat_id not in user_data or 'client' not in user_data[chat_id]:
        bot.send_message(chat_id, "❌ ابدأ من جديد بـ /gensession")
        return
    code = message.text.strip()
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(complete_auth(chat_id, code))
        loop.close()
    except Exception as e:
        bot.send_message(chat_id, f"❌ خطأ: {str(e)}")

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
        
        bot.send_message(chat_id, 
                        f"✅ **تم حفظ جلسة جديدة!**\n\n"
                        f"📱 الرقم: `{phone}`\n\n"
                        f"🔑 **جلسة النص (String Session):**\n"
                        f"`{session_string}`\n\n"
                        f"⚠️ احتفظ بها بأمان!\n"
                        f"📋 استرجاعها بـ /mysessions",
                        parse_mode='Markdown')
        del user_data[chat_id]
    except SessionPasswordNeededError:
        bot.send_message(chat_id, "🔐 حسابك مفعل بـ 2FA. أرسل كلمة المرور:")
        user_data[chat_id]['step'] = '2fa'
    except Exception as e:
        bot.send_message(chat_id, f"❌ خطأ: {str(e)}")
        await client.disconnect()

@bot.message_handler(commands=['mysessions'])
def my_sessions(message):
    chat_id = message.chat.id
    sessions_list = list(collection.find({"user_id": chat_id, "is_active": True}))
    if not sessions_list:
        bot.send_message(chat_id, "📭 لا توجد جلسات محفوظة.")
        return
    text = "📋 **جلساتك المحفوظة:**\n\n"
    for i, sess in enumerate(sessions_list, 1):
        text += f"{i}. 📱 {sess['phone']}\n"
        text += f"   🆔 `{sess['_id']}`\n"
        text += f"   📅 {sess['created_at'].strftime('%Y-%m-%d %H:%M')}\n\n"
    bot.send_message(chat_id, text, parse_mode='Markdown')

@bot.message_handler(commands=['revoke'])
def revoke_session(message):
    chat_id = message.chat.id
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(chat_id, "❌ أرسل المعرف المراد حذفه:\n`/revoke 65f3a1b2...`", parse_mode='Markdown')
        return
    session_id = parts[1]
    result = collection.delete_one({"_id": session_id, "user_id": chat_id})
    if result.deleted_count > 0:
        bot.send_message(chat_id, "✅ تم حذف الجلسة بنجاح.")
    else:
        bot.send_message(chat_id, "❌ لم أجد جلسة بهذا المعرف.")

# ==================== تشغيل البوت ====================
if __name__ == "__main__":
    print("🚀 بدء تشغيل البوت...")
    print(f"✅ TOKEN: {TOKEN[:10]}...")
    print(f"✅ API_ID: {API_ID}")
    print(f"✅ API_HASH: {API_HASH[:10]}...")
    print(f"✅ MONGO_URL: {MONGO_URL[:30]}...")
    
    # تشغيل البوت مع إعادة المحاولة
    while True:
        try:
            print("🔄 بدء polling...")
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            print(f"❌ خطأ في polling: {e}")
            print("⏳ إعادة المحاولة خلال 5 ثوان...")
            time.sleep(5)
