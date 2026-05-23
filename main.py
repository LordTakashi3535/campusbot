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
# UI STATE (НОВОЕ)
# =========================

BOT_STATE = {
    "running": False,
    "action": "Ожидание...",
    "checked": 0,
    "last_found": None
}

STATUS_MESSAGE_ID = None


# =========================
# STATUS UI
# =========================

def get_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("▶️ Запуск", callback_data="start"),
            InlineKeyboardButton("⏹ Стоп", callback_data="stop")
        ]
    ])


def get_status_text():

    status = "🟢 ВКЛЮЧЕН" if BOT_STATE["running"] else "🔴 ВЫКЛЮЧЕН"

    return (
        "🤖 Campus Bot\n\n"
        f"Статус: {status}\n"
        f"📍 Действие: {BOT_STATE['action']}\n"
        f"🏠 Проверено квартир: {BOT_STATE['checked']}"
    )


def set_action(text):
    BOT_STATE["action"] = text


async def update_status(context=None):

    global STATUS_MESSAGE_ID

    if not STATUS_MESSAGE_ID:
        return

    try:
        context.bot.edit_message_text(
            chat_id=TELEGRAM_CHAT_ID,
            message_id=STATUS_MESSAGE_ID,
            text=get_status_text(),
            reply_markup=get_keyboard()
        )
    except:
        pass


# =========================
# TELEGRAM UI
# =========================

def start_command(update: Update, context: CallbackContext):

    global STATUS_MESSAGE_ID

    msg = update.message.reply_text(
        get_status_text(),
        reply_markup=get_keyboard()
    )

    STATUS_MESSAGE_ID = msg.message_id


def button_handler(update: Update, context: CallbackContext):

    query = update.callback_query
    query.answer()

    if query.data == "start":
        BOT_STATE["running"] = True
        BOT_STATE["action"] = "Запущен"

    elif query.data == "stop":
        BOT_STATE["running"] = False
        BOT_STATE["action"] = "Остановлен"

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
# LOGIN (НЕ ИЗМЕНЯЛ)
# =========================

async def login(page):

    try:

        set_action("Открываю сайт...")

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
            set_action("Уже авторизован")
            return True

        login_button = page.locator("text=Inloggen")

        if await login_button.count() == 0:
            return False

        set_action("Логин...")

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
        set_action("Ошибка login")
        return False


# =========================
# CHECK (ТВОЯ ФУНКЦИЯ БЕЗ ИЗМЕНЕНИЙ ЛОГИКИ)
# =========================

async def check_apartments(page):

    global sent_links

    try:

        set_action("Открываю избранное...")

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

        set_action("Сканирую объявления...")

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

            except:
                pass

        BOT_STATE["checked"] = len(apartment_links)

        found_any = False

        for index, apartment in enumerate(apartment_links, start=1):

            set_action(f"Проверяю {index}/{len(apartment_links)}")

            apartment_url = apartment["url"]
            title = apartment["title"]

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
                        break

            except:
                pass

            if has_join_button:

                found_any = True

                if apartment_url not in sent_links:

                    sent_links.add(apartment_url)

                    set_action("🚨 Найдена квартира!")

            else:
                pass

        if not found_any:
            set_action("Свободных записей нет")

    except:
        set_action("Ошибка проверки")


# =========================
# MAIN LOOP
# =========================

async def main():

    threading.Thread(target=start_telegram_bot, daemon=True).start()

    while True:

        async with async_playwright() as p:

            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            while True:

                if not BOT_STATE["running"]:
                    await asyncio.sleep(2)
                    continue

                await update_status()

                success = await login(page)

                if success:
                    await check_apartments(page)

                await update_status()

                await asyncio.sleep(CHECK_INTERVAL)


asyncio.run(main())
