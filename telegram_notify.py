"""
telegram_notify.py
---------------------
يرسل تقريراً نصياً إلى قناة تيليجرام عبر بوت بعد انتهاء كل دورة تشغيل.
لكل خبر تم نشره: العنوان الجديد + رابط الخبر الأصلي (القديم) كرابط مختصر خلف نص "المصدر".
"""

import requests

import config


def _send_message(text: str) -> bool:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("تحذير: TELEGRAM_BOT_TOKEN أو TELEGRAM_CHAT_ID غير مضبوطين - تم تخطي الإشعار")
        return False

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        json={
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    if resp.status_code != 200:
        print(f"فشل إرسال رسالة تيليجرام: {resp.status_code} {resp.text[:300]}")
        return False
    return True


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def send_run_report(published: list, failed: list) -> None:
    """
    published: [{"new_title": ..., "original_url": ..., "wp_post_id": ...}, ...]
    failed: [{"listing_title": ..., "url": ..., "reason": ...}, ...]
    """
    lines = ["<b>تقرير دورة نبض الملاعب</b>", ""]

    if published:
        lines.append(f"✅ تم نشر {len(published)} خبر كمسودة:")
        for item in published:
            title = _escape_html(item["new_title"])
            # رابط مختصر خلف نص "المصدر"
            lines.append(f'• {title} — <a href="{item["original_url"]}">المصدر</a>')
    else:
        lines.append("لم يتم نشر أي خبر جديد في هذه الدورة.")

    if failed:
        lines.append("")
        lines.append(f"⚠️ فشلت معالجة {len(failed)} خبر (سيُعاد المحاولة تلقائياً بالدورة القادمة):")
        for item in failed[:10]:
            title = _escape_html(item.get("listing_title") or item.get("title") or "خبر بدون عنوان")
            lines.append(f"• {title} — {item.get('reason', '')}")

    text = "\n".join(lines)
    # تيليجرام يقبل حتى 4096 حرف تقريباً للرسالة الواحدة
    if len(text) > 3900:
        text = text[:3880] + "\n\n...(تم اختصار التقرير)"

    _send_message(text)
