import os
import asyncio
import threading
import time
import requests

from dotenv import load_dotenv
from playwright.async_api import async_playwright

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler

load_dotenv()

EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
users = set(chat_id)

CHECK_INTERVAL = 60

sent_links = set()

# =========================
# STATE
# =========================

BOT_STATE = {
    "running": False,
    "action": "Oczekiwanie..."
}

STATUS_MESSAGE_ID = None
lock = threading.Lock()


# =========================
# TELEGRAM UI HELPERS
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
        f"Status: {status}\n"
        f"📍 Działanie:\n{BOT_STATE['action']}"
    )


# =========================
# SAFE TELEGRAM REQUEST
# =========================

def tg_send_or_edit(text, keyboard=True):
    global STATUS_MESSAGE_ID

    try:
        if STATUS_MESSAGE_ID is None:

            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": text,
                    "reply_markup": get_keyboard().to_dict() if keyboard else None
                }
            )

            STATUS_MESSAGE_ID = r.json()["result"]["message_id"]

        else:

            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText",
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "message_id": STATUS_MESSAGE_ID,
                    "text": text,
                    "reply_markup": get_keyboard().to_dict() if keyboard else None
                }
            )

    except:
        pass


# =========================
# STATUS UPDATE (FIXED)
# =========================

def set_action(text):

    with lock:
        BOT_STATE["action"] = text

    tg_send_or_edit(get_status_text())


# =========================
# ALERTS
# =========================

def send_telegram_alert(text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text
            }
        )
    except:
        pass


# =========================
# TELEGRAM BOT (BUTTONS ONLY)
# =========================

def start_command(update: Update, context):
    update.message.reply_text(
        get_status_text(),
        reply_markup=get_keyboard()
    )


def button_handler(update: Update, context):

    query = update.callback_query
    query.answer()

    if query.data == "start":
        BOT_STATE["running"] = True
        set_action("▶️ Uruchomiony")

    elif query.data == "stop":
        BOT_STATE["running"] = False
        set_action("⏹ Zatrzymany")


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

    set_action("🌐 Otwieram stronę...")

    await page.goto("https://www.campusgroningen.com", wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    if "uitloggen" in (await page.content()).lower():
        set_action("✅ Już zalogowany")
        return True

    set_action("🔐 Logowanie...")

    await page.locator("text=Inloggen").first.click(force=True)
    await page.wait_for_timeout(2000)

    await page.locator('input[type="email"]').first.fill(EMAIL)
    await page.locator('input[type="password"]').first.fill(PASSWORD)

    await page.locator('input[type="password"]').first.press("Enter")
    await page.wait_for_timeout(8000)

    set_action("✅ Login OK")

    return True


# =========================
# CHECK (НЕ ТРОГАЛ ЛОГИКУ)
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

        set_action(f"🏠 {i}/{len(apartments)}\n{apt['title']}")

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
                "🚨 Dostępna rejestracja!\n\n"
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

        set_action("⏳ Oczekiwanie na Start")

        while True:

            if not BOT_STATE["running"]:
                await asyncio.sleep(1)
                continue

            ok = await login(page)

            if ok:
                await check_apartments(page)

            set_action(f"😴 Oczekiwanie {CHECK_INTERVAL}s")

            await asyncio.sleep(CHECK_INTERVAL)


asyncio.run(main())
