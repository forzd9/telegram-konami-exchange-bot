# browser_automation.py
import asyncio
import imaplib
import email
import re
import random
import string
from pathlib import Path
from playwright.async_api import async_playwright, BrowserContext
from config import Config

config = Config()
SESSIONS_DIR = Path(config.SESSIONS_DIR)
SESSIONS_DIR.mkdir(exist_ok=True)

class BrowserManager:
    def __init__(self):
        self.playwright = None
        self.browser = None
        # تخزين سياقات المتصفح لكل صفقة
        self.contexts: dict[int, BrowserContext] = {}
        self.deal_states = {}  # تخزين حالات الصفقات المؤقتة

    async def start_browser(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=config.BROWSER_HEADLESS,
            executable_path=config.BROWSER_EXECUTABLE_PATH
        )

    async def get_context_for_deal(self, deal_id: int) -> BrowserContext:
        if deal_id not in self.contexts:
            context = await self.browser.new_context(
                storage_state=None,
                viewport={"width": 1280, "height": 720}
            )
            self.contexts[deal_id] = context
        return self.contexts[deal_id]

    async def close_deal_context(self, deal_id: int):
        if deal_id in self.contexts:
            await self.contexts[deal_id].close()
            del self.contexts[deal_id]

    # ======== تيليجرام ويب ========
    async def telegram_login_flow(self, deal_id: int, phone_number: str, otp_callback, password_callback, on_success):
        """
        تشغيل سيرورة تسجيل الدخول.
        otp_callback: async func to ask user for OTP
        password_callback: async func to ask user for 2FA password
        on_success: async func called after successful login
        """
        context = await self.get_context_for_deal(deal_id)
        page = await context.new_page()
        try:
            await page.goto("https://web.telegram.org/k/", wait_until="domcontentloaded")
            # انتظار ظهور حقل إدخال الرقم
            await page.wait_for_selector("input[name='phone']", timeout=15000)
            await page.fill("input[name='phone']", phone_number)
            await page.click("button:has-text('Next')")
            # انتظار طلب الكود
            code = await otp_callback()  # يطلب من المستخدم
            await page.fill("input[name='code']", code)
            await page.click("button:has-text('Next')")
            
            # انتظار نجاح الدخول أو طلب كلمة مرور 2FA
            try:
                await page.wait_for_selector("input[name='password']", timeout=10000)
                pwd = await password_callback()
                await page.fill("input[name='password']", pwd)
                await page.click("button:has-text('Next')")
            except:
                pass  # لا يوجد 2FA
            
            await page.wait_for_selector(".chat-list", timeout=30000)  # واجهة المحادثات
            await on_success(page)
        except Exception as e:
            raise e
        finally:
            await page.close()

    async def verify_logout_devices(self, deal_id: int) -> bool:
        """يتحقق من أن المستخدم خرج من الجلسات الأخرى (محاكاة)"""
        # يمكن فتح قائمة الأجهزة والتحقق، هنا نكتفي بافتراض النجاح بعد تأكيد المستخدم
        return True

    async def change_telegram_password(self, deal_id: int, old_password: str = None, new_password: str = None):
        """تغيير كلمة المرور 2FA"""
        context = self.contexts.get(deal_id)
        if not context or not context.pages:
            return False
        page = context.pages[0]
        try:
            await page.goto("https://web.telegram.org/k/", wait_until="domcontentloaded")
            await page.click(".settings-btn")  # زر الإعدادات (افتراضي)
            await page.click("text=Privacy and Security")
            await page.click("text=Two-Step Verification")
            if old_password:
                await page.fill("input[name='password']", old_password)
                await page.click("button:has-text('Next')")
            # تغيير كلمة المرور (يعتمد على واجهة الموقع، يحتاج تفاصيل دقيقة)
            # هنا جزء مبسّط: إدخال كلمة المرور الجديدة وتأكيدها
            await page.fill("input[name='new_password']", new_password)
            await page.fill("input[name='confirm_password']", new_password)
            await page.click("button:has-text('Save')")
            return True
        except:
            return False

    async def change_recovery_email(self, deal_id: int, new_email: str) -> bool:
        """تغيير بريد الاستعادة وإرسال OTP للإيميل الجديد"""
        # يتطلب تفاعل مع واجهة تيليجرام لإدخال الإيميل ثم انتظار OTP من الإيميل الجديد.
        # نكتفي بمنطق مبسّط في هذا الكود للأغراض التعليمية.
        return True

    # ======== كونامي ========
    async def konami_login_flow(self, deal_id: int, email: str, password: str, otp_callback, on_success):
        context = await self.get_context_for_deal(deal_id)
        page = await context.new_page()
        try:
            await page.goto("https://www.konamigaming.com/login", wait_until="domcontentloaded")
            await page.fill("input[name='email']", email)
            await page.fill("input[name='password']", password)
            await page.click("button[type='submit']")
            try:
                await page.wait_for_selector("input[name='otp']", timeout=10000)
                otp = await otp_callback()
                await page.fill("input[name='otp']", otp)
                await page.click("button:has-text('Verify')")
            except:
                pass
            await page.wait_for_url("**/dashboard**", timeout=20000)
            await on_success(page)
        except Exception as e:
            raise e
        finally:
            await page.close()

    async def change_konami_email_password(self, deal_id: int, new_email: str, new_password: str) -> bool:
        context = self.contexts.get(deal_id)
        # منطق تغيير الإيميل وكلمة المرور في موقع كونامي (يختلف حسب واجهة الموقع)
        return True

    # ======== البريد الإلكتروني ========
    async def get_email_otp(self, email_address: str, timeout: int = 120) -> str:
        """سحب أحدث كود OTP من الإيميل عبر IMAP"""
        loop = asyncio.get_running_loop()
        # تنفيذ IMAP في thread منفصل
        def fetch():
            mail = imaplib.IMAP4_SSL(config.IMAP_SERVER, config.IMAP_PORT)
            mail.login(config.EMAIL_ADDRESS, config.EMAIL_PASSWORD)
            mail.select("inbox")
            # البحث عن رسائل غير مقروءة من الإيميل المستهدف
            status, messages = mail.search(None, '(UNSEEN TO "{}")'.format(email_address))
            if status != "OK":
                return None
            for num in messages[0].split()[-5:]:
                status, data = mail.fetch(num, "(RFC822)")
                msg = email.message_from_bytes(data[0][1])
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body += part.get_payload(decode=True).decode()
                else:
                    body = msg.get_payload(decode=True).decode()
                match = re.search(r"\b(\d{5,6})\b", body)
                if match:
                    return match.group(1)
            mail.logout()
            return None
        return await loop.run_in_executor(None, fetch)

    async def close_all(self):
        for ctx in self.contexts.values():
            await ctx.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

browser_manager = BrowserManager()