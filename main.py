import os
import asyncio
from datetime import datetime

import requests
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

CHECK_INTERVAL = 300  # 5 минут

sent_links = set()


def log(text):

    now = datetime.now().strftime("%H:%M:%S")

    message = f"[{now}] {text}"

    print(message)

    try:

        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=15
        )

    except Exception as e:

        print("Telegram error:", e)


async def login(page):

    try:

        log("🌐 Открываю сайт...")

        await page.goto(
            "https://www.campusgroningen.com",
            wait_until="networkidle",
            timeout=60000
        )

        await page.wait_for_timeout(5000)

        current_url = page.url.lower()

        if (
            "mijncampus" in current_url
            or "favorieten" in current_url
        ):

            log("✅ Уже авторизован")

            return True

        # cookies
        try:

            cookie_btn = page.locator(
                'button:has-text("Accept")'
            )

            if await cookie_btn.count() > 0:

                log("🍪 Принимаю cookies")

                await cookie_btn.click(
                    force=True
                )

                await page.wait_for_timeout(2000)

        except:
            pass

        log("🔐 Открываю окно логина...")

        await page.click(
            "text=Inloggen",
            force=True,
            timeout=30000
        )

        await page.wait_for_timeout(5000)

        log("📧 Ввожу email...")

        email_input = page.locator(
            'input[type="email"]'
        ).first

        await email_input.fill(EMAIL)

        log("🔑 Ввожу пароль...")

        password_input = page.locator(
            'input[type="password"]'
        ).first

        await password_input.fill(PASSWORD)

        await page.wait_for_timeout(2000)

        log("⌨️ Нажимаю ENTER...")

        await password_input.press("Enter")

        await page.wait_for_timeout(15000)

        current_url = page.url.lower()

        page_text = (
            await page.content()
        ).lower()

        log(f"🌍 URL после логина: {current_url}")

        # Проверяем успешный вход
        success = (
            "uitloggen" in page_text
            or "mijn favorieten" in page_text
            or "logout" in page_text
            or "mijncampus" in current_url
            or "favorieten" in current_url
        )

        if success:

            log("✅ Авторизация успешна")

            return True

        else:

            log("❌ Логин не прошел")

            await page.screenshot(
                path="login_failed.png",
                full_page=True
            )

            html = await page.content()

            with open(
                "login_failed.html",
                "w",
                encoding="utf-8"
            ) as f:

                f.write(html)

            return False

    except Exception as e:

        try:

            await page.screenshot(
                path="login_error.png",
                full_page=True
            )

        except:
            pass

        log(f"❌ Ошибка логина: {e}")

        return False

async def check_apartments(page):

    global sent_links

    try:

        log("🏠 Открываю избранные объявления...")

        await page.goto(
            "https://www.campusgroningen.com/mijn-favorieten",
            wait_until="domcontentloaded",
            timeout=60000
        )

        await page.wait_for_timeout(5000)

        listings = await page.locator("article").all()

        log(f"📋 Найдено объявлений: {len(listings)}")

        found_any = False

        for index, item in enumerate(listings, start=1):

            try:

                log(f"🔍 Проверяю объявление #{index}")

                text = await item.inner_text()

                text_lower = text.lower()

                has_join_button = (
                    "deelnemen" in text_lower
                    or "participate" in text_lower
                    or "join" in text_lower
                    or "inschrijven" in text_lower
                )

                if has_join_button:

                    found_any = True

                    log("🎉 Найдена запись на просмотр!")

                    link = await item.locator(
                        "a"
                    ).first.get_attribute("href")

                    if not link:

                        log("⚠️ Ссылка не найдена")

                        continue

                    if link.startswith("http"):

                        full_link = link

                    else:

                        full_link = (
                            f"https://www.campusgroningen.com{link}"
                        )

                    title = "Неизвестное объявление"

                    try:

                        title = await item.locator(
                            "h1, h2, h3"
                        ).first.inner_text()

                    except:
                        pass

                    if full_link not in sent_links:

                        sent_links.add(full_link)

                        log(
                            f"🏠 ДОСТУПНА ЗАПИСЬ НА ПРОСМОТР\n\n"
                            f"📌 {title}\n\n"
                            f"🔗 {full_link}"
                        )

                    else:

                        log("ℹ️ Уже отправлялось ранее")

                else:

                    log("❌ Записи нет")

            except Exception as e:

                log(
                    f"⚠️ Ошибка проверки объявления: {e}"
                )

        if not found_any:

            log("😴 Свободных записей пока нет")

    except Exception as e:

        try:

            await page.screenshot(
                path="favorites_error.png"
            )

        except:
            pass

        log(
            f"❌ Ошибка страницы избранного: {e}"
        )


async def main():

    log("🚀 Бот запущен")

    while True:

        try:

            async with async_playwright() as p:

                log("🌐 Запуск браузера...")

                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-setuid-sandbox",
                        "--disable-gpu",
                        "--no-zygote",
                        "--single-process"
                    ]
                )

                context = await browser.new_context()

                page = await context.new_page()

                log("✅ Браузер успешно запущен")

                while True:

                    try:

                        log("🔄 Новый цикл проверки")

                        success = await login(page)

                        if success:

                            await check_apartments(page)

                        else:

                            log(
                                "⚠️ Пропускаю проверку объявлений из-за ошибки логина"
                            )

                        log(
                            f"⏳ Ожидание {CHECK_INTERVAL} секунд..."
                        )

                    except Exception as e:

                        log(f"⚠️ Ошибка цикла: {e}")

                    await asyncio.sleep(
                        CHECK_INTERVAL
                    )

        except Exception as e:

            log(
                f"🔥 КРИТИЧЕСКАЯ ОШИБКА: {e}"
            )

            log(
                "♻️ Перезапуск браузера через 30 секунд..."
            )

            await asyncio.sleep(30)


asyncio.run(main())
