async def send_code(chat_id, phone):
    try:
        # إنشاء عميل Telethon مع تحديد session_string فارغ
        client = TelegramClient(sessions.StringSession(), API_ID, API_HASH)
        
        # الاتصال بالخادم
        await client.connect()
        
        # طلب رمز التحقق
        result = await client.send_code_request(phone)
        
        # حفظ بيانات العميل ورقم الهاتف
        user_data[chat_id]['client'] = client
        user_data[chat_id]['phone'] = phone
        user_data[chat_id]['phone_code_hash'] = result.phone_code_hash
        
        bot.send_message(chat_id, "🔑 أرسل رمز التحقق (5 أرقام) الذي وصل إليك في Telegram:")
        
    except Exception as e:
        bot.send_message(chat_id, f"❌ فشل الإرسال: {str(e)}")
