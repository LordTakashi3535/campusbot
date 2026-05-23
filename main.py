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

CHECK_INTERVAL = 60  # 5 минут

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

        page_text = (
            await page.content()
        ).lower()

        # ==========================================
        # УЖЕ АВТОРИЗОВАН
        # ==========================================

        if (
            "uitloggen" in page_text
            or "mijn favorieten" in page_text
            or "dashboard" in current_url
            or "mijncampus" in page_text
        ):

            log("✅ Уже авторизован")

            return True

        # ==========================================
        # COOKIES
        # ==========================================

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

        # ==========================================
        # ОТКРЫВАЕМ ЛОГИН
        # ==========================================

        login_button = page.locator(
            "text=Inloggen"
        )

        login_count = await login_button.count()

        if login_count == 0:

            log(
                "⚠️ Кнопка логина не найдена"
            )

            return False

        log("🔐 Открываю окно логина...")

        await login_button.first.click(
            force=True,
            timeout=30000
        )

        await page.wait_for_timeout(5000)

        # ==========================================
        # EMAIL
        # ==========================================

        log("📧 Ввожу email...")

        email_input = page.locator(
            'input[type="email"]'
        ).first

        await email_input.fill(EMAIL)

        # ==========================================
        # PASSWORD
        # ==========================================

        log("🔑 Ввожу пароль...")

        password_input = page.locator(
            'input[type="password"]'
        ).first

        await password_input.fill(PASSWORD)

        await page.wait_for_timeout(2000)

        # ==========================================
        # ENTER
        # ==========================================

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
            or "mijncampus" in page_text

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

        # ==========================================
        # ИЩЕМ КАРТОЧКИ КВАРТИР
        # ==========================================

        apartment_links = []
        processed_urls = set()

        cards = page.locator(".row")

        cards_count = await cards.count()

        log(f"📦 Всего row блоков: {cards_count}")

        for i in range(cards_count):

            try:

                card = cards.nth(i)

                card_text = (
                    await card.inner_text()
                ).lower()

                # Только реальные карточки квартир
                if (
                    "huurprijs" not in card_text
                    or "toegevoegd op" not in card_text
                ):
                    continue

                links = card.locator("a")

                links_count = await links.count()

                apartment_url = None
                apartment_title = None

                for j in range(links_count):

                    try:

                        link = links.nth(j)

                        text = (
                            await link.inner_text()
                        ).strip()

                        href = await link.get_attribute(
                            "href"
                        )

                        if not href:
                            continue

                        if not text:
                            continue

                        text_lower = text.lower()

                        # Пропускаем мусор
                        if (
                            "favoriet" in text_lower
                            or "verwijderen" in text_lower
                            or "facebook" in text_lower
                            or "instagram" in text_lower
                            or "linkedin" in text_lower
                        ):
                            continue

                        # Только реальные квартиры
                        if (
                            "/woning/" not in href
                            and "/aanbod/" not in href
                        ):
                            continue

                        apartment_title = text

                        if href.startswith("/"):

                            apartment_url = (
                                "https://www.campusgroningen.com"
                                + href
                            )

                        else:

                            apartment_url = href

                        break

                    except:
                        pass

                if not apartment_url:
                    continue

                # Убираем дубли
                if apartment_url in processed_urls:
                    continue

                processed_urls.add(apartment_url)

                apartment_links.append({

                    "title": apartment_title,
                    "url": apartment_url

                })

            except Exception as e:

                log(
                    f"⚠️ Ошибка карточки: {e}"
                )

        log(
            f"✅ Найдено объявлений: {len(apartment_links)}"
        )

        # ==========================================
        # ПРОВЕРЯЕМ КАЖДУЮ КВАРТИРУ
        # ==========================================

        found_any = False

        for index, apartment in enumerate(
            apartment_links,
            start=1
        ):

            try:

                apartment_url = apartment["url"]
                title = apartment["title"]

                log(
                    f"🔍 Проверяю объявление #{index}"
                )

                log(f"🏠 {title}")

                log(f"🔗 {apartment_url}")

                await page.goto(
                    apartment_url,
                    wait_until="domcontentloaded",
                    timeout=60000
                )

                await page.wait_for_timeout(5000)

                # ==========================================
                # ИЩЕМ КНОПКУ ТОЛЬКО В ПРАВОМ SIDEBAR
                # ==========================================

                has_join_button = False

                try:

                    sidebar = page.locator(
                        ".object-sidebar"
                    ).first

                    await sidebar.wait_for(
                        timeout=10000
                    )

                    sidebar_text = (
                        await sidebar.inner_text()
                    ).lower()

                    log("📋 Проверяю sidebar...")

                    log(
                        f"📄 Sidebar text:\n"
                        f"{sidebar_text}"
                    )

                    # ==========================================
                    # ИЩЕМ РЕАЛЬНЫЕ КНОПКИ ЗАПИСИ
                    # ==========================================

                    register_words = [

                        "bezichtiging",
                        "deelnemen",
                        "plan bezichtiging",
                        "beschikbare kijkmomenten",
                        "meld je aan"

                    ]

                    for word in register_words:

                        if word in sidebar_text:

                            has_join_button = True

                            log(
                                f"✅ Найдена запись: {word}"
                            )

                            break

                except Exception as e:

                    log(
                        f"⚠️ Ошибка sidebar: {e}"
                    )

                # ==========================================
                # УВЕДОМЛЕНИЕ
                # ==========================================

                if has_join_button:

                    found_any = True

                    if (
                        apartment_url
                        not in sent_links
                    ):

                        sent_links.add(
                            apartment_url
                        )

                        log(
                            f"🚨 ДОСТУПНА ЗАПИСЬ НА ПРОСМОТР!\n\n"
                            f"🏠 {title}\n\n"
                            f"🔗 {apartment_url}"
                        )

                    else:

                        log(
                            "ℹ️ Уже отправлялось ранее"
                        )

                else:

                    log("❌ Записи нет")

            except Exception as e:

                log(
                    f"⚠️ Ошибка проверки объявления: {e}"
                )

        log(
            f"✅ Проверено объявлений: "
            f"{len(apartment_links)}"
        )

        if not found_any:

            log(
                "😴 Свободных записей пока нет"
            )

    except Exception as e:

        try:

            await page.screenshot(
                path="favorites_error.png",
                full_page=True
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
                                "⚠️ Пропускаю проверку из-за ошибки логина"
                            )

                        log(
                            f"⏳ Ожидание {CHECK_INTERVAL} секунд..."
                        )

                    except Exception as e:

                        log(
                            f"⚠️ Ошибка цикла: {e}"
                        )

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
