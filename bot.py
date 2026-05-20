import time
import json
import os
import urllib.parse
import requests

from urllib.request import urlopen, Request
from urllib.error import HTTPError
from html.parser import HTMLParser
from pathlib import Path

# ===============================
# SETTINGS
# ===============================

BASE_URL = "https://www.campusgroningen.com/huren-groningen?page_id=222&p={page}&per-page=18"

MAX_PAGES = 10

SEEN_FILE = Path("seen_listings.json")

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = str(os.getenv("CHAT_ID"))

CHECK_ENABLED = True

LAST_UPDATE_ID = 0

# ===============================
# TELEGRAM
# ===============================

def send_telegram_message(text):

    try:

        encoded_text = urllib.parse.quote(text)

        url = (
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            f"?chat_id={CHAT_ID}"
            f"&text={encoded_text}"
        )

        with urlopen(url) as response:
            response.read()

    except Exception as e:
        print("Telegram error:", e)

def get_updates():

    global LAST_UPDATE_ID

    url = (
        f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        f"?offset={LAST_UPDATE_ID + 1}"
    )

    try:

        response = requests.get(url)

        data = response.json()

        if not data["ok"]:
            return []

        return data["result"]

    except Exception as e:
        print("Get updates error:", e)
        return []

def process_commands():

    global CHECK_ENABLED
    global LAST_UPDATE_ID

    updates = get_updates()

    for update in updates:

        LAST_UPDATE_ID = update["update_id"]

        try:

            message = update["message"]["text"]

            if str(update["message"]["chat"]["id"]) != CHAT_ID:
                continue

            # ==========================
            # COMMANDS
            # ==========================

            if message == "/startsearch":

                CHECK_ENABLED = True

                send_telegram_message(
                    "✅ Поиск включен"
                )

            elif message == "/stopsearch":

                CHECK_ENABLED = False

                send_telegram_message(
                    "⛔ Поиск остановлен"
                )

            elif message == "/status":

                status = (
                    "🟢 Включен"
                    if CHECK_ENABLED
                    else "🔴 Выключен"
                )

                send_telegram_message(
                    f"Статус поиска: {status}"
                )

        except Exception as e:
            print("Command process error:", e)

# ===============================
# HTML PARSER
# ===============================

class LinkExtractor(HTMLParser):

    def __init__(self, base_url):

        super().__init__()

        self.base_url = base_url

        self.results = []

    def handle_starttag(self, tag, attrs):

        if tag == "a":

            href = None
            title = None

            for k, v in attrs:

                if k == "href":
                    href = v

                elif k in ("title", "aria-label"):
                    title = v

            if href and "/woning/" in href:

                if href.startswith("/"):
                    href = self.base_url + href

                text = title or ""

                self.results.append(
                    (
                        text.strip()
                        or href.rsplit("/", 1)[-1],
                        href
                    )
                )

# ===============================
# STORAGE
# ===============================

def load_seen():

    if SEEN_FILE.exists():

        data = json.loads(
            SEEN_FILE.read_text(
                encoding="utf-8"
            )
        )

        return set(data)

    return set()

def save_seen(seen):

    SEEN_FILE.write_text(
        json.dumps(
            sorted(seen),
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

# ===============================
# FETCH
# ===============================

def fetch_html(url, timeout=20):

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64)"
        )
    }

    req = Request(url, headers=headers)

    try:

        with urlopen(
            req,
            timeout=timeout
        ) as response:

            charset = (
                response.headers.get_content_charset()
                or "utf-8"
            )

            return response.read().decode(charset)

    except HTTPError as e:

        print(f"HTTPError: {e}")

    except Exception as e:

        print(f"Error: {e}")

    return None

def fetch_page(page):

    url = BASE_URL.format(page=page)

    html = fetch_html(url)

    if not html:
        return []

    parser = LinkExtractor(
        "https://www.campusgroningen.com"
    )

    parser.feed(html)

    return parser.results

def fetch_all_pages(max_pages=MAX_PAGES):

    all_items = []

    seen_urls = set()

    for page in range(1, max_pages + 1):

        items = fetch_page(page)

        if not items:
            break

        for title, href in items:

            if href not in seen_urls:

                seen_urls.add(href)

                all_items.append((title, href))

        time.sleep(0.5)

    return all_items

# ===============================
# CHECK
# ===============================

def check_new():

    seen = load_seen()

    current = fetch_all_pages()

    new_items = []

    for title, href in current:

        if href not in seen:

            new_items.append((title, href))

            seen.add(href)

    if new_items:

        for title, href in new_items:

            message = (
                f"🔥 Новое объявление\n\n"
                f"{title}\n\n"
                f"{href}"
            )

            print(message)

            send_telegram_message(message)

    else:

        print("Новых объявлений нет.")

    save_seen(seen)

# ===============================
# MAIN
# ===============================

if __name__ == "__main__":

    send_telegram_message(
        "🚀 Campus bot запущен"
    )

    while True:

        process_commands()

        if CHECK_ENABLED:

            print("Checking...")

            check_new()

        else:

            print("Search paused")

        time.sleep(60)
