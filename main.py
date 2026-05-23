import os
import asyncio
import threading
import requests

from dotenv import load_dotenv
from playwright.async_api import async_playwright

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler

load_dotenv()

EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

CHECK_INTERVAL = 60

# =========================
# USERS
# =========================

users = set()
ADMIN_CHAT_ID = None

# =========================
# BOT STATE
# =========================

BOT_STATE = {
    "running": False,
    "action": "Oczekiwanie..."
}

STATUS_MESSAGE_ID = None
lock = threading.Lock()


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
        f"Status: {status}\n"
        f"📍 Działanie:\n{BOT_STATE['action']}"
    )


# =========================
# ALERT (ALWAYS SEND)
# =========================

def send_telegram_alert(text):
    for chat_id in list(users):
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text
                }
            )
        except:
            pass


# =========================
# STATUS UPDATE (FIXED)
# =========================

def set_action(text):

    global STATUS_MESSAGE_ID

    with lock:
        BOT_STATE["action"] = text

    if not ADMIN_CHAT_ID or not STATUS_MESSAGE_ID:
        return

    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText",
            json={
                "chat_id": ADMIN_CHAT_ID,
                "message_id": STATUS_MESSAGE_ID,
                "text": get_status_text(),
                "reply_markup": get_keyboard().to_dict()
            }
        )
    except:
        pass


# =========================
# TELEGRAM HANDLERS
# =========================

def start_command(update: Update, context):
    global ADMIN_CHAT_ID, STATUS_MESSAGE_ID

    chat_id = update.effective_chat.id

    users.add(chat_id)

    if ADMIN_CHAT_ID is None:
        ADMIN_CHAT_ID = chat_id

    msg = update.message.reply_text(
        get_status_text(),
        reply_markup=get_keyboard()
    )

    STATUS_MESSAGE_ID = msg.message_id


def button_handler(update: Update, context):

    query = update.callback_query
    query.answer()

    if query.data == "start":
        BOT_STATE["running"] = True
        set_action("▶️ Uruchomiony")

    elif query.data == "stop":
        BOT_STATE["running"] = False
        set_action("⏹ Zatrzymany")

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
# CHECK (ALWAYS NOTIFY)
# =========================

async def check_apartments(page):

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

        # 🚨 ALWAYS SEND (NO ANTI-DUPLICATE)
        if found:

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

    await asyncio.sleep(2)

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
