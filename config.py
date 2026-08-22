"""
إعدادات المشروع.

متغيرات البيئة المستخدمة (ولا شيء غيرها):
- BOT_TOKEN       : توكن بوت تيليجرام (إلزامي)
- OPENAI_API_KEY  : مفتاح OpenAI (اختياري، بدونه يعمل البوت بنظام fallback غني بلا انقطاع)
- OPENAI_MODEL    : اسم نموذج OpenAI (اختياري، له قيمة افتراضية)
- DATABASE_PATH   : مسار قاعدة بيانات SQLite (اختياري، له قيمة افتراضية). يُقبل أيضًا DATABASE_URL كبديل.

أي إعداد آخر (عدد اللاعبين، أوقات النقاش، حدود الذاكرة...) هو ثابت في الكود
عن قصد، حتى لا يحتاج مشغّل البوت لضبط متغيرات بيئة إضافية.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ---- متغيرات البيئة الأربعة المسموح بها فقط ----
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()
DATABASE_PATH = (os.getenv("DATABASE_PATH") or os.getenv("DATABASE_URL") or "game.db").strip()

# ---- ثوابت اللعبة (ليست متغيرات بيئة، تُعدّل من الكود مباشرة) ----
GAME_MIN_PLAYERS = 4
GAME_MAX_PLAYERS = 16

BASE_DISCUSSION_SECONDS = 120  # دقيقتان كحد أدنى للنقاش
MAX_DISCUSSION_SECONDS = 300
PHILOSOPHICAL_DISCUSSION_SECONDS = 120
DISCUSSION_POLL_INTERVAL_SECONDS = 15  # لفحص النشاط وتمديد الوقت دون تجميد البوت

# مهلات وإعادة محاولة نداءات الذكاء الاصطناعي
AI_REQUEST_TIMEOUT_SECONDS = 25
AI_MAX_RETRIES = 2

# نوافذ انتظار القرار السرّي وتصويت الشك (بالثواني)
SECRET_DECISION_WINDOW_SECONDS = 45
GROUP_VOTE_WINDOW_SECONDS = 40

# نوافذ انتظار مراحل المواجهة (بالثواني): الاتهام والدفاع أطول، الردود أقصر
CONFRONTATION_STAGE_WINDOW_SECONDS = 35
CONFRONTATION_REPLY_WINDOW_SECONDS = 20
CONFRONTATION_VOTE_WINDOW_SECONDS = 30
# أقل عدد لاعبين مطلوب حتى تكون المواجهة منطقية (متهم + متّهم + جمهور للتصويت)
CONFRONTATION_MIN_PLAYERS = 3

# حدود الذاكرة
LONG_MEMORY_LIMIT = 25
SHORT_MEMORY_MESSAGE_LIMIT = 50
