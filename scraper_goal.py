"""
scraper_goal.py
----------------
مسؤول فقط عن جلب الأخبار من https://www.goal.com/ar

آلية العمل:
1) نجلب صفحة "آخر الأخبار" (وصفحة الرئيسية كمصدر إضافي لنفس القسم "أخبار عاجلة")
   وهي تعرض روابط الأخبار مرفقة بعبارة الوقت النسبي بالعربية
   مثل: "قبل ساعة واحدة"، "قبل 3 ساعات"، "قبل 20 دقيقة"...
   وهذا يتيح تطبيق نافذة الثلاث ساعات مباشرة دون الحاجة لفتح كل مقال لمعرفة تاريخه.
2) لكل رابط ضمن النافذة الزمنية، نفتح صفحة الخبر ونستخرج: العنوان، نص الخبر، والصورة البارزة.
"""

import re
import requests
from bs4 import BeautifulSoup

import config

ARTICLE_URL_RE = re.compile(r"^https://www\.goal\.com/ar/[^/]+/[^/]+/[A-Za-z0-9_\-]+$")

# نمط عبارات الوقت النسبي بالعربية في موقع Goal
TIME_PATTERN = re.compile(
    r"^\s*(?:الآن|قبل\s+(?:"
    r"(?P<min_single>دقيقة واحدة)|"
    r"(?P<min_dual>دقيقتين)|"
    r"(?P<min_num>\d+)\s+(?:دقائق|دقيقة)|"
    r"(?P<hour_single>ساعة واحدة)|"
    r"(?P<hour_dual>ساعتين)|"
    r"(?P<hour_num>\d+)\s+(?:ساعات|ساعة)"
    r"))\s*(?P<rest>.*)$",
    re.UNICODE,
)


def _relative_time_to_minutes(text: str):
    """يحوّل عبارة الوقت النسبي العربية إلى عدد الدقائق، ويعيد أيضاً بقية النص (العنوان)."""
    m = TIME_PATTERN.match(text.strip())
    if not m:
        return None, None
    if text.strip().startswith("الآن"):
        return 0, m.group("rest").strip()
    if m.group("min_single"):
        return 1, m.group("rest").strip()
    if m.group("min_dual"):
        return 2, m.group("rest").strip()
    if m.group("min_num"):
        return int(m.group("min_num")), m.group("rest").strip()
    if m.group("hour_single"):
        return 60, m.group("rest").strip()
    if m.group("hour_dual"):
        return 120, m.group("rest").strip()
    if m.group("hour_num"):
        return int(m.group("hour_num")) * 60, m.group("rest").strip()
    return None, None


def _fetch(url: str) -> str:
    resp = requests.get(url, headers=config.SCRAPE_REQUEST_HEADERS, timeout=25)
    resp.raise_for_status()
    return resp.text


def get_recent_article_links(window_hours: int = None) -> list:
    """
    يعيد قائمة بالأخبار الحديثة ضمن نافذة الساعات المحددة:
    [{"url": ..., "listing_title": ..., "minutes_ago": ...}, ...]
    مع إزالة التكرار بين الرابطين المستخدمين كمصدر لنفس القسم.
    """
    window_hours = window_hours or config.RECENCY_WINDOW_HOURS
    window_minutes = window_hours * 60

    found = {}
    for page_url in (config.SOURCE_NEWS_LISTING_URL, config.SOURCE_HOME_URL):
        try:
            html = _fetch(page_url)
        except requests.RequestException:
            continue
        soup = BeautifulSoup(html, "html.parser")

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("/"):
                href = config.SOURCE_BASE_URL + href
            if not ARTICLE_URL_RE.match(href):
                continue

            text = a.get_text(" ", strip=True)
            minutes_ago, title = _relative_time_to_minutes(text)
            if minutes_ago is None:
                continue  # هذا الرابط ليس من قسم "أخبار عاجلة" ذي الوقت النسبي
            if minutes_ago > window_minutes:
                continue
            if not title:
                continue

            if href not in found or found[href]["minutes_ago"] > minutes_ago:
                found[href] = {
                    "url": href,
                    "listing_title": title,
                    "minutes_ago": minutes_ago,
                }

    return sorted(found.values(), key=lambda x: x["minutes_ago"])


def fetch_article(url: str) -> dict:
    """
    يفتح صفحة الخبر ويستخرج: العنوان الأصلي، نص الخبر الكامل، رابط الصورة البارزة.
    يعيد None في الحقول التي تعذّر استخراجها.
    """
    html = _fetch(url)
    soup = BeautifulSoup(html, "html.parser")

    # العنوان
    title_tag = soup.find("h1")
    title = title_tag.get_text(" ", strip=True) if title_tag else None

    # الصورة البارزة: نعتمد أولاً على og:image ثم أول صورة داخل جسم المقال
    image_url = None
    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        image_url = og_image["content"]

    # جسم الخبر: نبحث عن أكبر تجمّع فقرات <p> بعد العنوان (الأسلوب الأكثر ثباتاً
    # عبر مواقع الأخبار المختلفة دون الاعتماد على أسماء كلاسات قد تتغيّر)
    article_tag = soup.find("article") or soup.body
    paragraphs = []
    if article_tag:
        for p in article_tag.find_all("p"):
            txt = p.get_text(" ", strip=True)
            if len(txt) < 30:
                continue  # تجاهل الفقرات القصيرة جداً (أوصاف صور، إعلانات..)
            if txt in paragraphs:
                continue
            paragraphs.append(txt)

    if not image_url and article_tag:
        img_tag = article_tag.find("img", src=True)
        if img_tag:
            image_url = img_tag["src"]

    body_text = "\n\n".join(paragraphs[:12])  # حد أقصى معقول لحجم النص المُرسل لـ Gemini

    return {
        "url": url,
        "title": title,
        "body_text": body_text,
        "image_url": image_url,
    }
