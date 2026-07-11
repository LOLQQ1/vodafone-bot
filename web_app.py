import asyncio
import json
import logging
import os
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

from automation import (
    VodafoneAutomation,
    StepResult,
    SelectorNotFoundError,
    OfferNotFoundError,
    PageLoadError,
)

# تحميل الإعدادات
load_dotenv()
HEADLESS = os.getenv("HEADLESS", "True").lower() == "true"
TIMEOUT = int(os.getenv("SELECTOR_TIMEOUT", "20000"))

app = FastAPI(title="Plus Hamo - Vodafone Automation Web Interface")

# إعداد القوالب
templates = Jinja2Templates(directory="templates")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    """عرض واجهة المستخدم الخاصة بالـ Plus Hamo."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/stream")
async def stream_activation(
    number: str = Query(..., description="رقم الهاتف"),
    password: str = Query(..., description="كلمة المرور")
):
    """
    بث مباشر لخطوات التفعيل خطوة بخطوة باستخدام Server-Sent Events (SSE).
    """
    async def log_generator():
        # مساعد لإرسال اللوج بصيغة SSE
        async def send_log(log_type: str, message: str, status: str = "running"):
            payload = json.dumps({
                "type": log_type,
                "message": message,
                "status": status
            }, ensure_ascii=False)
            yield f"data: {payload}\n\n"
            await asyncio.sleep(0.1)

        yield "retry: 10000\n\n"

        await send_log("info", "🔄 جاري تشغيل المتصفح وتحضير بيئة العمل...")
        
        auto = VodafoneAutomation(headless=HEADLESS, timeout=TIMEOUT)
        
        try:
            await auto.start()
            
            # ── تسجيل الدخول ──
            await send_log("info", f"⏳ جاري محاولة تسجيل الدخول للرقم {number}...")
            try:
                await auto.login(number, password)
                await send_log("success", "✅ تم تسجيل الدخول إلى حساب أنا فودافون بنجاح!")
            except SelectorNotFoundError as e:
                await send_log("error", f"❌ فشل تسجيل الدخول: لم يُعثر على حقل إدخال البيانات.", "error")
                await auto.stop()
                return
            except ValueError as e:
                await send_log("error", f"❌ فشل تسجيل الدخول: {str(e)}", "error")
                await auto.stop()
                return
            except Exception as e:
                await send_log("error", f"❌ فشل تسجيل الدخول: خطأ غير متوقع في الموقع.", "error")
                await auto.stop()
                return

            # ── الخطوة 1: الاشتراك في بلس كومبو 600 ──
            await send_log("info", "⏳ [خطوة 1/5] جاري الاشتراك في باقة بلس كومبو 600 من الموقع...")
            try:
                step1_res = await auto.run_step_1()
                await send_log("success", step1_res.message)
            except Exception as e:
                await send_log("error", f"❌ فشل خطوة 1: {str(e)}", "error")
                await auto.stop()
                return

            # ── الخطوة 2: الاشتراك في عرض 1400 أو ميجابايتس أكتر ──
            await send_log("info", "⏳ [خطوة 2/5] جاري الانتقال لتطبيق الموبايل لتفعيل عرض الخصم...")
            try:
                step2_res = await auto.run_step_2()
                await send_log("success", step2_res.message)
            except Exception as e:
                await send_log("error", f"❌ فشل خطوة 2: {str(e)}", "error")
                await auto.stop()
                return

            # ── الخطوة 3: اشتراك ثانٍ وإعادة شراء ──
            await send_log("info", "⏳ [خطوة 3/5] جاري الرجوع للموقع للاشتراك الثاني وعمل إعادة شراء...")
            try:
                step3_res = await auto.run_step_3()
                await send_log("success", step3_res.message)
            except Exception as e:
                await send_log("error", f"❌ فشل خطوة 3: {str(e)}", "error")
                await auto.stop()
                return

            # ── الخطوة 4: الاشتراك في عرض 19 جنيه ──
            await send_log("info", "⏳ [خطوة 4/5] جاري الانتقال للتطبيق للاشتراك في عرض الـ 19 جنيه...")
            try:
                step4_res = await auto.run_step_4()
                await send_log("success", step4_res.message)
            except Exception as e:
                await send_log("error", f"❌ فشل خطوة 4: {str(e)}", "error")
                await auto.stop()
                return

            # ── الخطوة 5: إعادة شراء نهائية ──
            await send_log("info", "⏳ [خطوة 5/5] جاري تنفيذ إعادة الشراء النهائية لباقة بلس كومبو...")
            try:
                step5_res = await auto.run_step_5()
                await send_log("success", step5_res.message)
            except Exception as e:
                await send_log("error", f"❌ فشل خطوة 5: {str(e)}", "error")
                await auto.stop()
                return

            # ── التحقق النهائي ──
            await send_log("info", "🔎 جاري التحقق النهائي من تفعيل العرض بنجاح...")
            try:
                success, price_label, _ = await auto.run_verification()
                if success:
                    await send_log("success", f"🎉 مبروك! تم تفعيل الطريقة بنجاح. الباقة مفعلة الآن بسعر: {price_label}", "done")
                else:
                    await send_log("info", f"⚠️ التحقق النهائي: {price_label}")
                    await send_log("success", "✅ تم إنهاء كافة الخطوات بنجاح! راجع حسابك للتأكد.", "done")
            except Exception as e:
                await send_log("success", "✅ تم إنهاء جميع الخطوات بنجاح! (فشل التحقق التلقائي ولكن الخطوات تمت).", "done")

            await auto.stop()

        except Exception as e:
            logger.error(f"Error in stream_activation: {e}")
            await send_log("error", f"❌ خطأ غير متوقع أثناء تشغيل السيرفر: {str(e)}", "error")
            try:
                await auto.stop()
            except Exception:
                pass

    return StreamingResponse(log_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    # تشغيل السيرفر على منفذ 5001 لتفادي التعارض مع البوت أو الخدمات الأخرى
    uvicorn.run("web_app:app", host="0.0.0.0", port=5001, reload=True)
