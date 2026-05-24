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

CHECK_INTERVAL = 300

# =========================
# USERS
# =========================

users = set()

OWNER_CHAT_ID = None

STATUS_MESSAGES = {}

# =========================
# BOT STATE
# =========================

BOT_STATE = {
    "running": False,
    "action": "Oczekiwanie...",
    "search_cycles": 0,
    "favorites_count": 0,
    "buttons_count": 0,
    "countdown": CHECK_INTERVAL
}

# =========================
# BUTTON TRACKING
# =========================

LAST_BUTTON_COUNT = 0

lock = threading.Lock()

browser = None
page = None


# =========================
# UI
# =========================

def get_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "▶️ Start",
                callback_data="start"
            ),

            InlineKeyboardButton(
                "⏹ Stop",
                callback_data="stop"
            )
        ]
    ])


def get_status_text():

    status = (
        "🟢 WŁĄCZONY"
        if BOT_STATE["running"]
        else "🔴 WYŁĄCZONY"
    )

    return (
        "🤖 Campus Bot\n\n"
        f"Status: {status}\n"
        f"🔄 Cykle wyszukiwania: "
        f"{BOT_STATE['search_cycles']}\n"
        f"🏠 Mieszkań w ulubionych: "
        f"{BOT_STATE['favorites_count']}\n"
        f"🔘 Buttons: "
        f"{BOT_STATE['buttons_count']}\n\n"
        f"{BOT_STATE['action']}"
    )


# =========================
# ALERTS
# =========================

def send_telegram_alert(text):

    for chat_id in list(users):

        try:

            requests.post(
                f"https://api.telegram.org/bot"
                f"{TELEGRAM_TOKEN}/sendMessage",

                json={
                    "chat_id": chat_id,
                    "text": text,
                    "disable_web_page_preview": True
                }
            )

        except:
            pass


def send_log_message(text):

    global OWNER_CHAT_ID

    if not OWNER_CHAT_ID:
        return

    try:

        requests.post(
            f"https://api.telegram.org/bot"
            f"{TELEGRAM_TOKEN}/sendMessage",

            json={
                "chat_id": OWNER_CHAT_ID,
                "text": text,
                "disable_web_page_preview": True
            }
        )

    except:
        pass


# =========================
# STATUS UPDATE
# =========================

def set_action(text):

    with lock:
        BOT_STATE["action"] = text

    for chat_id, message_id in list(
        STATUS_MESSAGES.items()
    ):

        try:

            requests.post(
                f"https://api.telegram.org/bot"
                f"{TELEGRAM_TOKEN}/editMessageText",

                json={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": get_status_text(),
                    "reply_markup": (
                        get_keyboard().to_dict()
                    )
                }
            )

        except:
            pass


# =========================
# RESET BROWSER
# =========================

async def reset_browser():

    global browser, page

    try:
        if page:
            await page.close()
    except:
        pass

    try:
        if browser:
            await browser.close()
    except:
        pass

    try:

        playwright = (
            await async_playwright().start()
        )

        browser = (
            await playwright.chromium.launch(
                headless=True
            )
        )

        page = await browser.new_page()

    except:
        pass


# =========================
# TELEGRAM
# =========================

def start_command(update: Update, context):

    global OWNER_CHAT_ID

    chat_id = update.effective_chat.id

    users.add(chat_id)

    if OWNER_CHAT_ID is None:
        OWNER_CHAT_ID = chat_id

    msg = update.message.reply_text(
        get_status_text(),
        reply_markup=get_keyboard()
    )

    STATUS_MESSAGES[chat_id] = msg.message_id


def button_handler(update: Update, context):

    query = update.callback_query

    query.answer()

    if query.data == "start":

        BOT_STATE["running"] = True
        BOT_STATE["countdown"] = CHECK_INTERVAL

        set_action("▶️ Uruchomiony")

    elif query.data == "stop":

        BOT_STATE["running"] = False
        BOT_STATE["countdown"] = 0

        set_action("⏹ Zatrzymany")

    query.edit_message_text(
        text=get_status_text(),
        reply_markup=get_keyboard()
    )


def start_telegram_bot():

    updater = Updater(
        TELEGRAM_TOKEN,
        use_context=True
    )

    dp = updater.dispatcher

    dp.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )

    dp.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    updater.start_polling()

    updater.idle()


# =========================
# LOGIN
# =========================

async def login():

    global page

    set_action(
        "🌐 Otwieram stronę..."
    )

    await page.goto(
        "https://www.campusgroningen.com",
        wait_until="domcontentloaded"
    )

    await page.wait_for_timeout(3000)

    if "uitloggen" in (
        await page.content()
    ).lower():

        set_action(
            "✅ Już zalogowany"
        )

        return True

    set_action(
        "🔐 Logowanie..."
    )

    await page.locator(
        "text=Inloggen"
    ).first.click(force=True)

    await page.wait_for_timeout(2000)

    await page.locator(
        'input[type="email"]'
    ).first.fill(EMAIL)

    await page.locator(
        'input[type="password"]'
    ).first.fill(PASSWORD)

    await page.locator(
        'input[type="password"]'
    ).first.press("Enter")

    await page.wait_for_timeout(8000)

    set_action(
        "✅ Login OK"
    )

    return True


# =========================
# CHECK APARTMENTS
# =========================

async def check_apartments():

    global page
    global LAST_BUTTON_COUNT

    await page.goto(
        "https://www.campusgroningen.com/"
        "dashboard/mijn-favorieten",
        wait_until="domcontentloaded"
    )

    await page.wait_for_load_state(
        "networkidle"
    )

    await page.wait_for_timeout(3000)

    cards = page.locator(".row")

    count = await cards.count()

    apartments = []

    # =========================
    # GET APARTMENTS
    # =========================

    for i in range(count):

        card = cards.nth(i)

        try:

            card_text = (
                await card.inner_text()
            ).lower()

        except:
            continue

        if "huurprijs" not in card_text:
            continue

        links = card.locator("a")

        for j in range(
            await links.count()
        ):

            link = links.nth(j)

            href = await link.get_attribute(
                "href"
            )

            text = await link.inner_text()

            if href and "/woning/" in href:

                url = (
                    "https://www.campusgroningen.com"
                    + href
                    if href.startswith("/")
                    else href
                )

                apartments.append({
                    "title": text,
                    "url": url
                })

                break

    BOT_STATE["favorites_count"] = (
        len(apartments)
    )

    total_buttons = 0

    # =========================
    # CHECK EVERY APARTMENT
    # =========================

    for i, apt in enumerate(
        apartments,
        start=1
    ):

        if not BOT_STATE["running"]:
            return

        set_action(
            f"🏠 {i}/{len(apartments)}\n"
            f"{apt['title']}"
        )

        await page.goto(
            apt["url"],
            wait_until="domcontentloaded"
        )

        await page.wait_for_load_state(
            "networkidle"
        )

        await page.wait_for_timeout(5000)

        # =========================
        # COUNT BUTTONS
        # =========================

        button_selectors = [
            "button",
            "a.btn",
            "a.button",
            "[role='button']",
            "input[type='submit']"
        ]

        button_count = 0

        for selector in button_selectors:

            try:

                locator = page.locator(
                    selector
                )

                count = await locator.count()

                button_count += count

            except:
                pass

        total_buttons += button_count

    # =========================
    # SAVE BUTTON COUNT
    # =========================

    BOT_STATE["buttons_count"] = (
        total_buttons
    )

    # =========================
    # NEW BUTTON DETECTED
    # =========================

    if (
        LAST_BUTTON_COUNT != 0
        and total_buttons > LAST_BUTTON_COUNT
    ):

        send_log_message(
            "🚨 NOWY BUTTON!\n\n"
            f"🔘 Buttons: "
            f"{LAST_BUTTON_COUNT}"
            f" -> {total_buttons}"
        )

    LAST_BUTTON_COUNT = total_buttons


# =========================
# MAIN LOOP
# =========================

async def main():

    global browser, page

    threading.Thread(
        target=start_telegram_bot,
        daemon=True
    ).start()

    await asyncio.sleep(2)

    playwright = (
        await async_playwright().start()
    )

    browser = (
        await playwright.chromium.launch(
            headless=True
        )
    )

    page = await browser.new_page()

    set_action(
        "⏳ Oczekiwanie na Start"
    )

    while True:

        try:

            if not BOT_STATE["running"]:

                await asyncio.sleep(1)

                continue

            ok = await login()

            if ok:

                await check_apartments()

                BOT_STATE["search_cycles"] += 1

                set_action(
                    f"✅ Skończono cykl "
                    f"#{BOT_STATE['search_cycles']}"
                )

            # =========================
            # COUNTDOWN
            # =========================

            for remaining in range(
                CHECK_INTERVAL,
                0,
                -30
            ):

                if not BOT_STATE["running"]:

                    break

                BOT_STATE["countdown"] = remaining

                set_action(
                    f"😴 Oczekiwanie "
                    f"{remaining}s"
                )

                await asyncio.sleep(30)

        except Exception as e:

            error_text = str(e)

            set_action(
                f"❌ Błąd: {error_text}"
            )

            send_log_message(
                "❌ ERROR\n\n"
                f"{error_text}"
            )

            await reset_browser()

            await asyncio.sleep(10)


asyncio.run(main())
