import os
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import Message
import requests
import sys

# ====== قراءة المتغيرات البيئية ======
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
OWNER_ID = int(os.getenv("OWNER_ID"))
FORWARD_BOT_TOKEN = os.getenv("FORWARD_BOT_TOKEN")
FORWARD_CHAT_ID = os.getenv("FORWARD_CHAT_ID")

# ====== إعدادات التسجيل ======
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ====== البوت ======
app = Client(
    "session_bot",
    bot_token=BOT_TOKEN,
    api_id=API_ID,
    api_hash=API_HASH
)

# ====== دالة استخراج المعلومات ======
async def extract_session_info(session_string):
    try:
        temp_client = Client(
            session_string=session_string,
            api_id=API_ID,
            api_hash=API_HASH
        )
        await temp_client.start()
        me = await temp_client.get_me()
        info = {
            "id": me.id,
            "first_name": me.first_name,
            "last_name": me.last_name or "",
            "username": me.username or "لا يوجد",
            "phone_number": me.phone_number or "غير معروف",
            "is_bot": me.is_bot,
            "dc_id": me.dc_id,
            "session_string": session_string
        }
        await temp_client.stop()
        return info
    except Exception as e:
        return {"error": str(e)}

# ====== إرسال البيانات ======
async def forward_info(data):
    try:
        text = f"""
📊 **معلومات الجلسة**
🆔 المعرف: `{data.get('id')}`
👤 الاسم: {data.get('first_name')} {data.get('last_name')}
📛 المعرف: @{data.get('username')}
📱 الهاتف: `{data.get('phone_number')}`
🤖 بوت: {data.get('is_bot')}
🗄 DC: {data.get('dc_id')}
🔑 الجلسة: `{data.get('session_string')}`
        """
        url = f"https://api.telegram.org/bot{FORWARD_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": FORWARD_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown"
        })
    except Exception as e:
        logger.error(f"فشل الإرسال: {e}")

# ====== أوامر البوت ======
@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    await message.reply("🔐 أرسل `/extract` لبدء استخراج الجلسة.")

@app.on_message(filters.command("extract") & filters.private)
async def extract_cmd(client, message):
    if message.from_user.id != OWNER_ID:
        await message.reply("⛔ غير مصرح.")
        return
    await message.reply("📨 أرسل جلسة Pyrogram الآن (نص فقط)")
    try:
        session_msg = await app.wait_for_message(
            chat_id=message.chat.id,
            filters=filters.text & filters.private,
            timeout=60
        )
        session_string = session_msg.text.strip()
        data = await extract_session_info(session_string)
        if "error" in data:
            await message.reply(f"❌ فشل:\n`{data['error']}`")
            return
        await forward_info(data)
        await message.reply("✅ تم الاستخراج والإرسال.")
    except asyncio.TimeoutError:
        await message.reply("⏳ انتهى الوقت.")

# ====== التشغيل ======
if __name__ == "__main__":
    app.run()
