"""
state_store.py
---------------
يدير ملف data/state.json الذي يحفظ:
1) الأخبار المنشورة بنجاح سابقاً (لمنع التكرار) - عبر تجزئة الرابط + العنوان.
2) قائمة انتظار للأخبار التي فشلت معالجتها، لإعادة المحاولة في الدورة التالية.

هذا الملف نفسه يُحدَّث ويُحفظ (commit) داخل مستودع GitHub بعد كل تشغيل،
حتى تبقى الحالة محفوظة بين كل تشغيل مجدول وآخر.
"""

import json
import os
import hashlib
import difflib
from datetime import datetime, timedelta, timezone

import config


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.strip().split("?")[0].encode("utf-8")).hexdigest()


def load_state() -> dict:
    if not os.path.exists(config.STATE_FILE):
        return {"published": [], "pending_retry": []}
    try:
        with open(config.STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        data = {}
    data.setdefault("published", [])
    data.setdefault("pending_retry", [])
    return data


def save_state(state: dict) -> None:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    # تنظيف السجلات القديمة جداً حتى لا يتضخم الملف إلى الأبد
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.KEEP_HISTORY_DAYS)
    cleaned = []
    for item in state.get("published", []):
        try:
            ts = datetime.fromisoformat(item["processed_at"])
        except Exception:
            cleaned.append(item)
            continue
        if ts >= cutoff:
            cleaned.append(item)
    state["published"] = cleaned

    with open(config.STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def is_duplicate(state: dict, url: str, title: str) -> bool:
    """يتحقق من التكرار عبر تطابق الرابط أولاً، ثم تشابه العنوان الضبابي."""
    h = _url_hash(url)
    for item in state.get("published", []):
        if item.get("url_hash") == h:
            return True
        similarity = difflib.SequenceMatcher(
            None, item.get("title", ""), title
        ).ratio()
        if similarity >= config.TITLE_SIMILARITY_THRESHOLD:
            return True
    return False


def mark_published(state: dict, url: str, title: str, new_title: str, wp_post_id) -> None:
    state.setdefault("published", []).append(
        {
            "url_hash": _url_hash(url),
            "url": url,
            "title": title,
            "new_title": new_title,
            "wp_post_id": wp_post_id,
            "processed_at": _now_iso(),
        }
    )


def add_to_retry_queue(state: dict, article: dict, reason: str) -> None:
    """يضيف خبراً فشلت معالجته إلى قائمة الانتظار لإعادة المحاولة بالدورة القادمة."""
    existing = {a["url"] for a in state.get("pending_retry", [])}
    if article["url"] in existing:
        return
    article = dict(article)
    article["fail_reason"] = reason
    article["queued_at"] = _now_iso()
    state.setdefault("pending_retry", []).append(article)


def pop_retry_queue(state: dict) -> list:
    """يسحب كل قائمة الانتظار الحالية ويفرغها (سيُعاد ملؤها بما يفشل مجدداً)."""
    items = state.get("pending_retry", [])
    state["pending_retry"] = []
    return items


def remove_from_retry_queue(state: dict, url: str) -> None:
    state["pending_retry"] = [
        a for a in state.get("pending_retry", []) if a["url"] != url
    ]
