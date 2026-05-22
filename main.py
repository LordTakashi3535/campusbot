import os
import asyncio
from playwright.async_api import async_playwright
import requests
from dotenv import load_dotenv
from datetime import datetime

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
            timeout=10
        )
    except Exception as e:
        print("Telegram error:", e)


async def login(page):

    log("🌐 Открываю сайт...")

    await page.goto(
        "https://www.campusgroningen.com",
        wait_until="domcontentloaded"
    )

    await page.wait_for_timeout(3000)

    if "mijncampus" in page.url.lower():

        log("✅ Уже авторизован")

        return

    log("🔐 Авторизация...")

    await page.click("text=Inloggen")

    await page.wait_for_timeout(2000)

    await page.fill('input[type="email"]', EMAIL)

    log("📧 Email введен")

    await page.fill('input[type="password"]', PASSWORD)

    log("🔑 Пароль введен")

    await page.click('button[type="submit"]')

    log("🚀 Отправляю форму логина...")

    await page.wait_for_timeout(7000)

    if "mijncampus" in page.url.lower():

        log("✅ Успешный вход")

    else:

        log("❌ Не удалось войти")


async def check_apartments(page):

    global sent_links

    log("🏠 Переход в избранные объявления...")

    await page.goto(
        "https://www.campusgroningen.com/mijn-favorieten",
        wait_until="domcontentloaded"
    )

    await page.wait_for_timeout(5000)

    listings = await page.locator("article").all()

    log(f"📋 Найдено объявлений: {len(listings)}")

    found_any = False

    for index, item in enumerate(listings, start=1):

        try:

            log(f"🔍 Проверяю объявление #{index}")

            text = await item.inner_text()

            has_join_button = (
                "deelnemen" in text.lower()
                or "participate" in text.lower()
                or "join" in text.lower()
            )

            if has_join_button:

                found_any = True

                log("🎉 Найдена кнопка участия!")

                link = await item.locator("a").first.get_attribute("href")

                if not link:
                    continue

                full_link = f"https://www.campusgroningen.com{link}"

                if full_link not in sent_links:

                    sent_links.add(full_link)

                    log(
                        f"🏠 Есть запись на просмотр!\n\n{full_link}"
                    )

                else:

                    log("ℹ️ Уже отправлялось ранее")

            else:

                log("❌ Кнопка участия не найдена")

        except Exception as e:

            log(f"⚠️ Ошибка проверки объявления: {e}")

    if not found_any:

        log("😴 Свободных записей пока нет")


async def main():

    log("🚀 Бот запущен")

    async with async_playwright() as p:

        log("🌐 Запуск браузера...")

        browser = await p.chromium.launch(
            headless=True
        )

        context = await browser.new_context()

        page = await context.new_page()

        while True:

            try:

                log("🔄 Начинаю новый цикл проверки")

                await login(page)

                await check_apartments(page)

                log(
                    f"⏳ Жду {CHECK_INTERVAL} секунд до следующей проверки"
                )

            except Exception as e:

                log(f"🔥 Глобальная ошибка: {e}")

            await asyncio.sleep(CHECK_INTERVAL)


asyncio.run(main())
