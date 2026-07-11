"""
automation.py — محرك Playwright لأتمتة موقع وتطبيق أنا فودافون
================================================================
- تسجيل دخول برقم الهاتف + كلمة المرور
- سياق Desktop للموقع + Mobile للتطبيق
- تنفيذ الخطوات 1→5 بشكل سلس كامل
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
    message: str
    screenshot: str = ""
    offer_used: str = ""
    interactive_elements: list = field(default_factory=list)


# ─────────────────────────────────────────────
# محرك الأتمتة
# ─────────────────────────────────────────────
class VodafoneAutomation:

    def __init__(self, headless: bool = True, timeout: int = 20000,
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
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            await self._create_context(is_mobile=False)

    async def stop(self):
        if self.context:
            try:
                await self.context.close()
            except Exception:
                pass
            self.context = None
        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass
            self.browser = None
        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception:
                pass
            self.playwright = None

    async def _create_context(self, is_mobile: bool = False):
        """ينشئ سياق متصفح جديد (Desktop أو Mobile) مع حفظ الجلسة."""
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
                **device,
                storage_state=storage,
                locale="ar-EG",
                timezone_id="Africa/Cairo",
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
                locale="ar-EG",
                timezone_id="Africa/Cairo",
            )

        self.is_mobile = is_mobile
        self.page = await self.context.new_page()
        self.page.set_default_timeout(self.timeout)
        logger.info("Context → %s", "Mobile" if is_mobile else "Desktop")

    async def switch_context(self, to_mobile: bool):
        """يبدّل بين وضع Desktop و Mobile."""
        if self.is_mobile != to_mobile:
            await self._create_context(is_mobile=to_mobile)

    async def save_state(self):
        if self.context:
            await self.context.storage_state(path=self.state_file)

    # ── مساعدات ──────────────────────────────────

    async def _goto(self, path: str, wait: float = 3.0):
        url = f"{self.base_url}{path}"
        try:
            await self.page.goto(url, wait_until="domcontentloaded",
                                 timeout=self.timeout)
            await asyncio.sleep(wait)
        except PlaywrightTimeoutError:
            raise PageLoadError(f"فشل تحميل الصفحة: {url}")

    async def _dismiss_cookies(self):
        """يغلق نافذة الكوكيز إذا ظهرت."""
        for txt in ["قبول كل الملفات", "قبول", "Accept All", "موافق"]:
            try:
                loc = self.page.get_by_text(txt, exact=False).first
                if await loc.is_visible(timeout=2000):
                    await loc.click()
                    await asyncio.sleep(1)
                    return
            except Exception:
                pass

    async def _click_text(self, text: str, timeout: int = None) -> bool:
        t = timeout or self.timeout
        try:
            loc = self.page.get_by_text(text, exact=False).first
            await loc.wait_for(state="visible", timeout=t)
            await loc.click()
            return True
        except Exception:
            return False

    async def _click_selector(self, selector: str, timeout: int = None) -> bool:
        t = timeout or self.timeout
        try:
            await self.page.wait_for_selector(selector, timeout=t)
            await self.page.click(selector)
            return True
        except Exception:
            return False

    async def _screenshot(self, name: str = "shot") -> str:
        path = f"{name}.png"
        try:
            await self.page.screenshot(path=path)
        except Exception:
            pass
        return path

    async def get_screenshot(self, path: str = "screenshot.png") -> str:
        try:
            await self.page.screenshot(path=path)
        except Exception:
            pass
        return path

    async def get_interactive_elements(self) -> list:
        try:
            return await self.page.evaluate(r"""() => {
                const sel = 'button,a,input,select,textarea,[role="button"],[onclick]';
                return [...document.querySelectorAll(sel)]
                    .map((el, i) => {
                        const r = el.getBoundingClientRect();
                        if (r.width === 0 || r.height === 0) return null;
                        let t = (el.innerText || el.placeholder ||
                                 el.getAttribute('aria-label') || '').trim()
                                 .replace(/\s+/g,' ').substring(0,50);
                        if (!t && el.tagName==='INPUT')
                            t = 'Input[' + el.type + '] ' + (el.name||el.id||'');
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

    # ── تسجيل الدخول برقم الهاتف + كلمة المرور ──

    async def login(self, phone: str, password: str) -> str:
        """
        يسجّل الدخول برقم الهاتف وكلمة المرور.
        يضغط على أيقونة الحساب → يتحول لصفحة Keycloak → يملأ البيانات.
        """
        await self._create_context(is_mobile=False)
        await self._goto("/ar/home", wait=3)
        await self._dismiss_cookies()

        # ── الخطوة 1: الضغط على أيقونة الحساب (الشخص) لفتح صفحة الدخول ──
        login_triggered = False

        # محاولة النقر على أيقونة الحساب بعدة طرق
        icon_selectors = [
            "a[href*='login']",
            "a[href*='myHome']",
            ".login-icon",
            ".user-icon",
            "header .icon-user",
            "[class*='login']",
            "[class*='account']",
            # أيقونة الشخص عادة SVG أو span بجانب اليمين/اليسار
            "header a:last-of-type",
            "nav a:last-of-type",
        ]

        for sel in icon_selectors:
            try:
                loc = self.page.locator(sel).first
                if await loc.is_visible(timeout=1500):
                    await loc.click()
                    await asyncio.sleep(2)
                    login_triggered = True
                    logger.info(f"Clicked login icon via: {sel}")
                    break
            except Exception:
                pass

        # لو ما نجح، جرب بالنص
        if not login_triggered:
            for txt in ["دخول", "تسجيل الدخول", "حسابي", "Login"]:
                if await self._click_text(txt, timeout=3000):
                    await asyncio.sleep(2)
                    login_triggered = True
                    break

        # ── الخطوة 2: انتظر إعادة التوجيه لصفحة Keycloak ──
        # نتحقق أن الـ URL تغيّر لصفحة auth
        try:
            await self.page.wait_for_url(
                lambda url: "openid-connect" in url or "auth/realms" in url or "login" in url,
                timeout=10000
            )
            await asyncio.sleep(2)
            logger.info(f"Redirected to login page: {self.page.url}")
        except Exception:
            # لو ما صار redirect تلقائي، جرب navigate مباشرة
            logger.info("No redirect detected, trying direct navigation...")
            # أول خطوة: روح للهوم وبعدين اضغط على الرابط
            try:
                # استخرج رابط الدخول من الصفحة
                href = await self.page.evaluate("""() => {
                    const links = [...document.querySelectorAll('a')];
                    const loginLink = links.find(a =>
                        a.href.includes('login') ||
                        a.href.includes('auth') ||
                        a.href.includes('myHome')
                    );
                    return loginLink ? loginLink.href : null;
                }""")
                if href:
                    await self.page.goto(href, wait_until="domcontentloaded", timeout=10000)
                    await asyncio.sleep(2)
            except Exception:
                pass

        # ── الخطوة 3: ملء حقل رقم الهاتف (username) ──
        # Keycloak يستخدم input[name='username'] أو input#username
        phone_selectors = [
            "input[name='username']",
            "input#username",
            "input#kc-form-login",
            "input[autocomplete='username']",
            "input[type='text']:visible",
            "input[type='tel']",
        ]

        phone_filled = False
        for sel in phone_selectors:
            try:
                await self.page.wait_for_selector(sel, state="visible", timeout=8000)
                await self.page.fill(sel, phone)
                phone_filled = True
                logger.info(f"Phone filled with selector: {sel}")
                break
            except Exception:
                continue

        if not phone_filled:
            ss = await self._screenshot("login_no_phone_field")
            els = await self.get_interactive_elements()
            raise SelectorNotFoundError(
                "لم يُعثَر على حقل رقم الهاتف في صفحة تسجيل الدخول\n"
                "تأكد أن الضغط على أيقونة الحساب يفتح صفحة الدخول",
                ss, els,
            )

        await asyncio.sleep(0.5)

        # ── الخطوة 4: ملء كلمة المرور ──
        password_selectors = [
            "input[name='password']",
            "input#password",
            "input[type='password']",
            "input[autocomplete='current-password']",
        ]

        password_filled = False
        for sel in password_selectors:
            try:
                await self.page.wait_for_selector(sel, state="visible", timeout=5000)
                await self.page.fill(sel, password)
                password_filled = True
                logger.info(f"Password filled with selector: {sel}")
                break
            except Exception:
                continue

        if not password_filled:
            ss = await self._screenshot("login_no_pass_field")
            els = await self.get_interactive_elements()
            raise SelectorNotFoundError(
                "لم يُعثَر على حقل كلمة المرور",
                ss, els,
            )

        await asyncio.sleep(0.5)

        # ── الخطوة 5: تسجيل الدخول ──
        # Keycloak زر الدخول عادة: input[type='submit'] أو button[type='submit']
        submit_selectors = [
            "input[type='submit']",
            "button[type='submit']",
            "#kc-login",
            ".btn-primary",
        ]
        submitted = False
        for sel in submit_selectors:
            try:
                await self.page.wait_for_selector(sel, timeout=3000)
                await self.page.click(sel)
                submitted = True
                break
            except Exception:
                continue

        if not submitted:
            # جرب بالنص
            for txt in ["دخول", "تسجيل الدخول", "Login", "Sign In", "إرسال"]:
                if await self._click_text(txt, timeout=3000):
                    submitted = True
                    break

        # ── الخطوة 6: انتظار إتمام الدخول ──
        await asyncio.sleep(4)

        # تحقق من نجاح الدخول (نرجع لصفحة الهوم بعد الدخول)
        current_url = self.page.url
        content = await self.page.content()

        if "خطأ" in content or "غير صحيح" in content or "Invalid" in content:
            raise ValueError("رقم الهاتف أو كلمة المرور غير صحيحة — تأكد من البيانات وحاول مرة أخرى")

        await self.save_state()
        logger.info(f"Login done. Current URL: {current_url}")
        return await self._screenshot("after_login")

    # ── الخطوات الخمس ───────────────────────────


    async def _subscribe_plus_combo(self) -> bool:
        """يشترك في بلس كومبو 600 — يُستخدم في الخطوتين 1 و3."""
        await self._goto("/ar/internet/plus", wait=4)
        await self._dismiss_cookies()

        for name in ["بلس كومبو 600", "Plus Combo 600", "بلس كومبو"]:
            if await self._click_text(name, timeout=6000):
                await asyncio.sleep(2)
                break

        for btn in ["اشترك الآن", "اشترك", "الاشتراك", "Subscribe"]:
            if await self._click_text(btn, timeout=5000):
                await asyncio.sleep(3)
                return True

        return False

    async def _repurchase(self) -> bool:
        """يضغط على إعادة شراء."""
        for txt in ["إعادة شراء", "تجديد الباقة", "تجديد", "Renew"]:
            if await self._click_text(txt, timeout=8000):
                await asyncio.sleep(2)
                for confirm in ["تأكيد", "موافق", "نعم", "Confirm"]:
                    if await self._click_text(confirm, timeout=4000):
                        await asyncio.sleep(3)
                        return True
                return True
        return False

    async def run_step_1(self) -> StepResult:
        """الخطوة 1 — الموقع (Desktop): الاشتراك في بلس كومبو 600"""
        await self.switch_context(to_mobile=False)
        ok = await self._subscribe_plus_combo()

        if not ok:
            ss = await self._screenshot("step1_fail")
            els = await self.get_interactive_elements()
            raise SelectorNotFoundError(
                "لم يُعثَر على باقة بلس كومبو 600 أو زر الاشتراك في الصفحة",
                ss, els,
            )

        ss = await self._screenshot("step1_done")
        return StepResult(
            step=1, success=True,
            message="✅ تم الاشتراك في بلس كومبو 600 من الموقع",
            screenshot=ss,
        )

    async def run_step_2(self) -> StepResult:
        """الخطوة 2 — التطبيق (Mobile): 1400 ميجا بـ28 جنيه أو ميجابايتس أكتر"""
        await self.switch_context(to_mobile=True)
        await self._goto("/ar/offers", wait=4)
        await self._dismiss_cookies()

        content = await self.page.content()
        offer_used = ""

        # جرب عرض 28 جنيه
        if "28" in content and "1400" in content:
            clicked = (
                await self._click_text("1400 ميجابايت", timeout=5000) or
                await self._click_text("1400 ميجا", timeout=3000) or
                await self._click_text("28 جنيه", timeout=3000)
            )
            if clicked:
                await asyncio.sleep(2)
                await self._click_text("اشترك", timeout=5000) or \
                    await self._click_text("الاشتراك", timeout=3000)
                offer_used = "1400 ميجابايت بـ28 جنيه"

        # لو مش موجود، جرب ميجابايتس أكتر
        if not offer_used:
            content = await self.page.content()
            if "ميجابايتس أكتر" in content or "أكتر" in content:
                clicked = (
                    await self._click_text("ميجابايتس أكتر", timeout=5000) or
                    await self._click_text("أكتر", timeout=3000)
                )
                if clicked:
                    await asyncio.sleep(2)
                    await self._click_text("اشترك", timeout=5000) or \
                        await self._click_text("الاشتراك", timeout=3000)
                    offer_used = "ميجابايتس أكتر على باقة 37 جنيه"

        if not offer_used:
            ss = await self._screenshot("step2_no_offers")
            els = await self.get_interactive_elements()
            raise OfferNotFoundError(
                "⚠️ لم يُعثَر على عروض الخصم على هذا الخط!\n\n"
                "السبب: الخط لا يملك عرض 1400 ميجا بـ28 جنيه أو ميجابايتس أكتر حالياً.\n"
                "الحل: تأكد من توفر أحد هذين العرضين على الخط أولاً."
            )

        await asyncio.sleep(3)
        ss = await self._screenshot("step2_done")
        return StepResult(
            step=2, success=True,
            message=f"✅ تم الاشتراك في: {offer_used}",
            screenshot=ss, offer_used=offer_used,
        )

    async def run_step_3(self) -> StepResult:
        """الخطوة 3 — الموقع (Desktop): اشتراك ثانٍ في بلس كومبو 600 + إعادة شراء"""
        await self.switch_context(to_mobile=False)

        ok = await self._subscribe_plus_combo()
        if not ok:
            ss = await self._screenshot("step3_sub_fail")
            els = await self.get_interactive_elements()
            raise SelectorNotFoundError(
                "لم يُعثَر على بلس كومبو 600 للاشتراك الثاني",
                ss, els,
            )

        repurchased = await self._repurchase()
        if not repurchased:
            ss = await self._screenshot("step3_repurchase_fail")
            els = await self.get_interactive_elements()
            raise SelectorNotFoundError(
                "لم يُعثَر على زر إعادة الشراء بعد الاشتراك الثاني",
                ss, els,
            )

        ss = await self._screenshot("step3_done")
        return StepResult(
            step=3, success=True,
            message="✅ تم الاشتراك الثاني في بلس كومبو 600 وتنفيذ إعادة الشراء",
            screenshot=ss,
        )

    async def run_step_4(self) -> StepResult:
        """الخطوة 4 — التطبيق (Mobile): 1400 ميجابايت بـ19 جنيه"""
        await self.switch_context(to_mobile=True)
        await self._goto("/ar/offers", wait=4)
        await self._dismiss_cookies()

        content = await self.page.content()

        if "19" not in content or "1400" not in content:
            ss = await self._screenshot("step4_no_19")
            els = await self.get_interactive_elements()
            raise OfferNotFoundError(
                "⚠️ عرض 1400 ميجابايت بـ19 جنيه غير موجود الآن!\n\n"
                "الأسباب المحتملة:\n"
                "• الخطوات السابقة لم تكتمل بالترتيب الصحيح\n"
                "• العرض لم يظهر بعد — انتظر دقيقة وأعد المحاولة\n"
                "• الخط غير مؤهل لهذا العرض"
            )

        clicked = (
            await self._click_text("1400 ميجابايت", timeout=6000) or
            await self._click_text("19 جنيه", timeout=4000) or
            await self._click_text("1400", timeout=4000)
        )

        if not clicked:
            ss = await self._screenshot("step4_click_fail")
            els = await self.get_interactive_elements()
            raise SelectorNotFoundError(
                "عرض 19 جنيه موجود لكن لم يمكن النقر عليه",
                ss, els,
            )

        await asyncio.sleep(2)
        await self._click_text("اشترك", timeout=5000) or \
            await self._click_text("الاشتراك", timeout=3000)
        await asyncio.sleep(3)

        ss = await self._screenshot("step4_done")
        return StepResult(
            step=4, success=True,
            message="✅ تم الاشتراك في عرض 1400 ميجابايت بـ19 جنيه",
            screenshot=ss,
        )

    async def run_step_5(self) -> StepResult:
        """الخطوة 5 — الموقع (Desktop): إعادة شراء نهائية لبلس كومبو 600"""
        await self.switch_context(to_mobile=False)
        await self._goto("/ar/internet/plus", wait=4)
        await self._dismiss_cookies()

        repurchased = await self._repurchase()
        if not repurchased:
            ss = await self._screenshot("step5_fail")
            els = await self.get_interactive_elements()
            raise SelectorNotFoundError(
                "لم يُعثَر على زر إعادة الشراء في الخطوة الأخيرة",
                ss, els,
            )

        ss = await self._screenshot("step5_done")
        return StepResult(
            step=5, success=True,
            message="✅ تمت إعادة الشراء النهائية لبلس كومبو 600",
            screenshot=ss,
        )

    # ── التحقق النهائي ───────────────────────────

    async def run_verification(self):
        """
        يفحص الاشتراكات القادمة.
        يرجع: (نجاح: bool, السعر: str, مسار_الصورة: str)
        """
        await self.switch_context(to_mobile=False)
        await self._goto("/ar/internet/management", wait=4)
        await self._dismiss_cookies()

        await self._click_text("الاشتراكات القادمة", timeout=8000)
        await asyncio.sleep(2)

        ss = await self._screenshot("verify")
        content = await self.page.content()

        if "بلس كومبو" not in content:
            return False, "باقة بلس كومبو 600 غير موجودة في الاشتراكات القادمة", ss

        for price, label in [("19", "19 جنيه"), ("١٩", "19 جنيه"),
                              ("28", "28 جنيه"), ("٢٨", "28 جنيه")]:
            if price in content:
                success = price in ("19", "١٩")
                return success, label, ss

        return False, "السعر غير واضح في الصفحة", ss

    # ── Workflow كامل ────────────────────────────

    async def run_full_workflow(self, progress_callback=None):
        """
        ينفذ الخطوات 1→5 كاملة ثم يتحقق.
        progress_callback(result: StepResult) يُستدعى بعد كل خطوة.
        """
        steps = [
            self.run_step_1,
            self.run_step_2,
            self.run_step_3,
            self.run_step_4,
            self.run_step_5,
        ]
        results = []

        for i, fn in enumerate(steps, start=1):
            try:
                result = await fn()
            except OfferNotFoundError as e:
                result = StepResult(
                    step=i, success=False,
                    message=str(e),
                )
            except SelectorNotFoundError as e:
                result = StepResult(
                    step=i, success=False,
                    message=f"❌ عنصر غير موجود\n📌 {e.args[0]}",
                    screenshot=e.screenshot_path,
                    interactive_elements=e.interactive_elements,
                )
            except PageLoadError as e:
                result = StepResult(
                    step=i, success=False,
                    message=f"❌ فشل تحميل الصفحة\n📌 {e}",
                )
            except Exception as e:
                result = StepResult(
                    step=i, success=False,
                    message=f"❌ خطأ غير متوقع: {type(e).__name__}: {e}",
                )

            results.append(result)

            if progress_callback:
                await progress_callback(result)

            if not result.success:
                break

        return results
