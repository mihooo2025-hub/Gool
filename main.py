"""
main.py
--------
نقطة التشغيل الرئيسية. يُستدعى مرة كل ساعة عبر GitHub Actions.

خطوات الدورة:
1) جلب الأخبار المتاحة خلال آخر 3 ساعات من Goal.com العربي.
2) إضافة الأخبار التي فشلت في الدورات السابقة لإعادة محاولتها.
3) استبعاد المكرر (بالرابط أو بتشابه العنوان).
4) لكل خبر: محاولة المعالجة والنشر حتى مرتين داخل نفس الدورة في حال حدوث خطأ مؤقت.
5) إذا فشلت المحاولات داخل الدورة، يُصنف الخبر كفاشل ويُحفظ لإعادة المحاولة بالدورة القادمة.
6) استبعاد المقالات ذات المحتوى التالف أو بدون عنوان نهائياً.
7) إرسال تقرير نهائي إلى تيليجرام.
"""

import time
import sys

import config
import state_store
import scraper_goal
import rewriter_gemini
import wordpress_client
import telegram_notify

MAX_RETRIES = 2  # عدد المحاولات داخل نفس الدورة قبل تصنيف الخبر كفاشل


def _normalize_candidate(item) -> dict:
    """تحويل أي عنصر (نص أو قاموس) إلى شكل قاموس موحد يحتوي على url."""
    if isinstance(item, str):
        return {"url": item, "listing_title": ""}
    elif isinstance(item, dict):
        return item
    return {"url": str(item), "listing_title": ""}


def _dedupe_candidates(items: list) -> list:
    seen = set()
    unique = []
    for raw_item in items:
        item = _normalize_candidate(raw_item)
        url = item.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(item)
    return unique


def process_one(candidate: dict, state: dict, published_report: list, failed_report: list) -> None:
    url = candidate["url"]
    listing_title = candidate.get("listing_title", "") or "خبر بدون عنوان"

    print(f"\n--- معالجة: {listing_title[:60]} ---")
    print(url)

    last_error_reason = ""

    # حلقة إعادة المحاولة داخل نفس الدورة (حتى مرتين)
    for attempt in range(1, MAX_RETRIES + 1):
        if attempt > 1:
            print(f"  🔄 المحاولة رقم {attempt} للخبر...")
            time.sleep(5)  # انتظار قصير قبل إعادة المحاولة

        # 1) جلب نص الخبر والصورة
        try:
            article = scraper_goal.fetch_article(url)
        except Exception as e:
            print(f"  فشل جلب المقال (محاولة {attempt}): {e}")
            last_error_reason = f"فشل جلب الصفحة: {e}"
            continue

        if not article.get("title") or not article.get("body_text"):
            print("  تعذّر استخراج عنوان أو نص كافٍ من الصفحة")
            # المحتوى التالف يُستبعد نهائياً دون تكرار المحاولات
            state_store.remove_from_retry_queue(state, url)
            failed_report.append({"listing_title": listing_title, "url": url, "reason": "محتوى غير مكتمل (تم استبعاده)"})
            return

        # تحقق تكرار إضافي بالعنوان الحقيقي المستخرج من الصفحة
        if state_store.is_duplicate(state, url, article["title"]):
            print("  تم تجاهله: خبر مكرر")
            state_store.remove_from_retry_queue(state, url)
            return

        # 2) إعادة الصياغة عبر Gemini
        try:
            rewritten = rewriter_gemini.rewrite_article(article)
        except rewriter_gemini.RewriteError as e:
            print(f"  فشلت إعادة الصياغة (محاولة {attempt}): {e}")
            last_error_reason = "فشلت إعادة الصياغة (Gemini API)"
            continue
        finally:
            time.sleep(10)

        # 3) النشر في ووردبريس
        try:
            post = wordpress_client.publish_rewritten_article(rewritten, article.get("image_url"))
        except wordpress_client.WordPressError as e:
            msg = str(e)
            if "صورة بارزة" in msg:
                print(f"  تم تجاهل الخبر نهائياً: {msg}")
                state_store.remove_from_retry_queue(state, url)
                return
            else:
                print(f"  فشل النشر (محاولة {attempt}): {msg}")
                last_error_reason = f"فشل النشر: {msg}"
                continue
        finally:
            time.sleep(config.DELAY_BETWEEN_PUBLISHES_SECONDS)

        # 4) نجاح كامل -> تسجيل الحالة والتقرير الخروج من المحاولات
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
        return

    # إذا استُنفدت جميع المحاولات داخل الدورة الحالية ولم ينجح:
    print(f"  ❌ فشل الخبر بعد {MAX_RETRIES} محاولات في هذه الدورة. سيتم تأجيله للدورة القادمة.")
    state_store.add_to_retry_queue(state, candidate, last_error_reason)
    failed_report.append({"listing_title": listing_title, "url": url, "reason": last_error_reason})


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

    # جلب الأخبار الصادرة في آخر 3 ساعات حتى 15 خبراً
    fresh_candidates = scraper_goal.get_recent_article_links(window_hours=3, max_limit=15)
    retry_candidates = state_store.pop_retry_queue(state)

    print(f"أخبار جديدة ضمن آخر 3 ساعات: {len(fresh_candidates)}")
    print(f"أخبار معادة من قائمة الانتظار: {len(retry_candidates)}")

    all_candidates = _dedupe_candidates(retry_candidates + fresh_candidates)

    to_process = [
        c for c in all_candidates
        if not state_store.is_duplicate(state, c["url"], c.get("listing_title", ""))
    ][:10]

    print(f"سيتم معالجة {len(to_process)} خبر في هذه الدورة")

    published_report = []
    failed_report = []

    for candidate in to_process:
        process_one(candidate, state, published_report, failed_report)
        state_store.save_state(state)

    state_store.save_state(state)

    telegram_notify.send_run_report(published_report, failed_report)

    print(f"\nانتهت الدورة: نُشر {len(published_report)} خبر، فشل {len(failed_report)} خبر.")


if __name__ == "__main__":
    run()
