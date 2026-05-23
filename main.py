import os
import asyncio
import threading
from datetime import datetime

import requests
from dotenv import load_dotenv
from playwright.async_api import async_playwright

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update
)

from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    CallbackContext
)

load_dotenv()

EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

CHECK_INTERVAL = 60

sent_links = set()

BOT_RUNNING = False
STATUS_MESSAGE_ID = None
LAST_ACTION = "Ожидание"
CHECKED_APARTMENTS = 0

SPECIAL_WORDS = [
    "bezichtiging",
    "deelnemen",
    "meld je aan",
    "plan bezichtiging"
]


def console_log(text):

    now = datetime.now().strftime("%H:%M:%S")

    print(f"[{now}] {text}")


def telegram_notify(text):

    try:

        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text
            },
            timeout=15
        )

    except Exception as e:

        print("Telegram error:", e)


def get_status_text():

    status = "🟢 ВКЛЮЧЕН" if BOT_RUNNING else "🔴 ВЫКЛЮЧЕН"

    return (
        "🤖 Campus Groningen Bot\n\n"
        f"Статус: {status}\n"
        f"📋 Действие: {LAST_ACTION}\n"
        f"🏠 Проверено квартир: {CHECKED_APARTMENTS}\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
    )


def get_keyboard():

    keyboard = [
        [
            InlineKeyboardButton(
                "▶️ Запуск",
                callback_data="start_bot"
            ),
            InlineKeyboardButton(
                "⏹ Стоп",
                callback_data="stop_bot"
            )
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


def start_command(update: Update, context: CallbackContext):

    global STATUS_MESSAGE_ID

    sent = update.message.reply_text(
        get_status_text(),
        reply_markup=get_keyboard()
    )

    STATUS_MESSAGE_ID = sent.message_id


def button_handler(update: Update, context: CallbackContext):

    global BOT_RUNNING
    global LAST_ACTION

    query = update.callback_query

    query.answer()

    if query.data == "start_bot":

        BOT_RUNNING = True

        LAST_ACTION = "Бот запущен"

    elif query.data == "stop_bot":

        BOT_RUNNING = False

        LAST_ACTION = "Бот остановлен"

    query.edit_message_text(
        text=get_status_text(),
        reply_markup=get_keyboard()
    )


def update_status_message(bot):

    global STATUS_MESSAGE_ID

    if not STATUS_MESSAGE_ID:
        return

    try:

        bot.edit_message_text(
            chat_id=TELEGRAM_CHAT_ID,
            message_id=STATUS_MESSAGE_ID,
            text=get_status_text(),
            reply_markup=get_keyboard()
        )

    except:
        pass


async def login(page):

    global LAST_ACTION

    try:

        LAST_ACTION = "Открываю сайт"

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

        if (
            "uitloggen" in page_text
            or "mijn favorieten" in page_text
            or "dashboard" in current_url
            or "mijncampus" in page_text
        ):

            LAST_ACTION = "Уже авторизован"

            return True

        try:

            cookie_button = page.locator(
                'button:has-text("Accept")'
            )

            if await cookie_button.count() > 0:

                await cookie_button.first.click(force=True)

                await page.wait_for_timeout(2000)

        except:
            pass

        LAST_ACTION = "Авторизация"

        login_button = page.locator("text=Inloggen")

        if await login_button.count() == 0:
            return False

        await login_button.first.click(
            force=True,
            timeout=30000
        )

        await page.wait_for_timeout(5000)

        email_input = page.locator(
            'input[type="email"]'
        ).first

        await email_input.fill(EMAIL)

        password_input = page.locator(
            'input[type="password"]'
        ).first

        await password_input.fill(PASSWORD)

        await page.wait_for_timeout(2000)

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

        LAST_ACTION = "Авторизация успешна"

        return success

    except Exception as e:

        LAST_ACTION = "Ошибка логина"

        console_log(str(e))

        return False


async def check_apartments(page, telegram_bot):

    global sent_links
    global CHECKED_APARTMENTS
    global LAST_ACTION

    try:

        LAST_ACTION = "Открываю избранное"

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

            try:

                card = cards.nth(i)

                card_text = (
                    await card.inner_text()
                ).lower()

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

                            apartment_url = (
                                "https://www.campusgroningen.com" + href
                            )

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

            except:
                pass

        for apartment in apartment_links:

            try:

                CHECKED_APARTMENTS += 1

                apartment_url = apartment["url"]
                title = apartment["title"]

                LAST_ACTION = f"Проверяю: {title}"

                update_status_message(telegram_bot)

                await page.goto(
                    apartment_url,
                    wait_until="domcontentloaded",
                    timeout=60000
                )

                await page.wait_for_timeout(5000)

                has_join_button = False

                try:

                    sidebar_title = page.locator(
                        "text=Interesse in deze woning?"
                    ).first

                    await sidebar_title.wait_for(timeout=10000)

                    sidebar = sidebar_title.locator(
                        "xpath=../../.."
                    )

                    sidebar_text = (
                        await sidebar.inner_text()
                    ).lower()

                    for word in SPECIAL_WORDS:

                        if word.lower() in sidebar_text:

                            has_join_button = True
                            break

                except:
                    pass

                if has_join_button:

                    if apartment_url not in sent_links:

                        sent_links.add(apartment_url)

                        telegram_notify(
                            f"🚨 ДОСТУПНА ЗАПИСЬ НА ПРОСМОТР!\n\n"
                            f"🏠 {title}\n\n"
                            f"🔗 {apartment_url}"
                        )

            except Exception as e:

                console_log(str(e))

    except Exception as e:

        console_log(str(e))


async def main():

    global LAST_ACTION

    console_log("Бот запущен")

    while True:

        try:

            async with async_playwright() as p:

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

                updater = Updater(
                    TELEGRAM_TOKEN,
                    use_context=True
                )

                telegram_bot = updater.bot

                while True:

                    try:

                        if not BOT_RUNNING:

                            LAST_ACTION = "Бот остановлен"

                            update_status_message(
                                telegram_bot
                            )

                            await asyncio.sleep(5)

                            continue

                        success = await login(page)

                        update_status_message(
                            telegram_bot
                        )

                        if success:

                            await check_apartments(
                                page,
                                telegram_bot
                            )

                        LAST_ACTION = "Ожидание"

                        update_status_message(
                            telegram_bot
                        )

                    except Exception as e:

                        console_log(str(e))

                    await asyncio.sleep(CHECK_INTERVAL)

        except Exception as e:

            console_log(str(e))

            await asyncio.sleep(30)


def start_telegram_bot():

    updater = Updater(
        TELEGRAM_TOKEN,
        use_context=True
    )

    dp = updater.dispatcher

    dp.add_handler(
        CommandHandler("start", start_command)
    )

    dp.add_handler(
        CallbackQueryHandler(button_handler)
    )

    updater.start_polling()

    updater.idle()


telegram_thread = threading.Thread(
    target=start_telegram_bot,
    daemon=True
)

telegram_thread.start()

asyncio.run(main())
