"""
main.py
--------
نقطة التشغيل الرئيسية. يُستدعى مرة كل ساعة عبر GitHub Actions.

خطوات الدورة:
1) جلب الأخبار المتاحة خلال آخر 3 ساعات من Goal.com العربي.
2) إضافة الأخبار التي فشلت في الدورات السابقة لإعادة محاولتها.
3) استبعاد المكرر (بالرابط أو بتشابه العنوان).
4) لكل خبر: جلب النص + الصورة -> إعادة الصياغة عبر Gemini -> النشر كمسودة في ووردبريس.
5) الأخبار التي تفشل معالجتها (لأسباب مؤقتة) تُحفظ لإعادة المحاولة بالدورة القادمة.
6) إرسال تقرير نهائي إلى تيليجرام.
"""

import time
import sys

import config
import state_store
import scraper_goal
import rewriter_gemini
import wordpress_client
import telegram_notify


def _dedupe_candidates(items: list) -> list:
    seen = set()
    unique = []
    for item in items:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        unique.append(item)
    return unique


def process_one(candidate: dict, state: dict, published_report: list, failed_report: list) -> None:
    url = candidate["url"]
    listing_title = candidate.get("listing_title", "")

    print(f"\n--- معالجة: {listing_title[:60]} ---")
    print(url)

    # 1) جلب نص الخبر والصورة
    try:
        article = scraper_goal.fetch_article(url)
    except Exception as e:
        print(f"  فشل جلب المقال: {e}")
        state_store.add_to_retry_queue(state, candidate, f"فشل جلب المقال: {e}")
        failed_report.append({"listing_title": listing_title, "url": url, "reason": "فشل جلب الصفحة"})
        return

    if not article.get("title") or not article.get("body_text"):
        print("  تعذّر استخراج عنوان أو نص كافٍ من الصفحة")
        state_store.add_to_retry_queue(state, candidate, "محتوى غير مكتمل")
        failed_report.append({"listing_title": listing_title, "url": url, "reason": "محتوى غير مكتمل"})
        return

    # تحقق تكرار إضافي بالعنوان الحقيقي المستخرج من الصفحة (وليس فقط عنوان القائمة)
    if state_store.is_duplicate(state, url, article["title"]):
        print("  تم تجاهله: خبر مكرر")
        return

    # 2) إعادة الصياغة عبر Gemini
    try:
        rewritten = rewriter_gemini.rewrite_article(article)
    except rewriter_gemini.RewriteError as e:
        print(f"  فشلت إعادة الصياغة: {e}")
        state_store.add_to_retry_queue(state, candidate, "فشلت إعادة الصياغة (نفاد الحصة أو خطأ)")
        failed_report.append({"listing_title": listing_title, "url": url, "reason": "فشلت إعادة الصياغة"})
        return
    finally:
        rewriter_gemini.sleep_between_rewrites()

    # 3) النشر في ووردبريس (يشترط وجود صورة بارزة صالحة)
    try:
        post = wordpress_client.publish_rewritten_article(rewritten, article.get("image_url"))
    except wordpress_client.WordPressError as e:
        msg = str(e)
        if "صورة بارزة" in msg:
            # قاعدة إلزامية: لا صورة = تجاهل الخبر نهائياً (بدون إعادة محاولة)
            print(f"  تم تجاهل الخبر نهائياً: {msg}")
        else:
            print(f"  فشل النشر: {msg}")
            state_store.add_to_retry_queue(state, candidate, f"فشل النشر: {msg}")
            failed_report.append({"listing_title": listing_title, "url": url, "reason": "فشل النشر في ووردبريس"})
        return
    finally:
        time.sleep(config.DELAY_BETWEEN_PUBLISHES_SECONDS)

    # 4) نجاح كامل -> تسجيل الحالة والتقرير
    state_store.mark_published(
        state,
        url=url,
        title=article["title"],
        new_title=rewritten["title"],
        wp_post_id=post.get("id"),
    )
    state_store.remove_from_retry_queue(state, url)
    published_report.append(
        {
            "new_title": rewritten["title"],
            "original_url": url,
            "wp_post_id": post.get("id"),
        }
    )
    print(f"  ✅ نُشر كمسودة (post id={post.get('id')})")


def run() -> None:
    missing = []
    if not config.WP_BASE_URL:
        missing.append("WP_BASE_URL")
    if not config.WP_USERNAME or not config.WP_APP_PASSWORD:
        missing.append("WP_USERNAME / WP_APP_PASSWORD")
    if not config.GEMINI_API_KEY_1:
        missing.append("GEMINI_API_KEY_1")
    if missing:
        print(f"إعدادات ناقصة في الأسرار (Secrets): {', '.join(missing)}")
        sys.exit(1)

    state = state_store.load_state()

    # تحديد الفحص لآخر 3 ساعات حصراً
    fresh_candidates = scraper_goal.get_recent_article_links(window_hours=3)
    retry_candidates = state_store.pop_retry_queue(state)

    print(f"أخبار جديدة ضمن آخر 3 ساعات: {len(fresh_candidates)}")
    print(f"أخبار معادة من قائمة الانتظار: {len(retry_candidates)}")

    all_candidates = _dedupe_candidates(retry_candidates + fresh_candidates)

    # استبعاد ما هو مكرر أصلاً في السجل المنشور (بالرابط أو تشابه عنوان القائمة)
    to_process = [
        c for c in all_candidates
        if not state_store.is_duplicate(state, c["url"], c.get("listing_title", ""))
    ]

    print(f"سيتم معالجة {len(to_process)} خبر في هذه الدورة")

    published_report = []
    failed_report = []

    for candidate in to_process:
        process_one(candidate, state, published_report, failed_report)
        state_store.save_state(state)  # حفظ تدريجي حتى لا تُفقد الحالة عند انقطاع مفاجئ

    state_store.save_state(state)

    telegram_notify.send_run_report(published_report, failed_report)

    print(f"\nانتهت الدورة: نُشر {len(published_report)} خبر، فشل {len(failed_report)} خبر.")


if __name__ == "__main__":
    run()
