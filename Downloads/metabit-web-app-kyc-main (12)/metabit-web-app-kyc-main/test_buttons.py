import asyncio
import os
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram_notifier import send_telegram_message

# تحميل متغيرات البيئة
load_dotenv()

async def test_buttons():
    """
    اختبار إرسال إشعار مع أزرار
    """
    # الحصول على معرف المجموعة من متغيرات البيئة
    admin_group_id = os.getenv('ADMIN_GROUP_ID')
    
    if not admin_group_id:
        print("❌ لم يتم العثور على معرف المجموعة في متغيرات البيئة")
        return
    
    # إنشاء رسالة الاختبار
    message = """
🧪 *اختبار الأزرار* 🧪

هذه رسالة اختبار للتحقق من عمل الأزرار بشكل صحيح بعد الإصلاح.

انقر على أحد الأزرار أدناه للانتقال إلى البوت المطلوب.
    """
    
    # إنشاء أزرار للانتقال إلى بوت الإيداع وبوت السحب
    keyboard = [
        [
            InlineKeyboardButton("بوت الإيداع 💰", url="https://t.me/MetaBit_Trx_Bot"),
            InlineKeyboardButton("بوت السحب 💸", url="https://t.me/MetaBit_Withdrawal_Bot")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    print(f"محاولة إرسال إشعار اختبار إلى المجموعة {admin_group_id}...")
    
    # إرسال الإشعار مع الأزرار
    success = await send_telegram_message(admin_group_id, message, parse_mode="Markdown", reply_markup=reply_markup)
    
    if success:
        print("✅ تم إرسال الإشعار بنجاح")
    else:
        print("❌ فشل في إرسال الإشعار")

if __name__ == "__main__":
    asyncio.run(test_buttons())
