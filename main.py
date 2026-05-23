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
# LOG (НЕ ТРОГАЕМ ЛОГИКУ)
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
# UI STATUS
# =========================

def get_status_text():

    status = "🟢 ВКЛЮЧЕН" if BOT_RUNNING else "🔴 ВЫКЛЮЧЕН"

    return (
        "🤖 Campus Bot\n\n"
        f"Статус: {status}\n"
        f"⏳ Ожидание запуска..."
    )


def get_keyboard():

    keyboard = [
        [
            InlineKeyboardButton("▶️ Запуск", callback_data="start"),
            InlineKeyboardButton("⏹ Стоп", callback_data="stop")
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


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
# LOGIN (НЕ МЕНЯЛ)
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

        log("🔐 Логин...")

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
# CHECK (НЕ ТРОГАЛ ЛОГИКУ)
# =========================

async def check_apartments(page):

    global sent_links

    log("🏠 Открываю избранное...")

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

    for i in range(cards_count):

        card = cards.nth(i)
        card_text = (await card.inner_text()).lower()

        if "huurprijs" not in card_text:
            continue

        links = card.locator("a")
        links_count = await links.count()

        apartment_url = None
        apartment_title = None

        for j in range(links_count):

            link = links.nth(j)

            text = (await link.inner_text()).strip()
            href = await link.get_attribute("href")

            if not href:
                continue

            if "/woning/" not in href:
                continue

            apartment_title = text

            apartment_url = (
                "https://www.campusgroningen.com" + href
                if href.startswith("/")
                else href
            )

            break

        if not apartment_url:
            continue

        if apartment_url in processed_urls:
            continue

        processed_urls.add(apartment_url)

        apartment_links.append({
            "title": apartment_title,
            "url": apartment_url
        })

    for apartment in apartment_links:

        apartment_url = apartment["url"]
        title = apartment["title"]

        log(f"🔍 Проверяю: {title}")

        await page.goto(apartment_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)

        sidebar_text = (await page.content()).lower()

        has_join_button = any(
            word in sidebar_text for word in [
                "bezichtiging",
                "meld je aan",
                "deelnemen",
                "plan bezichtiging"
            ]
        )

        if has_join_button:

            if apartment_url not in sent_links:

                sent_links.add(apartment_url)

                log(
                    f"🚨 ДОСТУПНА ЗАПИСЬ!\n\n{title}\n{apartment_url}"
                )


# =========================
# MAIN LOOP (ДОБАВЛЕН ТОЛЬКО STOP/START)
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
