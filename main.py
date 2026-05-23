import os
import asyncio
from datetime import datetime
import threading

import requests
from dotenv import load_dotenv
from playwright.async_api import async_playwright

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext

load_dotenv()

EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

CHECK_INTERVAL = 60

sent_links = set()

# =========================
# UI STATE
# =========================

BOT_RUNNING = False
STATUS_MESSAGE_ID = None


# =========================
# LOG (НЕ МЕНЯЛ)
# =========================

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


# =========================
# UI (start / stop)
# =========================

def get_status_text():

    status = "🟢 ВКЛЮЧЕН" if BOT_RUNNING else "🔴 ВЫКЛЮЧЕН"

    return (
        "🤖 Campus Bot\n\n"
        f"Статус: {status}\n"
        f"⏳ Ожидание..."
    )


def get_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("▶️ Запуск", callback_data="start"),
            InlineKeyboardButton("⏹ Стоп", callback_data="stop")
        ]
    ])


def start_command(update: Update, context: CallbackContext):

    global STATUS_MESSAGE_ID

    msg = update.message.reply_text(
        get_status_text(),
        reply_markup=get_keyboard()
    )

    STATUS_MESSAGE_ID = msg.message_id


def button_handler(update: Update, context: CallbackContext):

    global BOT_RUNNING

    query = update.callback_query
    query.answer()

    if query.data == "start":
        BOT_RUNNING = True

    elif query.data == "stop":
        BOT_RUNNING = False

    query.edit_message_text(
        text=get_status_text(),
        reply_markup=get_keyboard()
    )


def start_telegram_bot():

    updater = Updater(TELEGRAM_TOKEN, use_context=True)

    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start_command))
    dp.add_handler(CallbackQueryHandler(button_handler))

    updater.start_polling()
    updater.idle()


# =========================
# LOGIN (ТВОЙ БЕЗ ИЗМЕНЕНИЙ)
# =========================

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

        page_text = (await page.content()).lower()

        if (
            "uitloggen" in page_text
            or "mijn favorieten" in page_text
            or "dashboard" in current_url
            or "mijncampus" in page_text
        ):
            log("✅ Уже авторизован")
            return True

        login_button = page.locator("text=Inloggen")

        if await login_button.count() == 0:
            return False

        log("🔐 Открываю логин...")

        await login_button.first.click(force=True)
        await page.wait_for_timeout(5000)

        await page.locator('input[type="email"]').first.fill(EMAIL)
        await page.locator('input[type="password"]').first.fill(PASSWORD)

        await page.locator('input[type="password"]').first.press("Enter")

        await page.wait_for_timeout(10000)

        page_text = (await page.content()).lower()

        return (
            "uitloggen" in page_text
            or "mijn favorieten" in page_text
            or "dashboard" in page.url.lower()
        )

    except Exception as e:
        log(f"❌ Ошибка login: {e}")
        return False


# =========================
# CHECK (ТВОЯ ФУНКЦИЯ 1 В 1)
# =========================

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
        processed_urls = set()

        cards = page.locator(".row")

        cards_count = await cards.count()

        log(f"📦 Всего row блоков: {cards_count}")

        for i in range(cards_count):

            try:

                card = cards.nth(i)

                card_text = (await card.inner_text()).lower()

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

                        text = (await link.inner_text()).strip()
                        href = await link.get_attribute("href")

                        if not href or not text:
                            continue

                        text_lower = text.lower()

                        if (
                            "favoriet" in text_lower
                            or "verwijderen" in text_lower
                            or "facebook" in text_lower
                            or "instagram" in text_lower
                            or "linkedin" in text_lower
                        ):
                            continue

                        if (
                            "/woning/" not in href
                            and "/aanbod/" not in href
                        ):
                            continue

                        apartment_title = text

                        if href.startswith("/"):
                            apartment_url = "https://www.campusgroningen.com" + href
                        else:
                            apartment_url = href

                        break

                    except:
                        pass

                if not apartment_url:
                    continue

                if apartment_url in processed_urls:
                    continue

                processed_urls.add(apartment_url)

                apartment_links.append({
                    "title": apartment_title,
                    "url": apartment_url
                })

            except Exception as e:
                log(f"⚠️ Ошибка карточки: {e}")

        log(f"✅ Найдено объявлений: {len(apartment_links)}")

        found_any = False

        for index, apartment in enumerate(apartment_links, start=1):

            try:

                apartment_url = apartment["url"]
                title = apartment["title"]

                log(f"🔍 Проверяю #{index}: {title}")

                await page.goto(apartment_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(5000)

                has_join_button = False

                try:

                    sidebar_title = page.locator(
                        "text=Interesse in deze woning?"
                    ).first

                    await sidebar_title.wait_for(timeout=10000)

                    sidebar = sidebar_title.locator("xpath=../../..")

                    sidebar_text = (await sidebar.inner_text()).lower()

                    log("📋 Sidebar найден")

                    register_words = [
                        "stel een vraag",
                        "bezichtiging",
                        "deelnemen",
                        "plan bezichtiging",
                        "beschikbare kijkmomenten",
                        "meld je aan"
                    ]

                    for word in register_words:
                        if word.lower() in sidebar_text:
                            has_join_button = True
                            log(f"✅ Найдено слово: {word}")
                            break

                except Exception as e:
                    log(f"⚠️ Ошибка sidebar: {e}")

                if has_join_button:

                    found_any = True

                    if apartment_url not in sent_links:

                        sent_links.add(apartment_url)

                        log(
                            f"🚨 ДОСТУПНА ЗАПИСЬ!\n\n"
                            f"{title}\n\n"
                            f"{apartment_url}"
                        )

                    else:
                        log("ℹ️ Уже отправлялось")

                else:
                    log("❌ Записи нет")

            except Exception as e:
                log(f"⚠️ Ошибка проверки: {e}")

        if not found_any:
            log("😴 Свободных записей нет")

    except Exception as e:
        log(f"❌ Ошибка страницы: {e}")


# =========================
# MAIN LOOP
# =========================

async def main():

    log("🚀 Бот запущен")

    while True:

        async with async_playwright() as p:

            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            while True:

                if not BOT_RUNNING:
                    await asyncio.sleep(2)
                    continue

                success = await login(page)

                if success:
                    await check_apartments(page)

                await asyncio.sleep(CHECK_INTERVAL)


# =========================
# START
# =========================

threading.Thread(target=start_telegram_bot, daemon=True).start()

asyncio.run(main())
