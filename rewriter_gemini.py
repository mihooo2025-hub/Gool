"""
rewriter_gemini.py
--------------------
يرسل نص الخبر الأصلي إلى Gemini لإعادة الصياغة وفق قواعد rules_ar.md،
مع تبديل تلقائي بين:
  - النموذج الأساسي والنموذج الاحتياطي
  - المفتاح الأول والمفتاح الثاني
بحيث تكون هناك حتى 4 محاولات لكل خبر قبل اعتباره فاشلاً في هذه الدورة.
"""

import json
import re
import time
import requests

import config

GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

QUOTA_ERROR_MARKERS = ("RESOURCE_EXHAUSTED", "quota", "429")


class RewriteError(Exception):
    pass


def _load_rules_template() -> str:
    with open("rules_ar.md", "r", encoding="utf-8") as f:
        return f.read()


def _build_system_prompt() -> str:
    template = _load_rules_template()
    categories_list = "، ".join(config.SELECTABLE_CATEGORIES)
    return template.replace("{{ALLOWED_CATEGORIES}}", categories_list)


def _extract_json(raw_text: str) -> dict:
    """Gemini مطالب بإخراج JSON فقط، لكن نحتاط لأي نص زائد حوله."""
    raw_text = raw_text.strip()
    raw_text = re.sub(r"^```json\s*|^```\s*|```$", "", raw_text.strip(), flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if not match:
        raise RewriteError("لم يتم العثور على JSON صالح في رد Gemini")
    return json.loads(match.group(0))


def _call_gemini(api_key: str, model: str, system_prompt: str, article: dict) -> dict:
    user_content = (
        f"عنوان الخبر الأصلي: {article.get('title', '')}\n\n"
        f"نص الخبر الأصلي:\n{article.get('body_text', '')}"
    )

    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_content}]}],
        "generationConfig": {
            "temperature": 0.4,
            "response_mime_type": "application/json",
        },
    }

    url = GEMINI_ENDPOINT.format(model=model)
    
    try:
        resp = requests.post(
            url,
            params={"key": api_key},
            json=payload,
            timeout=120,  # تم رفع المهلة لـ 120 ثانية لتفادي ReadTimeout
        )
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout) as e:
        raise RewriteError(f"انتهت مهلة الاتصال بـ Gemini ({model}): {e}")
    except requests.exceptions.RequestException as e:
        raise RewriteError(f"خطأ في شبكة الاتصال أثناء الطلب لـ Gemini: {e}")

    if resp.status_code != 200:
        body = resp.text[:500]
        is_quota = any(marker in body for marker in QUOTA_ERROR_MARKERS) or resp.status_code == 429
        raise RewriteError(
            f"فشل الاتصال بـ Gemini (status={resp.status_code}, quota_exceeded={is_quota}): {body}"
        )

    data = resp.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise RewriteError(f"استجابة Gemini غير متوقعة: {json.dumps(data)[:500]}")

    result = _extract_json(text)

    # تحقق أساسي من صحة البنية المطلوبة
    if not all(k in result for k in ("title", "body_html", "categories")):
        raise RewriteError(f"بنية JSON ناقصة من Gemini: {result}")

    return result


def rewrite_article(article: dict) -> dict:
    """
    يحاول إعادة صياغة الخبر عبر أربع محاولات بالترتيب:
    (مفتاح1+نموذج أساسي) -> (مفتاح1+نموذج احتياطي) -> (مفتاح2+نموذج أساسي) -> (مفتاح2+نموذج احتياطي)
    يتوقف عند أول نجاح. يرفع RewriteError إذا فشلت كل المحاولات.
    """
    system_prompt = _build_system_prompt()

    attempts = []
    if config.GEMINI_API_KEY_1:
        attempts.append((config.GEMINI_API_KEY_1, config.GEMINI_MODEL_PRIMARY))
        attempts.append((config.GEMINI_API_KEY_1, config.GEMINI_MODEL_FALLBACK))
    if config.GEMINI_API_KEY_2:
        attempts.append((config.GEMINI_API_KEY_2, config.GEMINI_MODEL_PRIMARY))
        attempts.append((config.GEMINI_API_KEY_2, config.GEMINI_MODEL_FALLBACK))

    if not attempts:
        raise RewriteError("لا يوجد أي مفتاح Gemini في متغيرات البيئة")

    last_error = None
    for i, (api_key, model) in enumerate(attempts, start=1):
        try:
            result = _call_gemini(api_key, model, system_prompt, article)
            return result
        except RewriteError as e:
            last_error = e
            print(f"  [محاولة {i}/{len(attempts)}] فشلت عبر {model}: {e}")
            continue

    raise RewriteError(f"فشلت كل محاولات إعادة الصياغة. آخر خطأ: {last_error}")


def sleep_between_rewrites():
    time.sleep(config.DELAY_BETWEEN_REWRITES_SECONDS)
