import asyncio
import os
import sys
from playwright.async_api import async_playwright

async def run():
    print("Starting Playwright...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="ar-EG",
            timezone_id="Africa/Cairo"
        )
        page = await context.new_page()
        
        print("Navigating to home page...")
        await page.goto("https://web.vodafone.com.eg/ar/home", wait_until="domcontentloaded")
        await asyncio.sleep(5)
        await page.screenshot(path="01_home.png")
        
        # Accept cookies
        print("Dismissing cookies...")
        for txt in ["قبول كل الملفات", "قبول", "Accept All", "موافق"]:
            try:
                loc = page.get_by_text(txt, exact=False).first
                if await loc.is_visible(timeout=2000):
                    await loc.click()
                    print(f"Clicked cookie button: {txt}")
                    await asyncio.sleep(1)
                    break
            except Exception:
                pass
                
        # Click login
        print("Clicking login icon...")
        login_clicked = False
        for sel in ["a[href*='login']", "a[href*='myHome']", ".login-icon", ".user-icon", "header .icon-user"]:
            try:
                loc = page.locator(sel).first
                if await loc.is_visible(timeout=2000):
                    await loc.click()
                    login_clicked = True
                    print(f"Clicked login icon using: {sel}")
                    break
            except Exception:
                pass
        
        if not login_clicked:
            try:
                loc = page.get_by_text("دخول", exact=False).first
                if await loc.is_visible(timeout=2000):
                    await loc.click()
                    login_clicked = True
                    print("Clicked login using text 'دخول'")
            except Exception:
                pass
                
        await asyncio.sleep(5)
        await page.screenshot(path="02_login_page.png")
        print(f"Current URL: {page.url}")
        
        # Look for username input
        print("Entering phone number...")
        phone = "01028834606"
        phone_selectors = [
            "input[name='mobileNumber']",
            "input[name='username']",
            "input#username",
            "input[type='tel']",
            "input[type='text']:visible"
        ]
        
        phone_filled = False
        for sel in phone_selectors:
            try:
                loc = page.locator(sel).first
                if await loc.is_visible(timeout=2000):
                    await loc.fill(phone)
                    phone_filled = True
                    print(f"Filled phone using: {sel}")
                    break
            except Exception:
                pass
                
        await page.screenshot(path="03_phone_filled.png")
        
        # Check if there is a password login option on this screen
        # Sometimes there's a link saying "الدخول بكلمة المرور" or "تسجيل الدخول بكلمة المرور"
        content = await page.content()
        print("Page HTML content summary:")
        print(f"Contains 'كلمة المرور': {'كلمة المرور' in content}")
        print(f"Contains 'الرمز السري': {'الرمز السري' in content}")
        print(f"Contains 'استمرار': {'استمرار' in content}")
        
        # Click Continue / Submit
        print("Clicking continue...")
        continue_clicked = False
        for sel in ["input[type='submit']", "button[type='submit']", "#kc-login", ".btn-primary"]:
            try:
                loc = page.locator(sel).first
                if await loc.is_visible(timeout=2000):
                    await loc.click()
                    continue_clicked = True
                    print(f"Clicked continue using: {sel}")
                    break
            except Exception:
                pass
                
        if not continue_clicked:
            try:
                loc = page.get_by_text("استمرار", exact=False).first
                if await loc.is_visible(timeout=2000):
                    await loc.click()
                    continue_clicked = True
                    print("Clicked continue using text")
            except Exception:
                pass
                
        await asyncio.sleep(5)
        await page.screenshot(path="04_after_continue.png")
        print(f"Current URL after continue: {page.url}")
        
        # Print list of input fields on the screen now
        inputs = await page.evaluate("""() => {
            return [...document.querySelectorAll('input, button, a')].map(el => ({
                tag: el.tagName,
                type: el.type,
                name: el.name,
                id: el.id,
                text: el.innerText || el.value,
                visible: el.getBoundingClientRect().width > 0
            })).filter(x => x.visible);
        }""")
        print("Visible elements on screen:")
        for inp in inputs:
            print(inp)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
