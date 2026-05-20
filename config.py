# config.py
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Config:
    # البوت
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "8776142375:AAErhtwLyTJpTeR-TaokDoNoGn07iUM-f1I")
    
    # مالك المشروع (يمكن إضافة أكثر من ID)
    ADMIN_IDS: list[int] = [6891530912]  # استبدل بـ ID الخاص بصاحب المشروع
    
    # قناة النشر التلقائي
    CHANNEL_ID: int = -1002514428576   # استبدل بـ ID القناة
    
    # قاعدة البيانات
    DB_PATH: str = "deals.db"
    
    # إعدادات الوقت
    DEAL_TIMEOUT_MINUTES: int = 60
    OTP_WAIT_SECONDS: int = 300
    USER_RESPONSE_WAIT: int = 1800     # 30 دقيقة لانتظار رد المستخدم
    
    # إعدادات الإيميل الخاص بمالك المشروع (استقبال أكواد OTP)
    EMAIL_DOMAIN: str = "gmail.com"
IMAP_SERVER: str = "imap.gmail.com"
IMAP_PORT: int = 993
EMAIL_ADDRESS: str = "scalosteoget@gmail.com"
EMAIL_PASSWORD: str = "momo momo 123"
    
    # Playwright
    BROWSER_HEADLESS: bool = True
    BROWSER_EXECUTABLE_PATH: str | None = None  # اترك None للاستخدام الافتراضي
    
    # مسار تخزين الجلسات
    SESSIONS_DIR: str = "browser_sessions"
    
    # مفاتيح تشفير (إن وجدت) – يمكن استخدام cryptography لتشفير الجلسات
    ENCRYPTION_KEY: str = "your-fernet-key-if-needed"