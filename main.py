import os
import asyncio
import threading
import time
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

CHECK_INTERVAL = 300

sent_links = set()

# =========================
# STATE
# =========================

BOT_STATE = {
    "running": False,
    "action": "Oczekiwanie..."
}

STATUS_MESSAGE_ID = None
updater = None
_last_update = 0


# =========================
# ALERT TELEGRAM
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
            InlineKeyboardButton("▶️ Start", callback_data="start"),
            InlineKeyboardButton("⏹ Stop", callback_data="stop")
        ]
    ])


def get_status_text():

    status = "🟢 WŁĄCZONY" if BOT_STATE["running"] else "🔴 WYŁĄCZONY"

    return (
        "🤖 Campus Bot\n\n"
        f"{status}\n"
        f"📍 Status:\n{BOT_STATE['action']}"
    )


# =========================
# SAFE UI UPDATE
# =========================

def set_action(text):

    global _last_update, updater, STATUS_MESSAGE_ID

    BOT_STATE["action"] = text

    now = time.time()

    if now - _last_update < 1.2:
        return

    _last_update = now

    if not updater or not STATUS_MESSAGE_ID:
        return

    try:
        updater.bot.edit_message_text(
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
        BOT_STATE["action"] = "▶️ Start"

    elif query.data == "stop":
        BOT_STATE["running"] = False
        BOT_STATE["action"] = "⏹ Stop"

    query.edit_message_text(
        text=get_status_text(),
        reply_markup=get_keyboard()
    )


def start_telegram_bot():

    global updater

    updater = Updater(TELEGRAM_TOKEN, use_context=True)

    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start_command))
    dp.add_handler(CallbackQueryHandler(button_handler))

    updater.start_polling()
    updater.idle()


# =========================
# LOGIN (bez zmian logiki)
# =========================

async def login(page):

    set_action("🌐 Otwieram stronę...")

    await page.goto(
        "https://www.campusgroningen.com",
        wait_until="domcontentloaded",
        timeout=60000
    )

    await page.wait_for_timeout(4000)

    if "uitloggen" in (await page.content()).lower():
        set_action("✅ Już zalogowany")
        return True

    set_action("🔐 Klikam Inloggen")

    login_button = page.locator("text=Inloggen")

    if await login_button.count() == 0:
        set_action("❌ Nie znaleziono przycisku logowania")
        return False

    await login_button.first.click(force=True)
    await page.wait_for_timeout(2000)

    set_action("📧 Wpisuję email")
    await page.locator('input[type="email"]').first.fill(EMAIL)

    set_action("🔑 Wpisuję hasło")
    await page.locator('input[type="password"]').first.fill(PASSWORD)

    set_action("⌨️ Wysyłam formularz")

    await page.locator('input[type="password"]').first.press("Enter")
    await page.wait_for_timeout(8000)

    set_action("✅ Logowanie zakończone")

    return True


# =========================
# CHECK (logika bez zmian)
# =========================

async def check_apartments(page):

    global sent_links

    await page.goto(
        "https://www.campusgroningen.com/dashboard/mijn-favorieten",
        wait_until="domcontentloaded"
    )

    await page.wait_for_timeout(3000)

    cards = page.locator(".row")
    count = await cards.count()

    set_action(f"📦 Znaleziono sekcji: {count}")

    apartments = []

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

                apartments.append({"title": text, "url": url})
                break

    for i, apt in enumerate(apartments, start=1):

        if not BOT_STATE["running"]:
            return

        set_action(f"🏠 Sprawdzam {i}/{len(apartments)}\n{apt['title']}")

        await page.goto(apt["url"])
        await page.wait_for_timeout(4000)

        sidebar = page.locator("text=Interesse in deze woning?").first

        found = False
        matched = None

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
                    found = True
                    matched = w
                    break

        except:
            pass

        if found and apt["url"] not in sent_links:

            sent_links.add(apt["url"])

            send_telegram_alert(
                "🚨 Dostępna rejestracja na oglądanie!\n\n"
                f"🏠 {apt['title']}\n"
                f"🔗 {apt['url']}\n"
                f"🔤 Słowo: {matched}"
            )


# =========================
# MAIN LOOP
# =========================

async def main():

    threading.Thread(target=start_telegram_bot, daemon=True).start()

    async with async_playwright() as p:

        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        set_action("⏳ Oczekiwanie na uruchomienie")

        while True:

            if not BOT_STATE["running"]:
                set_action("⏸ Bot zatrzymany — oczekiwanie na Start")
                await asyncio.sleep(2)
                continue

            set_action("🌐 Logowanie...")

            ok = await login(page)

            if ok:
                set_action("🔎 Sprawdzanie mieszkań...")
                await check_apartments(page)

            set_action(f"😴 Oczekiwanie {CHECK_INTERVAL}s")

            await asyncio.sleep(CHECK_INTERVAL)


asyncio.run(main())
