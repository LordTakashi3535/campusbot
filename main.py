import os
import asyncio
from playwright.async_api import async_playwright
import requests
from dotenv import load_dotenv

load_dotenv()

EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

CHECK_INTERVAL = 300  # 5 минут

sent_links = set()


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text
    })


async def login(page):
    await page.goto("https://www.campusgroningen.com")

    # если уже авторизован
    if "mijncampus" in page.url.lower():
        return

    await page.click("text=Inloggen")

    await page.fill('input[type="email"]', EMAIL)
    await page.fill('input[type="password"]', PASSWORD)

    await page.click('button[type="submit"]')

    await page.wait_for_timeout(5000)


async def check_apartments(page):
    global sent_links

    await page.goto(
        "https://www.campusgroningen.com/mijn-favorieten"
    )

    await page.wait_for_timeout(3000)

    listings = await page.locator("article").all()

    for item in listings:
        try:
            text = await item.inner_text()

            has_join_button = (
                "deelnemen" in text.lower()
                or "participate" in text.lower()
            )

            if has_join_button:

                link = await item.locator("a").first.get_attribute("href")

                full_link = f"https://www.campusgroningen.com{link}"

                if full_link not in sent_links:
                    sent_links.add(full_link)

                    send_telegram(
                        f"🏠 Есть запись на просмотр!\n\n{full_link}"
                    )

        except Exception as e:
            print(e)


async def main():
    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True
        )

        context = await browser.new_context()

        page = await context.new_page()

        while True:
            try:
                await login(page)
                await check_apartments(page)

            except Exception as e:
                print("ERROR:", e)

            await asyncio.sleep(CHECK_INTERVAL)


asyncio.run(main())
