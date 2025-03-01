import asyncio
import os
import sys
from dotenv import load_dotenv
from telegram_notifier import send_kyc_notification

# تحميل متغيرات البيئة
load_dotenv()

async def test_kyc_approval():
    """
    اختبار إرسال إشعار موافقة KYC مع أزرار
    """
    if len(sys.argv) < 2:
        print("Usage: python test_kyc_notification.py <request_id>")
        return
    
    request_id = sys.argv[1]
    registration_code = "11111111"  # رمز تسجيل للاختبار
    
    print(f"محاولة إرسال إشعار موافقة KYC للطلب {request_id}...")
    
    # إرسال إشعار الموافقة
    success = await send_kyc_notification(request_id, "approved", registration_code)
    
    if success:
        print("✅ تم إرسال إشعار الموافقة بنجاح")
    else:
        print("❌ فشل في إرسال إشعار الموافقة")

if __name__ == "__main__":
    asyncio.run(test_kyc_approval())
