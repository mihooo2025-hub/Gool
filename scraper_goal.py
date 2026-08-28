"""
scraper_goal.py
----------------
مسؤول فقط عن جلب الأخبار من https://www.goal.com/ar

آلية العمل المحدثة:
1) جلب قائمة الأخبار الحديثة وتحديد وقتها.
2) استخراج الصورة البارزة **الخاصة بالمقال حصرية** ومنع تكرار الصور العامة/الافتراضية.
3) استخراج العنوان ونصر الخبر بدقة.
"""

import re
import requests
from bs4 import BeautifulSoup

import config

ARTICLE_URL_RE = re.compile(r"^https://www\.goal\.com/ar/[^/]+/[^/]+/[A-Za-z0-9_\-]+$")

TIME_PATTERN = re.compile(
    r"(?:الآن|قبل\s+(?:"
    r"(?P<min_single>دقيقة واحدة)|"
    r"(?P<min_dual>دقيقتين)|"
    r"(?P<min_num>\d+)\s+(?:دقائق|دقيقة)|"
    r"(?P<hour_single>ساعة واحدة)|"
    r"(?P<hour_dual>ساعتين)|"
    r"(?P<hour_num>\d+)\s+(?:ساعات|ساعة)"
    r"))",
    re.UNICODE,
)

# قائمة سوداء موسعة للصور العامة/الافتراضية المكررة بموقع Goal
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
    "assets.goal.com/v3/assets",  # شعارات الأصول الافتراضية
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
    resp = requests.get(url, headers=config.SCRAPE_REQUEST_HEADERS, timeout=25)
    resp.raise_for_status()
    return resp.text


def _is_generic_image(url: str) -> bool:
    if not url:
        return True
    low = url.lower()
    return any(marker in low for marker in _GENERIC_IMAGE_MARKERS)


def get_recent_article_links(window_hours: int = None) -> list:
    window_hours = window_hours or config.RECENCY_WINDOW_HOURS
    window_minutes = window_hours * 60

    found = {}
    for page_url in (config.SOURCE_NEWS_LISTING_URL, config.SOURCE_HOME_URL):
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

            if not ARTICLE_URL_RE.match(href):
                continue

            text = a.get_text(" ", strip=True)
            if not text:
                continue

            minutes_ago = _relative_time_to_minutes(text)
            
            if minutes_ago is None:
                parent = a.find_parent(["article", "div", "li"])
                if parent:
                    parent_text = parent.get_text(" ", strip=True)
                    minutes_ago = _relative_time_to_minutes(parent_text)

            if minutes_ago is None:
                minutes_ago = 30 

            if minutes_ago > window_minutes:
                continue

            clean_title = TIME_PATTERN.sub("", text).strip()
            if not clean_title or len(clean_title) < 10:
                clean_title = text

            if href not in found or found[href]["minutes_ago"] > minutes_ago:
                found[href] = {
                    "url": href,
                    "listing_title": clean_title,
                    "minutes_ago": minutes_ago,
                }

    return sorted(found.values(), key=lambda x: x["minutes_ago"])


def _extract_featured_image(soup: BeautifulSoup, article_tag) -> str:
    """
    استخراج الصورة الفريدة للخبر باستبعاد تام للصور العامة والافتراضية.
    """
    # المستوى 1: البحث عن صورة في جسم المقال الرئيسي (الـ Figure الأول تحت الـ H1)
    h1 = soup.find("h1")
    if h1:
        parent = h1.find_parent(["article", "main", "div"])
        if parent:
            for img in parent.find_all("img"):
                # البحث في كافة الخصائص المحتملة للصورة
                src = img.get("src") or img.get("data-src") or img.get("srcset") or img.get("data-srcset")
                if srcset := img.get("srcset"):
                    src = srcset.split(",")[0].split(" ")[0]
                
                if src and not _is_generic_image(src):
                    return src

    # المستوى 2: البحث بداخل وسم article بالتحديد
    if article_tag:
        for img in article_tag.find_all("img"):
            src = img.get("src") or img.get("data-src") or img.get("data-original")
            if not src or _is_generic_image(src):
                continue
            return src

    # المستوى 3: ميتاداتا og:image بشرط ألا تكون صورة افتراضية للموقع
    for prop in ("og:image", "twitter:image"):
        meta = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        if meta and meta.get("content"):
            img_url = meta["content"]
            if not _is_generic_image(img_url):
                return img_url

    return None


def fetch_article(url: str) -> dict:
    html = _fetch(url)
    soup = BeautifulSoup(html, "html.parser")

    title_tag = soup.find("h1")
    title = title_tag.get_text(" ", strip=True) if title_tag else None

    article_tag = soup.find("article") or soup.find("main") or soup.body
    paragraphs = []
    if article_tag:
        for p in article_tag.find_all("p"):
            txt = p.get_text(" ", strip=True)
            if len(txt) < 30:
                continue
            if txt in paragraphs:
                continue
            paragraphs.append(txt)

    image_url = _extract_featured_image(soup, article_tag)
    body_text = "\n\n".join(paragraphs[:12])

    return {
        "url": url,
        "title": title,
        "body_text": body_text,
        "image_url": image_url,
    }
