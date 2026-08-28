"""
wordpress_client.py
---------------------
كل التعامل مع ووردبريس عبر REST API:
1) جلب قائمة التصنيفات الحقيقية من الموقع ومطابقتها بالاسم حرفياً.
2) تنزيل الصورة البارزة من رابط المصدر ثم رفعها كوسائط (Media) في ووردبريس.
3) إنشاء المقال كمسودة (draft) مع العنوان، المحتوى، الصورة البارزة، والتصنيفات.

تم تحسينه للتحقق الآمن من استجابات JSON لتفادي خطأ JSONDecodeError عند استلام صفحات HTML غير متوقعة.
"""

import io
import mimetypes
import requests
from requests.auth import HTTPBasicAuth

import config


class WordPressError(Exception):
    pass


def _auth():
    return HTTPBasicAuth(config.WP_USERNAME, config.WP_APP_PASSWORD)


def _api(path: str) -> str:
    return f"{config.WP_BASE_URL}/wp-json/wp/v2/{path.lstrip('/')}"


def _safe_json_decode(resp: requests.Response, action_name: str) -> dict:
    """تحليل استجابة JSON بأمان لتفادي توقف السكربت عند استلام صفحات HTML أو استجابات غير صالحة."""
    try:
        return resp.json()
    except Exception:
        preview = resp.text[:200] if resp.text else "لا يوجد نص في الاستجابة"
        raise WordPressError(f"فشل تحليل JSON أثناء {action_name} (status={resp.status_code}): {preview}")


_categories_cache = None


def get_categories_map() -> dict:
    """يعيد قاموس {اسم التصنيف: id} لكل تصنيفات الموقع الحقيقية."""
    global _categories_cache
    if _categories_cache is not None:
        return _categories_cache

    mapping = {}
    page = 1
    while True:
        try:
            resp = requests.get(
                _api("categories"),
                params={"per_page": 100, "page": page},
                auth=_auth(),
                timeout=30,
            )
        except requests.RequestException as e:
            raise WordPressError(f"خطأ اتصال أثناء جلب التصنيفات: {e}")

        if resp.status_code != 200:
            raise WordPressError(f"فشل جلب التصنيفات: {resp.status_code} {resp.text[:300]}")
            
        items = _safe_json_decode(resp, "جلب التصنيفات")
        if not isinstance(items, list) or not items:
            break
            
        for item in items:
            if isinstance(item, dict) and "name" in item and "id" in item:
                mapping[item["name"].strip()] = item["id"]
                
        if len(items) < 100:
            break
        page += 1

    _categories_cache = mapping
    return mapping


def resolve_category_ids(category_names: list) -> list:
    wp_categories = get_categories_map()
    resolved_ids = []

    always_id = wp_categories.get(config.ALWAYS_INCLUDE_CATEGORY)
    if always_id:
        resolved_ids.append(always_id)

    for name in category_names or []:
        name = (name or "").strip()
        if name in config.EXCLUDED_CATEGORIES:
            continue
        if name == config.ALWAYS_INCLUDE_CATEGORY:
            continue
        if name not in config.SELECTABLE_CATEGORIES:
            continue
        cid = wp_categories.get(name)
        if cid and cid not in resolved_ids:
            resolved_ids.append(cid)

    return resolved_ids


def download_image(image_url: str) -> tuple:
    if not image_url:
        return None
    try:
        resp = requests.get(
            image_url, headers=config.IMAGE_REQUEST_HEADERS, timeout=30, stream=True
        )
        if resp.status_code != 200:
            return None
        content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
        if not content_type.startswith("image/"):
            return None
        ext = mimetypes.guess_extension(content_type) or ".jpg"
        filename = f"featured{ext}"
        return resp.content, content_type, filename
    except requests.RequestException:
        return None


def upload_media(image_bytes: bytes, content_type: str, filename: str, title: str) -> int:
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": content_type,
    }
    try:
        resp = requests.post(
            _api("media"),
            headers=headers,
            data=image_bytes,
            auth=_auth(),
            timeout=60,
        )
    except requests.RequestException as e:
        raise WordPressError(f"خطأ شبكة أثناء رفع الصورة البارزة: {e}")

    if resp.status_code not in (200, 201):
        raise WordPressError(f"فشل رفع الصورة البارزة: {resp.status_code} {resp.text[:300]}")

    data = _safe_json_decode(resp, "رفع الصورة")
    media_id = data.get("id") if isinstance(data, dict) else None

    if not media_id:
        raise WordPressError("لم يعُد ووردبريس معرّف الصورة (media_id) بعد الرفع")

    try:
        requests.post(
            _api(f"media/{media_id}"),
            json={"alt_text": title, "title": title},
            auth=_auth(),
            timeout=30,
        )
    except requests.RequestException:
        pass

    return media_id


def create_draft_post(title: str, body_html: str, category_ids: list, featured_media_id: int) -> dict:
    payload = {
        "title": title,
        "content": body_html,
        "status": config.WP_POST_STATUS,
        "categories": category_ids,
        "featured_media": featured_media_id,
    }
    try:
        resp = requests.post(_api("posts"), json=payload, auth=_auth(), timeout=30)
    except requests.RequestException as e:
        raise WordPressError(f"خطأ شبكة أثناء إنشاء المسودة: {e}")

    if resp.status_code not in (200, 201):
        raise WordPressError(f"فشل إنشاء المسودة: {resp.status_code} {resp.text[:300]}")

    return _safe_json_decode(resp, "إنشاء المسودة")


def publish_rewritten_article(rewritten: dict, original_image_url: str) -> dict:
    image_data = download_image(original_image_url)
    if not image_data:
        raise WordPressError("لا توجد صورة بارزة صالحة - تم تجاهل الخبر وفق القاعدة الإلزامية")

    image_bytes, content_type, filename = image_data
    media_id = upload_media(image_bytes, content_type, filename, rewritten["title"])

    category_ids = resolve_category_ids(rewritten.get("categories", []))

    post = create_draft_post(
        title=rewritten["title"],
        body_html=rewritten["body_html"],
        category_ids=category_ids,
        featured_media_id=media_id,
    )
    return post
