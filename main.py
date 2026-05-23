import os
import asyncio
import threading
import requests

from dotenv import load_dotenv
from playwright.async_api import async_playwright

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext

load_dotenv()

EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

CHECK_INTERVAL = 60

sent_links = set()

# =========================
# STATE
# =========================

BOT_STATE = {
    "running": False,
    "action": "Ожидание...",
    "current_apartment": "-",
    "checked_live": 0,
    "checked_final": 0,
    "last_url": "-",
    "last_word": "-"
}

STATUS_MESSAGE_ID = None


# =========================
# TELEGRAM ALERT
# =========================

def send_telegram_alert(text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text
            },
            timeout=10
        )
    except:
        pass


# =========================
# UI
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
        f"🏠 Квартира: {BOT_STATE['current_apartment']}\n"
        f"📊 Проверено сейчас: {BOT_STATE['checked_live']}\n"
        f"📦 Всего (после стопа): {BOT_STATE['checked_final']}\n\n"
        f"🔎 DEBUG URL:\n{BOT_STATE['last_url']}\n\n"
        f"🔤 DEBUG WORD:\n{BOT_STATE['last_word']}"
    )


# =========================
# TELEGRAM MENU
# =========================

def start_command(update, context):

    global STATUS_MESSAGE_ID

    msg = update.message.reply_text(
        get_status_text(),
        reply_markup=get_keyboard()
    )

    STATUS_MESSAGE_ID = msg.message_id


def button_handler(update, context):

    query = update.callback_query
    query.answer()

    if query.data == "start":
        BOT_STATE["running"] = True
        BOT_STATE["action"] = "Запущен"

    elif query.data == "stop":
        BOT_STATE["running"] = False
        BOT_STATE["action"] = "Остановлен"
        BOT_STATE["checked_final"] = BOT_STATE["checked_live"]

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
# LOGIN (без изменений логики)
# =========================

async def login(page):

    BOT_STATE["action"] = "Логин..."

    await page.goto(
        "https://www.campusgroningen.com",
        wait_until="domcontentloaded",
        timeout=60000
    )

    await page.wait_for_timeout(5000)

    page_text = (await page.content()).lower()
    current_url = page.url.lower()

    if (
        "uitloggen" in page_text
        or "mijn favorieten" in page_text
        or "dashboard" in current_url
        or "mijncampus" in page_text
    ):
        BOT_STATE["action"] = "Уже авторизован"
        return True

    login_button = page.locator("text=Inloggen")

    if await login_button.count() == 0:
        return False

    await login_button.first.click(force=True)
    await page.wait_for_timeout(5000)

    await page.locator('input[type="email"]').first.fill(EMAIL)
    await page.locator('input[type="password"]').first.fill(PASSWORD)

    await page.locator('input[type="password"]').first.press("Enter")

    await page.wait_for_timeout(10000)

    return True


# =========================
# CHECK APARTMENTS
# =========================

async def check_apartments(page):

    global sent_links

    BOT_STATE["checked_live"] = 0
    BOT_STATE["action"] = "Открываю избранное..."

    await page.goto(
        "https://www.campusgroningen.com/dashboard/mijn-favorieten",
        wait_until="domcontentloaded",
        timeout=60000
    )

    await page.wait_for_timeout(5000)

    cards = page.locator(".row")
    cards_count = await cards.count()

    BOT_STATE["action"] = "Сканирую квартиры..."

    apartment_links = []
    processed_urls = set()

    for i in range(cards_count):

        card = cards.nth(i)
        card_text = (await card.inner_text()).lower()

        if "huurprijs" not in card_text:
            continue

        links = card.locator("a")

        for j in range(await links.count()):

            link = links.nth(j)

            text = (await link.inner_text()).strip()
            href = await link.get_attribute("href")

            if not href:
                continue

            if "/woning/" not in href:
                continue

            url = (
                "https://www.campusgroningen.com" + href
                if href.startswith("/")
                else href
            )

            apartment_links.append({
                "title": text,
                "url": url
            })

            break

    BOT_STATE["checked_live"] = len(apartment_links)

    found_any = False

    for index, apartment in enumerate(apartment_links, start=1):

        if not BOT_STATE["running"]:
            return

        title = apartment["title"]
        url = apartment["url"]

        BOT_STATE["current_apartment"] = title
        BOT_STATE["action"] = f"Проверяю {title}"

        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)

        has_join_button = False
        matched_word = None

        try:

            sidebar = page.locator("text=Interesse in deze woning?").first
            await sidebar.wait_for(timeout=10000)

            sidebar = sidebar.locator("xpath=../../..")
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
                    matched_word = word
                    break

        except:
            pass

        if has_join_button and url not in sent_links:

            sent_links.add(url)

            BOT_STATE["action"] = "🚨 Найдена регистрация"
            BOT_STATE["last_url"] = url
            BOT_STATE["last_word"] = matched_word

            # 🔥 ВОТ ТВОЁ УВЕДОМЛЕНИЕ
            send_telegram_alert(
                "🚨 Найдена регистрация на просмотр!\n\n"
                f"🏠 {title}\n"
                f"🔗 {url}\n"
                f"🔤 Слово: {matched_word}"
            )

            found_any = True

        BOT_STATE["checked_live"] = index

        await asyncio.sleep(0)

    if not found_any:
        BOT_STATE["action"] = "Свободных записей нет"


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

                await login(page)
                await check_apartments(page)

                await asyncio.sleep(CHECK_INTERVAL)


asyncio.run(main())
