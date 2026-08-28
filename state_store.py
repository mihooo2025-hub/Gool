"""
state_store.py
--------------
إدارة حالة الأخبار المنشورة وحظر التكرار.
محصّن بالكامل ضد أخطاء JSONDecodeError في حال تلف الملف.
"""

import os
import json

STATE_FILE = os.path.join("data", "state.json")


def _get_default_state() -> dict:
    return {
        "processed_urls": [],
        "pending_retry": []
    }


def load_state() -> dict:
    """تحميل الملف مع حماية كاملة ضد التلف أو قيم JSON المكسورة."""
    if not os.path.exists(STATE_FILE):
        return _get_default_state()

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("processed_urls", [])
                data.setdefault("pending_retry", [])
                return data
            return _get_default_state()
    except (json.JSONDecodeError, Exception) as e:
        print(f"⚠️ تنبيه: ملف state.json تالف أو غير صالح ({e}). سيتم إعادة إنشائه تلقائياً.")
        return _get_default_state()


def save_state(state: dict) -> None:
    """حفظ الحالة إلى الملف بشكل آمن."""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"خطأ أثناء حفظ state.json: {e}")


def is_processed(url: str, state: dict) -> bool:
    return url in state.get("processed_urls", [])


def is_duplicate(state: dict, url: str, title: str = "") -> bool:
    """التحقق مما إذا كان الرابط قد تم معالجته سابقاً لمنع التكرار."""
    return is_processed(url, state)


def mark_processed(url: str, state: dict) -> None:
    if "processed_urls" not in state:
        state["processed_urls"] = []
    if url not in state["processed_urls"]:
        state["processed_urls"].append(url)


def mark_published(url: str, state: dict) -> None:
    """دالة مستعارة لتوسيم الخبر كمنشور متوافقة مع main.py."""
    mark_processed(url, state)


def add_pending_retry(url: str, state: dict) -> None:
    if "pending_retry" not in state:
        state["pending_retry"] = []
    if url not in state["pending_retry"]:
        state["pending_retry"].append(url)


def remove_pending_retry(url: str, state: dict) -> None:
    if "pending_retry" in state and url in state["pending_retry"]:
        state["pending_retry"].remove(url)


def pop_retry_queue(state: dict) -> list:
    """استخراج قائمة العناصر المنتظرة لإعادة المحاولة وإفراغها من الحالة."""
    retry_list = list(state.get("pending_retry", []))
    state["pending_retry"] = []
    return retry_list
