"""
scraper_goal.py
----------------
مسؤول فقط عن جلب الأخبار من https://www.goal.com/ar

آلية العمل المحدثة:
1) جلب قائمة الأخبار الحديثة وتحديد وقتها بدقة.
2) استبعاد أي خبر لا يحمل توقيت زمني واضح لمنع جلب الأخبار القديمة.
3) حد أقصى لعدد الأخبار لضمان عدم تجاوز وقت GitHub Actions.
"""

import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

import config

# تعديل النمط ليشمل مختلف أنواع صفحات المقالات في goal.com/ar مثل الأخبار والقوائم
ARTICLE_URL_RE = re.compile(
    r"^https://www\.goal\.com/ar/(?:[^\n?#]+/)+[A-Za-z0-9_\-]+$"
)

# تعزيز نمط الوقت للالتقاط الدقيق لكافة صيغ الدقائق والساعات باللغة العربية
TIME_PATTERN = re.compile(
    r"(?:الآن|قبل\s+(?:"
    r"(?P<min_single>دقيقة(?:\s+واحدة)?)|"
    r"(?P<min_dual>دقيقتين)|"
    r"(?P<min_num>\d+)\s+(?:دقائق|دقيقة)|"
    r"(?P<hour_single>ساعة(?:\s+واحدة)?)|"
    r"(?P<hour_dual>ساعتين)|"
    r"(?P<hour_num>\d+)\s+(?:ساعات|ساعة)"
    r"))",
    re.UNICODE,
)

# قائمة سوداء للصور العامة/الافتراضية فقط
_GENERIC_IMAGE_MARKERS = (
    "brand-logo",
    "lcp-hack-background",
    "logo",
    "sprite",
    "favicon",
    "placeholder",
    "default",
    "avatar",
    "app-icon",
    "share-card",
    "og-image",
    "goal-logo",
    "fallback",
    "images.outbrain.com",
)


def _relative_time_to_minutes(text: str):
    if not text:
        return None

    m = TIME_PATTERN.search(text.strip())
    if not m:
        return None

    matched_text = m.group(0)

    if matched_text.startswith("الآن"):
        return 0
    if m.group("min_single"):
        return 1
    if m.group("min_dual"):
        return 2
    if m.group("min_num"):
        return int(m.group("min_num"))
    if m.group("hour_single"):
        return 60
    if m.group("hour_dual"):
        return 120
    if m.group("hour_num"):
        return int(m.group("hour_num")) * 60

    return None


def _fetch(url: str) -> str:
    resp = requests.get(
        url,
        headers=config.SCRAPE_REQUEST_HEADERS,
        timeout=25,
    )
    resp.raise_for_status()
    return resp.text


def _is_generic_image(url: str) -> bool:
    if not url:
        return True

    low = url.lower()

    return any(
        marker in low
        for marker in _GENERIC_IMAGE_MARKERS
    )


def get_recent_article_links(window_hours: int = 3, max_limit: int = 15) -> list:
    """جلب الأخبار الصادرة خلال window_hours مع حد أقصى max_limit لمنع التراكم."""
    window_hours = window_hours or getattr(
        config,
        "RECENCY_WINDOW_HOURS",
        3,
    )

    window_minutes = window_hours * 60

    found = {}

    for page_url in (
        config.SOURCE_NEWS_LISTING_URL,
        config.SOURCE_HOME_URL,
    ):
        try:
            html = _fetch(page_url)
        except requests.RequestException as e:
            print(f"خطأ أثناء جلب القائمة من {page_url}: {e}")
            continue

        soup = BeautifulSoup(html, "html.parser")

        for a in soup.find_all("a", href=True):
            href = a["href"]

            if href.startswith("/"):
                href = config.SOURCE_BASE_URL + href

            href = href.split("?")[0].split("#")[0]

            # التأكد من أن الرابط يتبع النطاق واللغة العربية المطلوبة
            if not href.startswith("https://www.goal.com/ar/") or not ARTICLE_URL_RE.match(href):
                continue

            text = a.get_text(" ", strip=True)
            minutes_ago = _relative_time_to_minutes(text)

            # البحث عن التوقيت في الآباء القريبين والوسوم الزمنية إن لم يوجد بالرابط مباشرة
            if minutes_ago is None:
                curr = a
                for _ in range(4):
                    curr = curr.parent
                    if not curr or curr.name == "[document]":
                        break
                    
                    time_tag = curr.find("time")
                    if time_tag:
                        minutes_ago = _relative_time_to_minutes(time_tag.get_text(" ", strip=True))
                        if minutes_ago is not None:
                            break

                    parent_text = curr.get_text(" ", strip=True)
                    minutes_ago = _relative_time_to_minutes(parent_text)
                    if minutes_ago is not None:
                        break

            # استبعاد الرابط إن لم نتمكن من تحديد توقيته الصريح
            if minutes_ago is None:
                continue

            if minutes_ago > window_minutes:
                continue

            clean_title = TIME_PATTERN.sub(
                "",
                text,
            ).strip()

            if not clean_title or len(clean_title) < 10:
                clean_title = text

            if (
                href not in found
                or found[href]["minutes_ago"] > minutes_ago
            ):
                found[href] = {
                    "url": href,
                    "listing_title": clean_title,
                    "minutes_ago": minutes_ago,
                }

    sorted_articles = sorted(
        found.values(),
        key=lambda x: x["minutes_ago"],
    )

    return sorted_articles[:max_limit]


def _extract_featured_image(soup: BeautifulSoup, article_tag) -> str:
    """
    استخراج الصورة البارزة الخاصة بالخبر.

    الأولوية:
    1) og:image
    2) twitter:image
    3) الصورة داخل المقال
    4) الصورة الموجودة قرب العنوان
    """

    # ---------------------------------------------------------
    # 1) الصورة الخاصة بالخبر من Open Graph
    # ---------------------------------------------------------
    for prop in ("og:image", "twitter:image"):
        meta = (
            soup.find("meta", property=prop)
            or soup.find("meta", attrs={"name": prop})
        )

        if meta and meta.get("content"):
            img_url = urljoin(
                config.SOURCE_BASE_URL,
                meta["content"].strip(),
            )

            if not _is_generic_image(img_url):
                return img_url

    # ---------------------------------------------------------
    # 2) الصور الموجودة داخل المقال نفسه
    # ---------------------------------------------------------
    if article_tag:
        for img in article_tag.find_all("img"):
            src = (
                img.get("src")
                or img.get("data-src")
                or img.get("data-original")
                or img.get("data-lazy-src")
                or img.get("data-srcset")
                or img.get("srcset")
            )

            if not src:
                continue

            # اختيار أفضل رابط من srcset
            if "," in src:
                candidates = []

                for item in src.split(","):
                    item = item.strip()
                    if not item:
                        continue

                    parts = item.split()
                    candidates.append(parts[0])

                if candidates:
                    src = candidates[-1]

            src = urljoin(
                config.SOURCE_BASE_URL,
                src.strip(),
            )

            if not _is_generic_image(src):
                return src

    # ---------------------------------------------------------
    # 3) البحث عن صورة مرتبطة بالعنوان
    # ---------------------------------------------------------
    h1 = soup.find("h1")

    if h1:
        parent = h1.find_parent(
            ["article", "main", "div"]
        )

        if parent:
            for img in parent.find_all("img"):
                src = (
                    img.get("src")
                    or img.get("data-src")
                    or img.get("data-original")
                    or img.get("data-lazy-src")
                    or img.get("data-srcset")
                    or img.get("srcset")
                )

                if not src:
                    continue

                if "," in src:
                    parts = [
                        item.strip().split()[0]
                        for item in src.split(",")
                        if item.strip()
                    ]

                    if parts:
                        src = parts[-1]

                src = urljoin(
                    config.SOURCE_BASE_URL,
                    src.strip(),
                )

                if not _is_generic_image(src):
                    return src

    return None


def fetch_article(url: str) -> dict:
    html = _fetch(url)
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    title_tag = soup.find("h1")

    title = (
        title_tag.get_text(
            " ",
            strip=True,
        )
        if title_tag
        else None
    )

    article_tag = (
        soup.find("article")
        or soup.find("main")
        or soup.body
    )

    paragraphs = []

    if article_tag:
        for p in article_tag.find_all("p"):
            txt = p.get_text(
                " ",
                strip=True,
            )

            if len(txt) < 30:
                continue

            if txt in paragraphs:
                continue

            paragraphs.append(txt)

    image_url = _extract_featured_image(
        soup,
        article_tag,
    )

    body_text = "\n\n".join(
        paragraphs[:12]
    )

    return {
        "url": url,
        "title": title,
        "body_text": body_text,
        "image_url": image_url,
    }
