import asyncio
import sys
import os
from dotenv import load_dotenv
from telegram_notifier import send_kyc_notification

# تحميل متغيرات البيئة
load_dotenv()

async def simulate_kyc_approval():
    """
    محاكاة عملية الموافقة على طلب KYC
    """
    if len(sys.argv) < 2:
        print("Usage: python simulate_kyc_approval.py <request_id>")
        print("Example: python simulate_kyc_approval.py KYC-20250228-HB53W05N")
        return
    
    request_id = sys.argv[1]
    registration_code = "11111111"  # رمز تسجيل للاختبار
    
    print(f"محاكاة الموافقة على طلب KYC رقم {request_id}...")
    
    # إرسال إشعار الموافقة مع الأزرار
    success = await send_kyc_notification(request_id, "approved", registration_code)
    
    if success:
        print("✅ تم إرسال إشعار الموافقة بنجاح")
        print("يجب أن تظهر الأزرار في الإشعار الآن")
    else:
        print("❌ فشل في إرسال إشعار الموافقة")

if __name__ == "__main__":
    asyncio.run(simulate_kyc_approval())
