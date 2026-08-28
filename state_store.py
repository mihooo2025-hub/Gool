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


def save_state(state: dict = None, **kwargs) -> None:
    """حفظ الحالة إلى الملف بشكل آمن."""
    if state is None:
        state = kwargs.get("state", {})
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"خطأ أثناء حفظ state.json: {e}")


def is_processed(url: str = "", state: dict = None, **kwargs) -> bool:
    if state is None:
        state = kwargs.get("state", {})
    if not url:
        url = kwargs.get("url", "")
    return url in state.get("processed_urls", [])


def is_duplicate(state: dict = None, url: str = "", title: str = "", **kwargs) -> bool:
    """التحقق مما إذا كان الرابط قد تم معالجته سابقاً لمنع التكرار."""
    if state is None:
        state = kwargs.get("state", {})
    if not url:
        url = kwargs.get("url", "")
    return is_processed(url=url, state=state)


def mark_processed(*args, **kwargs) -> None:
    """علامة الخبر كمنشور مع قبول أي عدد من المعاملات."""
    state = kwargs.get("state")
    url = kwargs.get("url")

    # استخراج الوسائط في حال التمرير غير المسمى
    for arg in args:
        if isinstance(arg, dict) and state is None:
            state = arg
        elif isinstance(arg, (str, dict)) and url is None:
            url = arg.get("url", "") if isinstance(arg, dict) else arg

    if state is None:
        state = {}

    if "processed_urls" not in state:
        state["processed_urls"] = []
    if url and url not in state["processed_urls"]:
        state["processed_urls"].append(url)


def mark_published(*args, **kwargs) -> None:
    """دالة مستعارة لتوسيم الخبر كمنشور متوافقة مع main.py."""
    mark_processed(*args, **kwargs)


def add_pending_retry(*args, **kwargs) -> None:
    """إضافة خبر لقائمة الإعادة كـ dict موحد يضم الرابط والعنوان لضمان اتساق البيانات."""
    state = kwargs.get("state")
    candidate = kwargs.get("candidate") or kwargs.get("url")

    # استخراج الوسائط غير المسمات
    for arg in args:
        if isinstance(arg, dict) and state is None:
            state = arg
        elif candidate is None and not isinstance(arg, dict):
            candidate = arg

    if state is None:
        state = {}

    if "pending_retry" not in state:
        state["pending_retry"] = []

    # تحويل المرشح إلى قاموس موحد
    if isinstance(candidate, str):
        item_dict = {"url": candidate, "listing_title": ""}
    elif isinstance(candidate, dict):
        item_dict = candidate
    else:
        item_dict = None

    if item_dict and item_dict.get("url"):
        # منع التكرار داخل قائمة الإعادة بناءً على الرابط
        existing_urls = [
            x["url"] if isinstance(x, dict) else x 
            for x in state["pending_retry"]
        ]
        if item_dict["url"] not in existing_urls:
            state["pending_retry"].append(item_dict)


def add_to_retry_queue(*args, **kwargs) -> None:
    """دالة مستعارة لإضافة الخبر إلى قائمة الإعادة متوافقة مع main.py."""
    add_pending_retry(*args, **kwargs)


def remove_pending_retry(*args, **kwargs) -> None:
    """حذف الخبر من قائمة الإعادة سواء كان مخزناً كنص أو قاموس."""
    state = kwargs.get("state")
    url = kwargs.get("url")

    for arg in args:
        if isinstance(arg, dict) and state is None:
            state = arg
        elif isinstance(arg, (str, dict)) and url is None:
            url = arg.get("url", "") if isinstance(arg, dict) else arg

    if state is not None and "pending_retry" in state and url:
        state["pending_retry"] = [
            item for item in state["pending_retry"]
            if (item.get("url") if isinstance(item, dict) else item) != url
        ]


def remove_from_retry_queue(*args, **kwargs) -> None:
    """دالة مستعارة لحذف الخبر من قائمة الانتظار متوافقة مع main.py."""
    remove_pending_retry(*args, **kwargs)


def pop_retry_queue(*args, **kwargs) -> list:
    """استخراج قائمة العناصر المنتظرة لإعادة المحاولة وإفراغها من الحالة."""
    state = kwargs.get("state")
    if state is None and args:
        for arg in args:
            if isinstance(arg, dict):
                state = arg
                break
    if state is None:
        state = {}

    retry_list = list(state.get("pending_retry", []))
    state["pending_retry"] = []
    return retry_list
