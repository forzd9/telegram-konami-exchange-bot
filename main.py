# main.py
import asyncio
import logging
import random
import string
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ChatMemberUpdated
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import Config
from database import (init_db, create_deal, get_deal_by_chat, update_deal_status,
                      set_selected_first, add_rating, get_user_stats, set_deal_frozen,
                      save_session_data, delete_deal_sessions, cleanup_old_deals)
from browser_automation import browser_manager

config = Config()
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()
deal_locks = {}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ---------- حالات FSM ----------
class VerificationSteps(StatesGroup):
    # Telegram number verification
    TG_WAIT_NUMBER = State()
    TG_WAIT_OTP = State()
    TG_WAIT_2FA = State()
    TG_WAIT_LOGOUT = State()
    # Konami verification
    KONAMI_WAIT_EMAIL_PASS = State()
    KONAMI_WAIT_OTP = State()
    # Post exchange
    FINAL_EMAIL = State()
    RATING = State()
    SCREENSHOT = State()

# ---------- دوال مساعدة ----------
def generate_deal_number():
    return f"DEAL-{random.randint(1000, 9999)}"

def get_deal_keyboard(deal_id: int, user_id: int = None) -> InlineKeyboardMarkup:
    """أزرار عامة للقروب"""
    builder = InlineKeyboardBuilder()
    builder.button(text="الذهاب للمحادثة الخاصة", url=f"tg://user?id={bot.id}")
    return builder.as_markup()

async def lock_group(chat_id: int):
    """حذف أي رسائل غير البوت وإغلاق المحادثة فعلياً"""
    # لا يمكن قفل الإرسال عبر البوت، نكتفي بحذف الرسائل عبر handler
    pass

async def send_deal_status(deal: dict, text: str):
    """تحديث رسالة الحالة في القروب"""
    chat_id = deal["chat_id"]
    # حذف الرسالة المثبتة القديمة وإرسال جديدة
    try:
        await bot.send_message(chat_id, text, reply_markup=get_deal_keyboard(deal["id"]))
    except Exception as e:
        logger.error(f"Failed to send group message: {e}")

async def perform_draw(deal: dict):
    """القرعة لاختيار الطرف الأول"""
    first = deal["first_user_id"]
    second = deal["second_user_id"]
    chosen = random.choice([first, second])
    await set_selected_first(deal["id"], chosen)
    await update_deal_status(deal["id"], "first_user_verifying")
    username = (await bot.get_chat(chosen)).username or str(chosen)
    await send_deal_status(deal, f"✅ تم اختيار @{username} للبدء.\nيرجى التوجه للمحادثة الخاصة مع البوت لإدخال بيانات المنتج.")

    # إرسال رسالة خاصة للطرف المختار
    try:
        await bot.send_message(
            chosen,
            "أنت الطرف الأول المختار.\nاختر نوع المنتج الذي ستقدمه:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="رقم تيليجرام", callback_data=f"start_verify:tg:{deal['id']}")],
                [InlineKeyboardButton(text="حساب eFootball", callback_data=f"start_verify:konami:{deal['id']}")]
            ])
        )
    except:
        await send_deal_status(deal, "⚠️ لا يمكن إرسال رسالة للطرف المختار، الرجاء فتح الخاص مع البوت.")

async def start_verification_for_user(deal_id: int, user_id: int, product_type: str, state: FSMContext):
    """بدء عملية التحقق بحسب نوع المنتج"""
    await state.update_data(deal_id=deal_id, product_type=product_type)
    if product_type == "tg":
        await bot.send_message(user_id, "أرسل رقم الهاتف الذي تريد استبداله.")
        await state.set_state(VerificationSteps.TG_WAIT_NUMBER)
    elif product_type == "konami":
        await bot.send_message(user_id, "أرسل إيميل وكلمة مرور الحساب بالتنسيق:\nemail:password")
        await state.set_state(VerificationSteps.KONAMI_WAIT_EMAIL_PASS)

# ---------- معالجات الأحداث ----------
@dp.my_chat_member()
async def on_bot_added(event: ChatMemberUpdated):
    """عند إضافة البوت إلى قروب جديد"""
    if event.new_chat_member.status == "administrator":
        chat = event.chat
        if chat.type == "group" or chat.type == "supergroup":
            members_count = await bot.get_chat_member_count(chat.id)
            # يجب أن يكون العدد = 3 (بوت + 2 مستخدمين)
            if members_count == 3:
                admins = await bot.get_chat_administrators(chat.id)
                user_ids = [admin.user.id for admin in admins if not admin.user.is_bot and admin.user.id != bot.id]
                if len(user_ids) == 2:
                    deal_number = generate_deal_number()
                    deal_id = await create_deal(deal_number, chat.id, user_ids[0], user_ids[1])
                    await send_deal_status(
                        {"id": deal_id, "chat_id": chat.id, "first_user_id": user_ids[0], "second_user_id": user_ids[1]},
                        f"🆕 صفقة جديدة: {deal_number}\nجارٍ إجراء القرعة..."
                    )
                    deal = await get_deal_by_chat(chat.id)
                    await perform_draw(deal)
            else:
                await bot.send_message(chat.id, "❌ يجب أن يحتوي القروب على شخصين فقط + البوت.")

@dp.callback_query(lambda c: c.data.startswith("start_verify:"))
async def start_verify(callback: types.CallbackQuery, state: FSMContext):
    """الضغط على زر بدء التحقق (يأتي من الخاص)"""
    _, product, deal_id_str = callback.data.split(":")
    deal_id = int(deal_id_str)
    user_id = callback.from_user.id
    await start_verification_for_user(deal_id, user_id, product, state)
    await callback.answer()

# ---------- سير التحقق لرقم تيليجرام ----------
@dp.message(StateFilter(VerificationSteps.TG_WAIT_NUMBER))
async def tg_number_received(message: types.Message, state: FSMContext):
    phone = message.text.strip()
    await state.update_data(phone=phone)
    await message.answer("جاري إرسال كود التحقق...")
    data = await state.get_data()
    deal_id = data["deal_id"]

    async def ask_otp():
        await message.answer("تم إرسال كود التحقق إلى الرقم. أرسل الكود هنا:")
        await state.set_state(VerificationSteps.TG_WAIT_OTP)
        try:
            msg = await bot.wait_for(
                "message",
                timeout=config.OTP_WAIT_SECONDS,
                filters=lambda m: m.from_user.id == message.from_user.id
            )
            return msg.text
        except:
            await message.answer("⏰ انتهى الوقت، تم إلغاء الصفقة.")
            await update_deal_status(deal_id, "cancelled")
            return None

    async def ask_password():
        await message.answer("الحساب محمي بـ 2FA. أرسل كلمة المرور الثانية:")
        await state.set_state(VerificationSteps.TG_WAIT_2FA)
        try:
            msg = await bot.wait_for("message", timeout=config.OTP_WAIT_SECONDS)
            return msg.text
        except:
            await message.answer("⏰ انتهى الوقت.")
            return None

    async def on_success(page):
        await message.answer("✅ تم تسجيل الدخول بنجاح. تأكد من تسجيل الخروج من جميع الأجهزة ثم اضغط 'تم'.")
        await state.set_state(VerificationSteps.TG_WAIT_LOGOUT)

    try:
        await browser_manager.telegram_login_flow(deal_id, phone, ask_otp, ask_password, on_success)
    except Exception as e:
        await message.answer(f"❌ فشل التحقق: {str(e)}")
        # إعادة المحاولة لاحقاً (يمكن تطويرها)
        return

@dp.message(StateFilter(VerificationSteps.TG_WAIT_LOGOUT))
async def tg_logout_confirm(message: types.Message, state: FSMContext):
    if message.text.strip().lower() != "تم":
        await message.answer("الرجاء كتابة 'تم' بعد تسجيل الخروج.")
        return
    data = await state.get_data()
    deal_id = data["deal_id"]
    # التحقق من الجلسات
    if await browser_manager.verify_logout_devices(deal_id):
        # توليد كلمة مرور جديدة وإيميل جديد
        new_pass = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
        new_email = f"tg-{deal_id}@{config.EMAIL_DOMAIN}"
        # تغيير كلمة المرور
        await browser_manager.change_telegram_password(deal_id, old_password=data.get("password2fa"), new_password=new_pass)
        # تغيير الإيميل (يحتاج OTP)
        changed = await browser_manager.change_recovery_email(deal_id, new_email)
        if changed:
            # حفظ بيانات المنتج الجديد
            await save_session_data(deal_id, session_json="{}", telegram_context=f"phone={data['phone']},pass={new_pass},email={new_email}")
            await message.answer("✅ تم التحقق من الرقم وتأمينه. انتظر حتى ينتهي الطرف الآخر.")
            # تحديث حالة الصفقة (إذا كان الطرفان انتهوا)
            await check_both_verified(deal_id)
        else:
            await message.answer("❌ فشل تغيير الإيميل، سيتم مراجعة الصفقة.")
    else:
        await message.answer("لم يتم تأكيد الخروج، حاول مجدداً.")

# ---------- سير التحقق لحساب كونامي ----------
@dp.message(StateFilter(VerificationSteps.KONAMI_WAIT_EMAIL_PASS))
async def konami_creds_received(message: types.Message, state: FSMContext):
    try:
        email, password = message.text.strip().split(":")
    except:
        await message.answer("صيغة خاطئة. أرسل: email@example.com:password")
        return
    await state.update_data(konami_email=email, konami_pass=password)
    await message.answer("جاري تسجيل الدخول...")
    data = await state.get_data()
    deal_id = data["deal_id"]

    async def ask_otp():
        await message.answer("تم طلب OTP من الموقع. أرسله هنا:")
        await state.set_state(VerificationSteps.KONAMI_WAIT_OTP)
        try:
            msg = await bot.wait_for("message", timeout=config.OTP_WAIT_SECONDS)
            return msg.text
        except:
            await message.answer("⏰ انتهى الوقت.")
            return None

    async def on_success(page):
        new_email = f"konami-{deal_id}@{config.EMAIL_DOMAIN}"
        new_pass = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
        changed = await browser_manager.change_konami_email_password(deal_id, new_email, new_pass)
        if changed:
            await save_session_data(deal_id, session_json="{}", konami_context=f"email={new_email},pass={new_pass}")
            await message.answer("✅ تم التحقق من حساب eFootball. انتظر الطرف الآخر.")
        else:
            await message.answer("❌ فشل تغيير بيانات الحساب.")

    try:
        await browser_manager.konami_login_flow(deal_id, email, password, ask_otp, on_success)
    except Exception as e:
        await message.answer(f"❌ فشل الدخول: {e}")

@dp.message(StateFilter(VerificationSteps.KONAMI_WAIT_OTP))
async def konami_otp_received(message: types.Message, state: FSMContext):
    # سيكمل السير السابق
    pass

# ---------- تحقق الطرفين وتبادل ----------
async def check_both_verified(deal_id: int):
    deal = await get_deal_by_id(deal_id)
    if not deal:
        return
    # التحقق من وجود سياقين في قاعدة البيانات
    from database import get_raw  # افتراض وجود دالة
    # فحص الجدول sessions
    # إذا كلا الطرفين أنجز، يتم التبادل
    # منطق مبسط للعرض
    await finalize_exchange(deal_id)

async def finalize_exchange(deal_id: int):
    deal = await get_deal_by_id(deal_id)
    # جلب بيانات الحسابات الجديدة
    # إرسال لكل طرف بيانات المنتج الذي سيستلمه
    user1 = deal["first_user_id"]
    user2 = deal["second_user_id"]
    # المنتج: من أعطى تيليجرام يستلم كونامي والعكس
    # لتحديد من أعطى ماذا، يجب تخزين نوع المنتج لكل طرف.
    # (يمكن إضافته في جدول deals)
    # هنا للتوضيح نرسل رسائل افتراضية
    await bot.send_message(user1, "🎉 استلم حساب eFootball:\nemail: ... \npassword: ...")
    await bot.send_message(user2, "🎉 استلم رقم تيليجرام:\nphone: ... \npassword: ...")
    await update_deal_status(deal_id, "exchanged")
    # طلب التقييم والسكرينات
    for uid in [user1, user2]:
        await bot.send_message(uid, "الرجاء تقييم الطرف الآخر (1-5 نجوم):", reply_markup=stars_keyboard(deal_id, uid))

def stars_keyboard(deal_id: int, from_user_id: int):
    buttons = []
    for i in range(1, 6):
        buttons.append([InlineKeyboardButton(text="⭐"*i, callback_data=f"rate:{deal_id}:{from_user_id}:{i}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.callback_query(lambda c: c.data.startswith("rate:"))
async def handle_rating(callback: types.CallbackQuery):
    _, deal_id_str, from_uid_str, stars_str = callback.data.split(":")
    deal_id = int(deal_id_str)
    from_uid = int(from_uid_str)
    stars = int(stars_str)
    deal = await get_deal_by_id(deal_id)
    to_uid = deal["first_user_id"] if from_uid == deal["second_user_id"] else deal["second_user_id"]
    await add_rating(deal_id, from_uid, to_uid, stars)
    await callback.message.edit_text("شكراً لتقييمك! أرسل الآن لقطة شاشة للمنتج الذي استلمته.")
    # توجيه لطلب السكرين شوت

# ---------- أوامر الإدارة ----------
@dp.message(Command("freeze"))
async def freeze_deal_cmd(message: types.Message):
    if message.from_user.id not in config.ADMIN_IDS:
        return
    try:
        deal_id = int(message.text.split()[1])
        await set_deal_frozen(deal_id, True)
        await message.reply("تم تجميد الصفقة.")
    except:
        await message.reply("استخدم: /freeze <deal_id>")

# ---------- المجدول ----------
async def scheduled_cleanup():
    await cleanup_old_deals(24)
    logger.info("تم تنظيف الصفقات القديمة.")

# ---------- بدء التشغيل ----------
async def on_startup():
    await init_db()
    await browser_manager.start_browser()
    scheduler.add_job(scheduled_cleanup, "interval", hours=6)
    scheduler.start()
    logger.info("Bot started!")

async def on_shutdown():
    await browser_manager.close_all()
    scheduler.shutdown()

async def main():
    await on_startup()
    await dp.start_polling(bot)
    await on_shutdown()

if __name__ == "__main__":
    asyncio.run(main())