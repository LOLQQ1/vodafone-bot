"""
bot.py — بوت تيليجرام لأتمتة خصم فودافون مصر
================================================
• واجهة زراير كاملة (بدون أوامر نصية)
• تسجيل دخول برقم الهاتف + كلمة المرور مباشرة
• تشغيل الخطوات 1→5 تلقائياً بدون تأكيد
• تشخيص سبب العطل بالعربي مع صورة الشاشة
• دعم Webhook للسيرفر + Polling للتطوير
"""

import asyncio
import os
import logging
from datetime import datetime

from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
)
from automation import (
    VodafoneAutomation,
    StepResult,
    SelectorNotFoundError,
    OfferNotFoundError,
)

# ─────────────────────────────────────────────
load_dotenv()

TOKEN          = os.getenv("TELEGRAM_BOT_TOKEN", "")
HEADLESS       = os.getenv("HEADLESS", "True").lower() == "true"
TIMEOUT        = int(os.getenv("SELECTOR_TIMEOUT", "20000"))
WEBHOOK_URL    = os.getenv("WEBHOOK_URL", "")
WEBHOOK_PORT   = int(os.getenv("WEBHOOK_PORT", "8443"))
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
USE_WEBHOOK    = bool(WEBHOOK_URL)

AUTHORIZED_USERS: list[int] = []
for _u in os.getenv("AUTHORIZED_USERS", "").replace(",", " ").split():
    if _u.isdigit():
        AUTHORIZED_USERS.append(int(_u))

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# حالتان للمحادثة: رقم الهاتف ثم كلمة المرور
STATE_PHONE, STATE_PASSWORD = range(2)

active_automations: dict[int, VodafoneAutomation] = {}

# ─────────────────────────────────────────────
# وصف كل خطوة للمستخدم
# ─────────────────────────────────────────────
STEP_INFO = {
    1: ("🖥️", "الموقع",   "الاشتراك في باقة بلس كومبو 600"),
    2: ("📱", "التطبيق",  "الاشتراك في 1400 ميجا بـ28 جنيه (أو ميجابايتس أكتر)"),
    3: ("🖥️", "الموقع",   "اشتراك ثانٍ في بلس كومبو 600 + إعادة شراء"),
    4: ("📱", "التطبيق",  "الاشتراك في 1400 ميجا بـ19 جنيه"),
    5: ("🖥️", "الموقع",   "إعادة شراء نهائية لبلس كومبو 600"),
}

# ─────────────────────────────────────────────
# مساعدات
# ─────────────────────────────────────────────
def is_authorized(update: Update) -> bool:
    u = update.effective_user
    if not u:
        return False
    return not AUTHORIZED_USERS or u.id in AUTHORIZED_USERS

async def check_auth(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    if not is_authorized(update):
        t = update.message or (update.callback_query and update.callback_query.message)
        if t:
            await t.reply_text("⛔️ غير مصرح لك باستخدام هذا البوت.")
        return False
    return True

async def cleanup(chat_id: int):
    a = active_automations.pop(chat_id, None)
    if a:
        try:
            await a.stop()
        except Exception:
            pass

async def send_photo_safe(bot, chat_id: int, path: str,
                          caption: str, markup=None):
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            await bot.send_photo(chat_id=chat_id, photo=f,
                                 caption=caption, reply_markup=markup,
                                 parse_mode="Markdown")
        try:
            os.remove(path)
        except Exception:
            pass
    else:
        await bot.send_message(chat_id=chat_id, text=caption,
                               reply_markup=markup, parse_mode="Markdown")

# ─────────────────────────────────────────────
# لوحات مفاتيح
# ─────────────────────────────────────────────
def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔑 تسجيل الدخول",  callback_data="login"),
            InlineKeyboardButton("📊 الحالة",         callback_data="status"),
        ],
        [
            InlineKeyboardButton("🚀 تشغيل الطريقة", callback_data="run"),
            InlineKeyboardButton("📷 شاشة المتصفح",  callback_data="view"),
        ],
        [
            InlineKeyboardButton("🛑 إيقاف وإغلاق",  callback_data="stop"),
        ],
    ])

def kb_error_recovery(elements: list) -> InlineKeyboardMarkup:
    rows = []
    for el in elements[:10]:
        label = f"[{el['tagName']}] {el['text']}"[:40]
        rows.append([InlineKeyboardButton(label,
                                          callback_data=f"click_{el['index']}")])
    rows.append([
        InlineKeyboardButton("🔄 تحديث الشاشة", callback_data="view"),
        InlineKeyboardButton("🏠 القائمة",       callback_data="menu"),
    ])
    return InlineKeyboardMarkup(rows)

def kb_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="menu")
    ]])

# ─────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update, ctx):
        return
    await update.message.reply_text(
        "👋 *أهلاً! بوت خصم فودافون مصر*\n\n"
        "البوت يطبّق طريقة خصم باقة بلس كومبو 600 تلقائياً.\n"
        "اختر من القائمة:",
        parse_mode="Markdown",
        reply_markup=kb_main(),
    )

# ─────────────────────────────────────────────
# تسجيل الدخول (Conversation)
# ─────────────────────────────────────────────
async def login_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update, ctx):
        return ConversationHandler.END

    target = update.message or update.callback_query.message
    if update.callback_query:
        await update.callback_query.answer()

    await target.reply_text(
        "📱 *تسجيل الدخول*\n\nأرسل رقم هاتف فودافون (11 رقم):",
        parse_mode="Markdown"
    )
    return STATE_PHONE

async def got_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not phone.isdigit() or len(phone) < 11:
        await update.message.reply_text(
            "❌ الرقم غير صحيح. أرسل رقم مكوّن من 11 رقم:"
        )
        return STATE_PHONE

    # حفظ رقم الهاتف مؤقتاً
    ctx.user_data["phone"] = phone
    await update.message.reply_text(
        "🔐 أرسل كلمة المرور الخاصة بحساب أنا فودافون:"
    )
    return STATE_PASSWORD

async def got_password(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    phone    = ctx.user_data.get("phone", "")
    chat_id  = update.effective_chat.id

    if not password:
        await update.message.reply_text("❌ كلمة المرور فارغة. أرسلها مرة أخرى:")
        return STATE_PASSWORD

    # حذف رسالة كلمة المرور فوراً للحماية
    try:
        await update.message.delete()
    except Exception:
        pass

    msg = await ctx.bot.send_message(
        chat_id,
        f"⏳ جاري تسجيل الدخول برقم {phone}...\nيرجى الانتظار."
    )

    try:
        auto = VodafoneAutomation(headless=HEADLESS, timeout=TIMEOUT)
        await auto.start()
        active_automations[chat_id] = auto
        ss = await auto.login(phone, password)
        await msg.delete()
        await send_photo_safe(
            ctx.bot, chat_id, ss,
            "🎉 *تم تسجيل الدخول بنجاح!*\n\nاضغط **🚀 تشغيل الطريقة** للبدء.",
            kb_main(),
        )
        await auto.stop()
        active_automations.pop(chat_id, None)
    except SelectorNotFoundError as e:
        await msg.delete()
        await send_photo_safe(
            ctx.bot, chat_id, e.screenshot_path,
            f"❌ *فشل تسجيل الدخول*\n\n📌 السبب: {e.args[0]}\n\n"
            "اضغط على أحد الأزرار أو عد للقائمة:",
            kb_error_recovery(e.interactive_elements),
        )
        await cleanup(chat_id)
    except ValueError as e:
        await msg.delete()
        await ctx.bot.send_message(
            chat_id,
            f"❌ *{e}*\n\nتأكد من رقم الهاتف وكلمة المرور وحاول مرة أخرى.",
            parse_mode="Markdown",
            reply_markup=kb_main(),
        )
        await cleanup(chat_id)
    except Exception as e:
        await msg.delete()
        await ctx.bot.send_message(
            chat_id,
            f"❌ خطأ غير متوقع: {type(e).__name__}: {e}",
            reply_markup=kb_main(),
        )
        await cleanup(chat_id)
    return ConversationHandler.END

async def cancel_conv(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cleanup(update.effective_chat.id)
    await update.message.reply_text("🚫 تم الإلغاء.", reply_markup=kb_main())
    return ConversationHandler.END

# ─────────────────────────────────────────────
# تشغيل الطريقة — كل الخطوات تلقائياً
# ─────────────────────────────────────────────
async def run_workflow(chat_id: int, ctx: ContextTypes.DEFAULT_TYPE):
    """يشغّل الخطوات 1→5 كاملة بدون توقف."""

    if not os.path.exists("auth_state.json"):
        await ctx.bot.send_message(
            chat_id,
            "⚠️ لا توجد جلسة محفوظة.\nاضغط **🔑 تسجيل الدخول** أولاً.",
            parse_mode="Markdown",
            reply_markup=kb_main(),
        )
        return

    # رسالة بداية
    header = await ctx.bot.send_message(
        chat_id,
        "🚀 *جاري تشغيل الطريقة...*\n\n"
        "سيتم تنفيذ الخطوات الخمس تلقائياً وستصلك تحديثات لحظية.",
        parse_mode="Markdown",
    )

    # فتح المتصفح
    auto = VodafoneAutomation(headless=HEADLESS, timeout=TIMEOUT)
    active_automations[chat_id] = auto

    try:
        await auto.start()
    except Exception as e:
        await header.edit_text(f"❌ فشل فتح المتصفح: {e}")
        await cleanup(chat_id)
        return

    # ── Callback يُرسَل مع كل خطوة ──
    async def on_step(result: StepResult):
        icon, where, desc = STEP_INFO.get(int(str(result.step)[-1]), ("", "", ""))

        if result.success:
            caption = (
                f"{icon} *الخطوة {result.step} — {where}*\n"
                f"📍 {desc}\n\n"
                f"{result.message}"
            )
            if result.offer_used:
                caption += f"\n🎁 العرض المُستخدَم: *{result.offer_used}*"

            await send_photo_safe(
                ctx.bot, chat_id, result.screenshot, caption
            )
        else:
            caption = (
                f"⛔ *الخطوة {result.step} — {where}*\n"
                f"📍 {desc}\n\n"
                f"{result.message}"
            )
            markup = None
            if result.interactive_elements:
                markup = kb_error_recovery(result.interactive_elements)
            else:
                markup = kb_main()

            await send_photo_safe(
                ctx.bot, chat_id, result.screenshot, caption, markup
            )

    # ── تنفيذ الخطوات ──
    results = await auto.run_full_workflow(progress_callback=on_step)

    # ── التحقق النهائي ──
    last = results[-1] if results else None
    all_ok = last and last.success and last.step == 5

    if all_ok:
        await ctx.bot.send_message(
            chat_id,
            "🔎 *التحقق النهائي...*",
            parse_mode="Markdown",
        )
        try:
            success, price, ss = await auto.run_verification()
            if success:
                caption = (
                    "🎉 *مبروك! نجحت الطريقة!*\n\n"
                    f"باقة بلس كومبو 600 ستتفعل بسعر *{price}*\n"
                    "💰 اشحن المبلغ وسيبها تتفعل تلقائياً ✅"
                )
            else:
                caption = (
                    "⚠️ *انتهت الخطوات*\n\n"
                    f"الحالة الحالية: {price}\n"
                    "راجع الصورة وتأكد يدوياً."
                )
            await send_photo_safe(ctx.bot, chat_id, ss, caption, kb_main())
        except Exception as e:
            await ctx.bot.send_message(
                chat_id,
                f"⚠️ فشل التحقق النهائي: {e}",
                reply_markup=kb_main(),
            )
    else:
        await ctx.bot.send_message(
            chat_id,
            "⛔ *توقفت الطريقة بسبب خطأ في إحدى الخطوات.*\n\n"
            "إذا كان الخطأ بسبب عنصر مفقود، يمكنك النقر عليه يدوياً من الصورة أعلاه.",
            parse_mode="Markdown",
            reply_markup=kb_main(),
        )

    await cleanup(chat_id)

# ─────────────────────────────────────────────
# معالج زراير الـ Inline Keyboard
# ─────────────────────────────────────────────
async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_authorized(update):
        await q.message.reply_text("⛔️ غير مصرح.")
        return

    chat_id = q.message.chat_id
    data    = q.data

    # ── القائمة الرئيسية ──────────────────────
    if data == "menu":
        await q.edit_message_text(
            "🏠 *القائمة الرئيسية*\nاختر ما تريد:",
            parse_mode="Markdown",
            reply_markup=kb_main(),
        )

    # ── تسجيل الدخول ──────────────────────────
    elif data == "login":
        await login_start(update, ctx)

    # ── الحالة ────────────────────────────────
    elif data == "status":
        running       = chat_id in active_automations
        session_saved = os.path.exists("auth_state.json")
        txt = (
            "📊 *حالة النظام*\n\n"
            f"🌐 المتصفح: {'🟢 يعمل' if running else '🔴 مغلق'}\n"
            f"🔑 الجلسة:  {'🟢 محفوظة' if session_saved else '🔴 غير موجودة'}\n"
            f"🖥️ الوضع:   {'مخفي' if HEADLESS else 'ظاهر'}\n"
            f"🌍 السيرفر: {'Webhook' if USE_WEBHOOK else 'Polling محلي'}"
        )
        await q.edit_message_text(txt, parse_mode="Markdown",
                                  reply_markup=kb_main())

    # ── تشغيل الطريقة ─────────────────────────
    elif data == "run":
        await q.edit_message_text(
            "⏳ *جاري التهيئة وبدء الطريقة...*",
            parse_mode="Markdown",
        )
        asyncio.create_task(run_workflow(chat_id, ctx))

    # ── لقطة شاشة ─────────────────────────────
    elif data == "view":
        auto = active_automations.get(chat_id)
        if not auto:
            await q.edit_message_text(
                "❌ لا يوجد متصفح نشط الآن.",
                reply_markup=kb_main(),
            )
            return
        els = await auto.get_interactive_elements()
        ss  = await auto.get_screenshot()
        await send_photo_safe(
            ctx.bot, chat_id, ss,
            f"📷 الشاشة الحالية\n🔗 `{auto.page.url}`",
            kb_error_recovery(els),
        )

    # ── إيقاف ─────────────────────────────────
    elif data == "stop":
        await cleanup(chat_id)
        await q.edit_message_text(
            "🛑 تم إيقاف كل العمليات وإغلاق المتصفح.",
            reply_markup=kb_main(),
        )

    # ── نقر على عنصر ──────────────────────────
    elif data.startswith("click_"):
        auto = active_automations.get(chat_id)
        if not auto:
            await q.message.reply_text("❌ لا يوجد متصفح نشط.")
            return
        idx = int(data.split("_", 1)[1])
        try:
            await auto.click_element_by_index(idx)
            await asyncio.sleep(1.5)
            els = await auto.get_interactive_elements()
            ss  = await auto.get_screenshot()
            await send_photo_safe(
                ctx.bot, chat_id, ss,
                f"✅ تم النقر\n🔗 `{auto.page.url}`",
                kb_error_recovery(els),
            )
        except Exception as e:
            await q.message.reply_text(f"❌ فشل النقر: {e}",
                                       reply_markup=kb_main())

# ─────────────────────────────────────────────
# رسائل نصية → تُكتب في المتصفح
# ─────────────────────────────────────────────
async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    chat_id = update.effective_chat.id
    auto = active_automations.get(chat_id)
    if not auto:
        await update.message.reply_text(
            "💡 لا يوجد متصفح نشط. استخدم القائمة:",
            reply_markup=kb_main(),
        )
        return
    text = update.message.text.strip()
    try:
        await auto.type_in_focused(text)
        await asyncio.sleep(0.8)
        ss = await auto.get_screenshot()
        await send_photo_safe(
            ctx.bot, chat_id, ss,
            f"✍️ تم كتابة: `{text}`",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 تحديث", callback_data="view"),
                InlineKeyboardButton("🏠 القائمة", callback_data="menu"),
            ]]),
        )
    except Exception as e:
        await update.message.reply_text(f"❌ فشل الكتابة: {e}",
                                        reply_markup=kb_main())

# ─────────────────────────────────────────────
# تشغيل
# ─────────────────────────────────────────────
def main():
    if not TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN غير موجود في ملف .env")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    # محادثة تسجيل الدخول
    login_conv = ConversationHandler(
        entry_points=[
            CommandHandler("login", login_start),
            CallbackQueryHandler(login_start, pattern="^login$"),
        ],
        states={
            STATE_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_phone)],
            STATE_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_password)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(login_conv)
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    async def set_cmds(application):
        await application.bot.set_my_commands([
            BotCommand("start",  "القائمة الرئيسية"),
            BotCommand("login",  "تسجيل الدخول"),
            BotCommand("cancel", "إلغاء العملية"),
        ])

    app.post_init = set_cmds

    if USE_WEBHOOK:
        logger.info("🌐 Webhook على %s:%s", WEBHOOK_URL, WEBHOOK_PORT)
        app.run_webhook(
            listen="0.0.0.0",
            port=WEBHOOK_PORT,
            webhook_url=f"{WEBHOOK_URL}/webhook",
            url_path="/webhook",
            secret_token=WEBHOOK_SECRET or None,
            drop_pending_updates=True,
        )
    else:
        logger.info("🔄 Polling...")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
