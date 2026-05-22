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
            wait_until="domcontentloaded",
            timeout=60000
        )

        await page.wait_for_timeout(5000)

        current_url = page.url.lower()

        if (
            "dashboard" in current_url
            or "favorieten" in current_url
        ):

            log("✅ Уже авторизован")

            return True

        # Cookies
        try:

            cookie_button = page.locator(
                'button:has-text("Accept")'
            )

            if await cookie_button.count() > 0:

                log("🍪 Принимаю cookies")

                await cookie_button.first.click(
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

        await page.wait_for_timeout(10000)

        current_url = page.url.lower()

        page_text = (
            await page.content()
        ).lower()

        success = (
            "uitloggen" in page_text
            or "mijn favorieten" in page_text
            or "dashboard" in current_url
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
            "https://www.campusgroningen.com/dashboard/mijn-favorieten",
            wait_until="domcontentloaded",
            timeout=60000
        )

        await page.wait_for_timeout(5000)

        apartment_links = []

        # Берем все ссылки
        all_links = page.locator("a")

        links_count = await all_links.count()

        for i in range(links_count):

            try:

                href = await all_links.nth(i).get_attribute("href")

                text = (
                    await all_links.nth(i).inner_text()
                ).strip()

                if not href:
                    continue

                # пропускаем мусор
                if (
                    "facebook" in href.lower()
                    or "instagram" in href.lower()
                    or "linkedin" in href.lower()
                    or "twitter" in href.lower()
                    or text.lower() == "home"
                ):
                    continue

                # только внутренние ссылки
                if href.startswith("/"):

                    full_link = (
                        "https://www.campusgroningen.com"
                        + href
                    )

                elif href.startswith(
                    "https://www.campusgroningen.com"
                ):

                    full_link = href

                else:
                    continue

                # исключаем dashboard страницы
                if (
                    "/dashboard/" in full_link
                    or "/mijn-favorieten" in full_link
                ):
                    continue

                # только уникальные
                if full_link not in apartment_links:

                    apartment_links.append(full_link)

            except:
                pass

        log(
            f"📋 Найдено объявлений: {len(apartment_links)}"
        )

        found_any = False

        for index, apartment_url in enumerate(apartment_links, start=1):

            try:

                log(
                    f"🔍 Проверяю объявление #{index}"
                )

                log(f"🔗 {apartment_url}")

                await page.goto(
                    apartment_url,
                    wait_until="domcontentloaded",
                    timeout=60000
                )

                await page.wait_for_timeout(5000)

                page_text = (
                    await page.content()
                ).lower()

                title = "Неизвестное объявление"

                try:

                    h1 = page.locator("h1")

                    if await h1.count() > 0:

                        title = (
                            await h1.first.inner_text()
                        ).strip()

                except:
                    pass

                log(f"🏠 {title}")

                join_selectors = [

                    'button:has-text("Deelnemen")',
                    'button:has-text("Inschrijven")',
                    'a:has-text("Deelnemen")',
                    'a:has-text("Inschrijven")',
                    'button:has-text("Participate")',
                    'button:has-text("Join")',
                    'a:has-text("Participate")',
                    'a:has-text("Join")'

                ]

                has_join_button = False

                for selector in join_selectors:

                    try:

                        locator = page.locator(selector)

                        count = await locator.count()

                        if count > 0:

                            visible = await locator.first.is_visible()

                            if visible:

                                has_join_button = True

                                log(
                                    f"✅ Найдена кнопка: {selector}"
                                )

                                break

                    except:
                        pass

                # fallback по тексту
                if not has_join_button:

                    checks = [

                        "deelnemen",
                        "inschrijven",
                        "bezichtiging",
                        "viewing",
                        "participate",
                        "join"

                    ]

                    for word in checks:

                        if word in page_text:

                            has_join_button = True

                            log(
                                f"✅ Найден текст: {word}"
                            )

                            break

                if has_join_button:

                    found_any = True

                    if apartment_url not in sent_links:

                        sent_links.add(apartment_url)

                        log(
                            f"🚨 ДОСТУПНА ЗАПИСЬ НА ПРОСМОТР!\n\n"
                            f"🏠 {title}\n\n"
                            f"🔗 {apartment_url}"
                        )

                    else:

                        log(
                            "ℹ️ Уже отправлялось"
                        )

                else:

                    log("❌ Записи нет")

            except Exception as e:

                log(
                    f"⚠️ Ошибка проверки объявления: {e}"
                )

        log(
            f"✅ Проверено объявлений: {len(apartment_links)}"
        )

        if not found_any:

            log("😴 Свободных записей пока нет")

    except Exception as e:

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
                                "⚠️ Пропускаю проверку из-за ошибки логина"
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
