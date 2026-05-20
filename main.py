import time
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from html.parser import HTMLParser
import json
from pathlib import Path

# Настройки
BASE_URL = "https://www.campusgroningen.com/huren-groningen?page_id=222&p={page}&per-page=18"
MAX_PAGES = 10  # сколько страниц проверять
SEEN_FILE = Path("seen_listings.json")

# ===============================
# HTML парсер для поиска ссылок "/woning/..."
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
                self.results.append((text.strip() or href.rsplit("/", 1)[-1], href))


def load_seen():
    if SEEN_FILE.exists():
        data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        return set(data)
    return set()

def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=2), encoding="utf-8")

def fetch_html(url, timeout=20):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            html = response.read().decode(charset)
            return html
    except HTTPError as e:
        print(f"HTTPError: {e} on URL {url}")
    except Exception as e:
        print(f"Error: {e} on URL {url}")
    return None

def fetch_page(page):
    url = BASE_URL.format(page=page)
    html = fetch_html(url)
    if not html:
        return []

    parser = LinkExtractor("https://www.campusgroningen.com")
    parser.feed(html)

    return parser.results

def fetch_all_pages(max_pages=MAX_PAGES):
    all_items = []
    seen_urls = set()

    for page in range(1, max_pages + 1):
        items = fetch_page(page)
        if not items:
            print(f"Страница {page} пустая или ошибка.")
            break

        unique_on_page = []
        for title, href in items:
            if href not in seen_urls:
                seen_urls.add(href)
                unique_on_page.append((title, href))
                all_items.append((title, href))

        if not unique_on_page:
            print(f"На странице {page} нет новых объявлений.")
            break
        else:
            print(f"Страница {page}: найдено {len(unique_on_page)} ссылки.")
        time.sleep(0.5)  # чтобы не бомбить сайт

    return all_items

def check_new():
    seen = load_seen()
    current = fetch_all_pages()

    new_items = []
    for title, href in current:
        if href not in seen:
            new_items.append((title, href))
            seen.add(href)

    if new_items:
        print("\n🔥 Новые объявления:")
        for title, href in new_items:
            print(f"- {title}")
            print(f"  {href}")
    else:
        print("Новых объявлений нет.")

    save_seen(seen)

if __name__ == "__main__":
    while True:
        print("Проверка страниц сайта Campus Groningen...")
        check_new()
        print("Спим 5 минут...\n")
        time.sleep(5 * 60)  # 5 минут паузы между проверками
