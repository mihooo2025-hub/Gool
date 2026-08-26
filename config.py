"""
config.py
---------
كل الإعدادات القابلة للتغيير موجودة هنا في مكان واحد.
كل القيم الحساسة (مفاتيح API، بيانات دخول ووردبريس، توكن تيليجرام) تُقرأ من
متغيرات البيئة (GitHub Secrets) ولا يتم كتابتها في الكود أبداً.
"""

import os

# ============================================================
# مصدر الأخبار
# ============================================================
SOURCE_NAME = "Goal Arabic"
SOURCE_BASE_URL = "https://www.goal.com"
SOURCE_NEWS_LISTING_URL = "https://www.goal.com/ar/%D8%A3%D8%AE%D8%A8%D8%A7%D8%B1"  # /ar/أخبار
SOURCE_HOME_URL = "https://www.goal.com/ar"

# نافذة فحص الأخبار الأخيرة (بالساعات) وفق طلبك
RECENCY_WINDOW_HOURS = 3

# ============================================================
# نماذج Gemini (الأساسي ثم الاحتياطي) + مفتاحين مع تبديل تلقائي
# ============================================================
GEMINI_MODEL_PRIMARY = "gemini-3.6-flash"
GEMINI_MODEL_FALLBACK = "gemini-3.5-flash-lite"

GEMINI_API_KEY_1 = os.environ.get("GEMINI_API_KEY_1", "")
GEMINI_API_KEY_2 = os.environ.get("GEMINI_API_KEY_2", "")

# محاولات إعادة الصياغة قبل اعتبار الخبر فاشلاً في هذه الدورة
GEMINI_MAX_ATTEMPTS_PER_ARTICLE = 4  # (مفتاح1+نموذج1, مفتاح1+نموذج2, مفتاح2+نموذج1, مفتاح2+نموذج2)

# ============================================================
# التوقيت بين العمليات (بالثواني) لتجنب الأخطاء والحظر
# ============================================================
DELAY_BETWEEN_REWRITES_SECONDS = 10
DELAY_BETWEEN_PUBLISHES_SECONDS = 3

# ============================================================
# ووردبريس
# ============================================================
WP_BASE_URL = os.environ.get("WP_BASE_URL", "").rstrip("/")  # مثال: https://nabdalmalaeb.com
WP_USERNAME = os.environ.get("WP_USERNAME", "")
WP_APP_PASSWORD = os.environ.get("WP_APP_PASSWORD", "")  # Application Password من ووردبريس
WP_POST_STATUS = "draft"  # كما طلبت: يُرفع كمسودة دائماً

# ============================================================
# قائمة التصنيفات المسموحة (كما تظهر بالضبط في ووردبريس)
# مطابقة للصورة المرسلة - يمنع إنشاء أي تصنيف جديد
# ============================================================
EXCLUDED_CATEGORIES = ["اهم الاخبار", "مقالات وتحليلات"]

# التصنيف الإنجليزي الخاص بقسم الرئيسية - يُختار في كل مرة إلزامياً
ALWAYS_INCLUDE_CATEGORY = "Uncategorized"

# التصنيفات المتاحة أمام Gemini للاختيار منها (بدون المستبعدة وبدون الإلزامي)
SELECTABLE_CATEGORIES = [
    "سوق الانتقالات",
    "ريال مدريد",
    "برشلونة",
    "ليفربول",
    "مانشستر يونايتد",
    "مانشستر سيتي",
    "تشلسي",
    "ارسنال",
    "بايرن ميونخ",
    "باريس سان جرمان",
    "ميلان",
    "يوفنتوس",
    "انتر ميلان",
    "بروسيا دورتموند",
    "اتليتكو مدريد",
]

# ============================================================
# تيليجرام
# ============================================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ============================================================
# ملفات الحالة (تُحفظ وتُحدَّث داخل المستودع بين كل تشغيل وآخر)
# ============================================================
DATA_DIR = "data"
STATE_FILE = os.path.join(DATA_DIR, "state.json")  # الأخبار المنشورة + قائمة الانتظار للفاشلة

# عتبة تشابه العناوين لاعتبار خبرين مكررين (0-1)
TITLE_SIMILARITY_THRESHOLD = 0.78

# مهلة الاحتفاظ بسجل الأخبار المنشورة (بالأيام) لمنع تضخم الملف
KEEP_HISTORY_DAYS = 14

# HTTP headers للتحايل على بعض حمايات الروابط عند جلب الصور المميزة
IMAGE_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.goal.com/",
}

SCRAPE_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en;q=0.8",
}
