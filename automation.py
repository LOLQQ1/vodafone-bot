"""
automation.py — محرك Playwright لأتمتة أنا فودافون
=======================================================
يدعم:
  - سياق Desktop (الموقع) + Mobile (التطبيق)
  - تبديل سلس بين الوضعين مع حفظ الجلسة
  - تشخيص أسباب العطل بالعربي
  - run_full_workflow() — يشغّل الخطوات 1→5 بالكامل مع Callback للتقدم
"""

import asyncio
import os
import logging
from dataclasses import dataclass, field
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# أخطاء مخصصة
# ─────────────────────────────────────────────
class OfferNotFoundError(Exception):
    """العرض غير موجود على الخط."""

class SelectorNotFoundError(Exception):
    """عنصر في الصفحة لم يُعثَر عليه."""
    def __init__(self, message, screenshot_path="", interactive_elements=None):
        super().__init__(message)
        self.screenshot_path = screenshot_path
        self.interactive_elements = interactive_elements or []

class SessionExpiredError(Exception):
    """الجلسة منتهية — يلزم تسجيل الدخول من جديد."""

class PageLoadError(Exception):
    """الصفحة لم تُحمَّل."""


# ─────────────────────────────────────────────
# نتيجة كل خطوة
# ─────────────────────────────────────────────
@dataclass
class StepResult:
    step: int
    success: bool
    message: str                       # رسالة بالعربي
    screenshot: str = ""               # مسار الصورة
    offer_used: str = ""               # العرض المُستخدَم (للخطوة 2)
    interactive_elements: list = field(default_factory=list)


# ─────────────────────────────────────────────
# محرك الأتمتة
# ─────────────────────────────────────────────
class VodafoneAutomation:

    def __init__(self, headless: bool = True, timeout: int = 15000,
                 state_file: str = "auth_state.json"):
        self.headless   = headless
        self.timeout    = timeout
        self.state_file = state_file
        self.base_url   = os.getenv(
            "VODAFONE_BASE_URL", "https://web.vodafone.com.eg"
        ).rstrip("/")

        self.playwright = None
        self.browser    = None
        self.context    = None
        self.page       = None
        self.is_mobile  = False

    # ── دورة حياة المتصفح ───────────────────────

    async def start(self):
        if not self.playwright:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled",
                      "--no-sandbox"],
            )
            await self._create_context(is_mobile=False)

    async def stop(self):
        for attr in ("context", "browser", "playwright"):
            obj = getattr(self, attr, None)
            if obj:
                try:
                    await obj.close() if attr != "playwright" else await obj.stop()
                except Exception:
                    pass
                setattr(self, attr, None)

    async def _create_context(self, is_mobile: bool = False):
        if self.context:
            try:
                await self.context.storage_state(path=self.state_file)
            except Exception:
                pass
            await self.context.close()

        storage = self.state_file if os.path.exists(self.state_file) else None

        if is_mobile:
            device = self.playwright.devices["Pixel 5"]
            self.context = await self.browser.new_context(
                **device, storage_state=storage,
                locale="ar-EG", timezone_id="Africa/Cairo",
            )
        else:
            self.context = await self.browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                storage_state=storage,
                locale="ar-EG", timezone_id="Africa/Cairo",
            )

        self.is_mobile = is_mobile
        self.page = await self.context.new_page()
        self.page.set_default_timeout(self.timeout)
        logger.info("Context → %s", "Mobile" if is_mobile else "Desktop")

    async def switch_context(self, to_mobile: bool):
        if self.is_mobile != to_mobile:
            await _create_context := self._create_context
            await _create_context(is_mobile=to_mobile)

    async def save_state(self):
        if self.context:
            await self.context.storage_state(path=self.state_file)

    # ── مساعدات التفاعل ─────────────────────────

    async def _goto(self, path: str, wait: float = 3.0):
        """ينتقل لصفحة ويتحقق من التحميل."""
        url = f"{self.base_url}{path}"
        try:
            await self.page.goto(url, wait_until="domcontentloaded",
                                 timeout=self.timeout)
            await asyncio.sleep(wait)
        except PlaywrightTimeoutError:
            ss = await self._screenshot("load_error")
            raise PageLoadError(f"فشل تحميل الصفحة: {url}")

    async def _click_text(self, text: str, timeout: int = None,
                          context_label: str = "") -> bool:
        """ينقر على عنصر يحتوي النص — يرجع False لو ما وُجد."""
        t = timeout or self.timeout
        try:
            loc = self.page.get_by_text(text, exact=False).first
            await loc.wait_for(state="visible", timeout=t)
            await loc.click()
            return True
        except PlaywrightTimeoutError:
            return False

    async def _click_text_or_raise(self, text: str, error_msg: str,
                                   timeout: int = None):
        """ينقر أو يرفع SelectorNotFoundError."""
        if not await self._click_text(text, timeout=timeout):
            ss = await self._screenshot("not_found")
            elements = await self.get_interactive_elements()
            raise SelectorNotFoundError(error_msg, ss, elements)

    async def _screenshot(self, name: str = "shot") -> str:
        path = f"{name}_{int(asyncio.get_event_loop().time())}.png"
        try:
            await self.page.screenshot(path=path, full_page=False)
        except Exception:
            pass
        return path

    async def get_screenshot(self, path: str = "screenshot.png") -> str:
        await self.page.screenshot(path=path)
        return path

    async def get_interactive_elements(self) -> list:
        try:
            return await self.page.evaluate("""() => {
                const sel = 'button,a,input,select,textarea,[role="button"],[onclick]';
                return [...document.querySelectorAll(sel)]
                    .map((el, i) => {
                        const r = el.getBoundingClientRect();
                        if (r.width === 0 || r.height === 0) return null;
                        let t = (el.innerText || el.placeholder ||
                                 el.getAttribute('aria-label') || '').trim()
                                 .replace(/\s+/g,' ').substring(0,50);
                        if (!t && el.tagName==='INPUT')
                            t = `Input[${el.type}] ${el.name||el.id||''}`;
                        return t ? {index:i, tagName:el.tagName, text:t} : null;
                    }).filter(Boolean);
            }""")
        except Exception:
            return []

    async def click_element_by_index(self, index: int):
        await self.page.evaluate("""(i) => {
            const el = document.querySelectorAll(
                'button,a,input,select,textarea,[role="button"],[onclick]'
            )[i];
            if (el) { el.scrollIntoView({block:'center'}); el.click(); }
        }""", index)
        await asyncio.sleep(1.2)

    async def type_in_focused(self, text: str):
        await self.page.keyboard.insert_text(text)
        await asyncio.sleep(0.5)

    # ── تسجيل الدخول ────────────────────────────

    async def go_to_login(self, phone: str) -> str:
        """يفتح صفحة الدخول ويدخل رقم الهاتف — يرجع مسار سكرين شوت."""
        if self.is_mobile:
            await self._create_context(is_mobile=False)

        await self._goto("/ar/home", wait=3)

        # 1. إغلاق أو قبول الكوكيز إذا ظهرت
        for cookie_btn in ["قبول كل الملفات", "قبول", "Accept All", "reject", "رفض"]:
            try:
                if await self._click_text(cookie_btn, timeout=2000):
                    await asyncio.sleep(1)
                    break
            except Exception:
                pass

        # 2. الضغط على أيقونة الحساب (شكل الشخص أعلى اليسار) أو كلمة دخول
        # سنجرب الضغط على أيقونة الشخص عبر الكلاس أو الرول أو النص
        profile_clicked = False
        profile_selectors = [
            ".profile-icon", "a.login-btn", "a[href*='login']",
            "header i.icon-user", "header .user-icon", ".nav-link:has-text('دخول')",
            "header a:has-text('دخول')"
        ]
        
        # جرب الضغط بالنص أولاً
        if await self._click_text("دخول", timeout=3000):
            profile_clicked = True
            await asyncio.sleep(1.5)
            
        if not profile_clicked:
            for selector in profile_selectors:
                try:
                    loc = self.page.locator(selector).first
                    if await loc.is_visible(timeout=1500):
                        await loc.click()
                        profile_clicked = True
                        await asyncio.sleep(2)
                        break
                except Exception:
                    pass

        # لو لم يفلح أي مما سبق، سنضغط على الأيقونة بناء على إحداثياتها أو ننتقل لصفحة الدخول مباشرة
        if not profile_clicked:
            try:
                # محاولة الانتقال لصفحة تسجيل الدخول مباشرة بالرابط
                await self.page.goto(f"{self.base_url}/ar/home?login=true", timeout=8000)
                await asyncio.sleep(2)
            except Exception:
                pass

        # حقل الهاتف
        phone_sel = ("input[name='username'],input#username,"
                     "input#mobileNum,input[placeholder*='رقم'],"
                     "input[type='tel']")
        try:
            await self.page.wait_for_selector(phone_sel, timeout=10000)
            await self.page.fill(phone_sel, phone)
        except PlaywrightTimeoutError:
            raise SelectorNotFoundError(
                "لم يُعثَر على حقل رقم الهاتف في صفحة تسجيل الدخول",
                await self._screenshot("login_field"),
                await self.get_interactive_elements(),
            )

        # زر إرسال OTP
        otp_btn = ("button[type='submit'],"
                   "button:has-text('كلمة المرور المؤقتة'),"
                   "button:has-text('أرسل الكود'),"
                   "button:has-text('دخول')")
        try:
            await self.page.wait_for_selector(otp_btn, timeout=6000)
            await self.page.click(otp_btn)
        except PlaywrightTimeoutError:
            raise SelectorNotFoundError(
                "لم يُعثَر على زر طلب كود التحقق",
                await self._screenshot("otp_btn"),
                await self.get_interactive_elements(),
            )

        await asyncio.sleep(2)
        return await self._screenshot("after_phone")

    async def submit_otp(self, otp: str) -> str:
        otp_sel = ("input#otp,input[name='otp'],"
                   "input[placeholder*='رمز'],input[placeholder*='كود'],"
                   "input[type='number'][maxlength]")
        try:
            await self.page.wait_for_selector(otp_sel, timeout=10000)
            await self.page.fill(otp_sel, otp)
        except PlaywrightTimeoutError:
            raise SelectorNotFoundError(
                "لم يُعثَر على حقل إدخال كود التحقق",
                await self._screenshot("otp_field"),
                await self.get_interactive_elements(),
            )

        submit = ("button[type='submit'],"
                  "button:has-text('تأكيد'),"
                  "button:has-text('دخول')")
        try:
            await self.page.wait_for_selector(submit, timeout=5000)
            await self.page.click(submit)
        except PlaywrightTimeoutError:
            pass  # قد تكون النموذج تلقائي

        await asyncio.sleep(5)

        # تحقق من وجود خطأ في الصفحة
        content = await self.page.content()
        if "خطأ" in content or "غير صحيح" in content or "error" in content.lower():
            raise ValueError("كود التحقق خاطئ أو منتهي الصلاحية")

        await self.save_state()
        return await self._screenshot("after_login")

    # ── الخطوات الخمس ───────────────────────────

    async def run_step_1(self) -> StepResult:
        """
        الخطوة 1 — الموقع (Desktop):
        الاشتراك في باقة بلس كومبو 600
        """
        if self.is_mobile:
            await self._create_context(is_mobile=False)

        await self._goto("/ar/internet/plus", wait=4)

        # ابحث عن بلس كومبو 600
        found = await self._click_text("بلس كومبو 600", timeout=10000)
        if not found:
            # جرّب اسم أقصر
            found = await self._click_text("بلس كومبو", timeout=5000)
        if not found:
            ss = await self._screenshot("step1_notfound")
            els = await self.get_interactive_elements()
            raise SelectorNotFoundError(
                "باقة بلس كومبو 600 غير موجودة في الصفحة — "
                "ربما تغير اسمها أو الصفحة لم تُحمَّل",
                ss, els,
            )

        await asyncio.sleep(2)

        # زر اشترك / الاشتراك
        ok = await self._click_text("اشترك", timeout=6000)
        if not ok:
            ok = await self._click_text("الاشتراك", timeout=4000)
        if not ok:
            ok = await self._click_text("تأكيد", timeout=4000)

        await asyncio.sleep(3)
        ss = await self._screenshot("step1_done")
        return StepResult(
            step=1, success=True,
            message="✅ تم الاشتراك في بلس كومبو 600 من الموقع",
            screenshot=ss,
        )

    async def run_step_2(self) -> StepResult:
        """
        الخطوة 2 — التطبيق (Mobile):
        اشترك في 1400 ميجا بـ28 جنيه؛ إذا غير موجود → ميجابايتس أكتر
        """
        await self._create_context(is_mobile=True)
        await self._goto("/ar/offers", wait=4)

        content = await self.page.content()
        offer_used = ""

        # محاولة 1: عرض 28 جنيه
        has_28   = "28"   in content and "1400" in content
        has_more = "ميجابايتس أكتر" in content or "أكتر" in content

        if has_28:
            clicked = await self._click_text("1400", timeout=6000)
            if not clicked:
                clicked = await self._click_text("28", timeout=5000)
            if clicked:
                await asyncio.sleep(2)
                await self._click_text("اشترك", timeout=5000) or \
                    await self._click_text("الاشتراك", timeout=3000)
                offer_used = "1400 ميجابايت بـ28 جنيه"
            else:
                has_28 = False  # فشل النقر، جرب البديل

        if not has_28:
            if has_more:
                clicked = await self._click_text("ميجابايتس أكتر", timeout=6000)
                if not clicked:
                    clicked = await self._click_text("أكتر", timeout=4000)
                if clicked:
                    await asyncio.sleep(2)
                    await self._click_text("اشترك", timeout=5000) or \
                        await self._click_text("الاشتراك", timeout=3000)
                    offer_used = "ميجابايتس أكتر على باقة 37 جنيه"
                else:
                    has_more = False

        if not has_28 and not has_more:
            ss = await self._screenshot("step2_no_offers")
            els = await self.get_interactive_elements()
            raise OfferNotFoundError(
                "⚠️ لم يُعثَر على عروض الخصم على هذا الخط!\n\n"
                "السبب المرجّح: الخط لا يملك عروض خصم مؤهلة حالياً.\n"
                "الحل: تأكد أن الخط يحتوي على عرض 1400 ميجا بـ28 جنيه "
                "أو عرض ميجابايتس أكتر قبل تشغيل الطريقة."
            )

        await asyncio.sleep(3)
        ss = await self._screenshot("step2_done")
        return StepResult(
            step=2, success=True,
            message=f"✅ تم الاشتراك في: {offer_used}",
            screenshot=ss, offer_used=offer_used,
        )

    async def run_step_3(self) -> StepResult:
        """
        الخطوة 3 — الموقع (Desktop):
        اشتراك ثانٍ في بلس كومبو 600 + إعادة شراء
        """
        await self._create_context(is_mobile=False)
        await self._goto("/ar/internet/plus", wait=4)

        # اشتراك ثانٍ
        found = await self._click_text("بلس كومبو 600", timeout=8000)
        if not found:
            found = await self._click_text("بلس كومبو", timeout=5000)
        if not found:
            ss = await self._screenshot("step3_notfound")
            els = await self.get_interactive_elements()
            raise SelectorNotFoundError(
                "لم يُعثَر على باقة بلس كومبو 600 للمرة الثانية",
                ss, els,
            )

        await asyncio.sleep(2)
        await self._click_text("اشترك", timeout=6000) or \
            await self._click_text("الاشتراك", timeout=4000)
        await asyncio.sleep(3)

        # إعادة شراء
        repurchased = await self._click_text("إعادة شراء", timeout=8000)
        if not repurchased:
            repurchased = await self._click_text("تجديد", timeout=5000)
        if not repurchased:
            ss = await self._screenshot("step3_repurchase_fail")
            els = await self.get_interactive_elements()
            raise SelectorNotFoundError(
                "لم يُعثَر على زر 'إعادة شراء' أو 'تجديد' بعد الاشتراك",
                ss, els,
            )

        await asyncio.sleep(2)
        # تأكيد النافذة
        await self._click_text("تأكيد", timeout=5000)
        await asyncio.sleep(3)

        ss = await self._screenshot("step3_done")
        return StepResult(
            step=3, success=True,
            message="✅ تم الاشتراك الثاني في بلس كومبو 600 وتنفيذ إعادة الشراء",
            screenshot=ss,
        )

    async def run_step_4(self) -> StepResult:
        """
        الخطوة 4 — التطبيق (Mobile):
        الاشتراك في 1400 ميجابايت بـ19 جنيه
        """
        await self._create_context(is_mobile=True)
        await self._goto("/ar/offers", wait=4)

        content = await self.page.content()

        # تحقق وجود عرض 19 جنيه
        has_19 = "19" in content and "1400" in content

        if not has_19:
            ss = await self._screenshot("step4_no_19")
            els = await self.get_interactive_elements()
            raise OfferNotFoundError(
                "⚠️ عرض 1400 ميجابايت بـ19 جنيه غير موجود الآن!\n\n"
                "الأسباب المحتملة:\n"
                "• الخطوات السابقة لم تُنفَّذ بالترتيب الصحيح\n"
                "• العرض ظهر بعد فترة — انتظر دقيقة وأعد المحاولة\n"
                "• الخط غير مؤهل لهذا العرض في الوقت الحالي"
            )

        clicked = await self._click_text("19", timeout=8000)
        if not clicked:
            clicked = await self._click_text("1400", timeout=5000)
        if not clicked:
            ss = await self._screenshot("step4_click_fail")
            els = await self.get_interactive_elements()
            raise SelectorNotFoundError(
                "عرض 19 جنيه موجود في الصفحة لكن لم يمكن النقر عليه",
                ss, els,
            )

        await asyncio.sleep(2)
        await self._click_text("اشترك", timeout=6000) or \
            await self._click_text("الاشتراك", timeout=4000)
        await asyncio.sleep(3)

        ss = await self._screenshot("step4_done")
        return StepResult(
            step=4, success=True,
            message="✅ تم الاشتراك في عرض 1400 ميجابايت بـ19 جنيه",
            screenshot=ss,
        )

    async def run_step_5(self) -> StepResult:
        """
        الخطوة 5 — الموقع (Desktop):
        إعادة شراء نهائية لبلس كومبو 600
        """
        await self._create_context(is_mobile=False)
        await self._goto("/ar/internet/plus", wait=4)

        repurchased = await self._click_text("إعادة شراء", timeout=10000)
        if not repurchased:
            repurchased = await self._click_text("تجديد", timeout=6000)

        if not repurchased:
            ss = await self._screenshot("step5_notfound")
            els = await self.get_interactive_elements()
            raise SelectorNotFoundError(
                "لم يُعثَر على زر 'إعادة شراء' في الخطوة الأخيرة.\n"
                "ربما لم تكتمل إعادة الشراء في الخطوة 3 بشكل صحيح.",
                ss, els,
            )

        await asyncio.sleep(2)
        await self._click_text("تأكيد", timeout=5000)
        await asyncio.sleep(3)

        ss = await self._screenshot("step5_done")
        return StepResult(
            step=5, success=True,
            message="✅ تمت إعادة الشراء النهائية لبلس كومبو 600",
            screenshot=ss,
        )

    # ── التحقق النهائي ───────────────────────────

    async def run_verification(self):
        """
        يفحص الاشتراكات القادمة ويرجع:
        (نجاح: bool, السعر: str, مسار_الصورة: str)
        """
        await self._create_context(is_mobile=False)
        await self._goto("/ar/internet/management", wait=4)

        await self._click_text("الاشتراكات القادمة", timeout=8000)
        await asyncio.sleep(2)

        ss  = await self._screenshot("verify")
        content = await self.page.content()

        if "بلس كومبو 600" not in content and "بلس كومبو" not in content:
            return False, "باقة بلس كومبو 600 غير موجودة في الاشتراكات القادمة", ss

        for price, label in [("19", "19 جنيه"), ("١٩", "19 جنيه"),
                              ("28", "28 جنيه"), ("٢٨", "28 جنيه")]:
            if price in content:
                return price in ("19", "١٩"), label, ss

        return False, "السعر غير واضح", ss

    # ── Workflow كامل ────────────────────────────

    async def run_full_workflow(self, progress_callback=None):
        """
        ينفذ الخطوات 1→5 كاملة ثم يتحقق.
        progress_callback(result: StepResult) يُستدعى بعد كل خطوة.
        يرجع قائمة StepResult.
        """
        steps = [
            self.run_step_1,
            self.run_step_2,
            self.run_step_3,
            self.run_step_4,
            self.run_step_5,
        ]
        results = []

        for fn in steps:
            try:
                result = await fn()
            except OfferNotFoundError as e:
                result = StepResult(
                    step=fn.__name__[-1], success=False,
                    message=str(e),
                    screenshot="",
                )
            except SelectorNotFoundError as e:
                result = StepResult(
                    step=fn.__name__[-1], success=False,
                    message=(
                        f"❌ عنصر غير موجود في الصفحة\n"
                        f"📌 التفاصيل: {e.args[0]}"
                    ),
                    screenshot=e.screenshot_path,
                    interactive_elements=e.interactive_elements,
                )
            except PageLoadError as e:
                result = StepResult(
                    step=fn.__name__[-1], success=False,
                    message=f"❌ فشل تحميل الصفحة\n📌 {e}",
                )
            except Exception as e:
                result = StepResult(
                    step=fn.__name__[-1], success=False,
                    message=f"❌ خطأ غير متوقع: {type(e).__name__}: {e}",
                )

            results.append(result)
            if progress_callback:
                await progress_callback(result)

            # إذا فشلت خطوة بشكل حرج، أوقف
            if not result.success:
                break

        return results
