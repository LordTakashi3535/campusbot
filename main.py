import os
import asyncio
import threading
import requests

from dotenv import load_dotenv
from playwright.async_api import async_playwright

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler

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
    "current_apartment": "-"
}

STATUS_MESSAGE_ID = None


# =========================
# ALERT
# =========================

def send_telegram_alert(text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
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
        f"📍 Действие: {BOT_STATE['action']}"
    )


async def update_menu(context):
    global STATUS_MESSAGE_ID

    if not STATUS_MESSAGE_ID:
        return

    try:
        await context.bot.edit_message_text(
            chat_id=TELEGRAM_CHAT_ID,
            message_id=STATUS_MESSAGE_ID,
            text=get_status_text(),
            reply_markup=get_keyboard()
        )
    except:
        pass


# =========================
# TELEGRAM
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
# LOGIN
# =========================

async def login(page):

    BOT_STATE["action"] = "Логин..."

    await page.goto(
        "https://www.campusgroningen.com",
        wait_until="domcontentloaded",
        timeout=60000
    )

    await page.wait_for_timeout(5000)

    if "uitloggen" in (await page.content()).lower():
        BOT_STATE["action"] = "Уже авторизован"
        return True

    login_button = page.locator("text=Inloggen")

    if await login_button.count() == 0:
        return False

    await login_button.first.click(force=True)
    await page.wait_for_timeout(3000)

    await page.locator('input[type="email"]').first.fill(EMAIL)
    await page.locator('input[type="password"]').first.fill(PASSWORD)
    await page.locator('input[type="password"]').first.press("Enter")

    await page.wait_for_timeout(8000)

    return True


# =========================
# CHECK
# =========================

async def check_apartments(page):

    global sent_links

    await page.goto(
        "https://www.campusgroningen.com/dashboard/mijn-favorieten",
        wait_until="domcontentloaded",
        timeout=60000
    )

    await page.wait_for_timeout(4000)

    cards = page.locator(".row")
    count = await cards.count()

    apartment_links = []

    for i in range(count):

        card = cards.nth(i)

        if "huurprijs" not in (await card.inner_text()).lower():
            continue

        links = card.locator("a")

        for j in range(await links.count()):

            link = links.nth(j)

            href = await link.get_attribute("href")
            text = await link.inner_text()

            if href and "/woning/" in href:

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

    for i, apt in enumerate(apartment_links, start=1):

        if not BOT_STATE["running"]:
            return

        BOT_STATE["current_apartment"] = apt["title"]
        BOT_STATE["action"] = f"Проверяю: {apt['title']}"

        await page.goto(apt["url"])
        await page.wait_for_timeout(4000)

        sidebar = page.locator("text=Interesse in deze woning?").first

        has_join = False
        matched_word = None

        try:
            await sidebar.wait_for(timeout=8000)
            text = (await sidebar.locator("xpath=../../..").inner_text()).lower()

            words = [
                "stel een vraag",
                "bezichtiging",
                "deelnemen",
                "plan bezichtiging",
                "beschikbare kijkmomenten",
                "meld je aan"
            ]

            for w in words:
                if w in text:
                    has_join = True
                    matched_word = w
                    break

        except:
            pass

        if has_join and apt["url"] not in sent_links:

            sent_links.add(apt["url"])

            BOT_STATE["action"] = f"🚨 НАЙДЕНО: {apt['title']}"

            send_telegram_alert(
                "🚨 Найдена регистрация!\n\n"
                f"🏠 {apt['title']}\n"
                f"🔗 {apt['url']}\n"
                f"🔤 {matched_word}"
            )

        # 🔥 ВАЖНО: обновляем меню КАЖДЫЙ цикл
        await update_menu(None)

    BOT_STATE["action"] = "Проверка завершена"


# =========================
# MAIN
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
