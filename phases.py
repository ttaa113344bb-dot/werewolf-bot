"""
منطق اختيار المراحل: عدد الجولات، أي مرحلة عميقة تُستخدم، هل يوجد تصويت،
وكم يجب أن يدوم النقاش. لا يوجد ترتيب ثابت؛ القرار يعتمد على حالة اللعبة.
"""

import random

DEEP_PHASES = [
    "philosophical",
    "evidence",
    "investigation",
    "interrogation",
    "decision",
    "secret_decision",
    "alliance",
]

# المواجهة تحتاج على الأقل متهمًا ومتّهمًا وجمهورًا يصوّت، لذا لا تدخل
# ضمن DEEP_PHASES العادية؛ تُضاف لمجموعة الاختيار فقط إذا كفى عدد اللاعبين
# (راجع CONFRONTATION_MIN_PLAYERS في config.py) ولم تحدث مؤخرًا جدًا.
CONFRONTATION_PHASE = "confrontation"


def decide_total_rounds(player_count: int) -> int:
    base = 3 if player_count <= 5 else 4 if player_count <= 9 else 5
    return base + random.choice([0, 0, 1])


def choose_deep_phases(round_number: int, recently_used: list, player_count: int = 0) -> list:
    """يختار مرحلة أو مرحلتين عميقتين لهذه الجولة، متجنبًا تكرار آخر مرحلتين مباشرة.

    المواجهة (confrontation) تُضاف لمجموعة الاختيار فقط بدءًا من الجولة الثانية،
    وفقط إن كان عدد اللاعبين كافيًا (CONFRONTATION_MIN_PLAYERS)، ولم تُختر في
    آخر جولتين، وبفرصة محدودة حتى لا تطغى على بقية المراحل في كل جولة.
    """
    from config import CONFRONTATION_MIN_PLAYERS

    avoid = set(recently_used[-2:])
    pool = [p for p in DEEP_PHASES if p not in avoid] or list(DEEP_PHASES)
    count = 1 if round_number == 1 else random.choice([1, 1, 2])
    chosen = random.sample(pool, min(count, len(pool)))

    if (
        round_number >= 2
        and player_count >= CONFRONTATION_MIN_PLAYERS
        and CONFRONTATION_PHASE not in recently_used[-2:]
        and CONFRONTATION_PHASE not in chosen
        and random.random() < 0.3
    ):
        chosen.append(CONFRONTATION_PHASE)

    # اجعل المرحلة الفلسفية تظهر غالبًا مرة واحدة على الأقل في الجولات المتوسطة
    if round_number >= 2 and "philosophical" not in recently_used[-3:] and "philosophical" not in chosen:
        if random.random() < 0.35:
            chosen.append("philosophical")
    return chosen


def should_vote_this_round(round_number: int, total_rounds: int) -> bool:
    if round_number == total_rounds:
        return True
    return round_number > 1 and random.random() < 0.3


def discussion_seconds(round_number: int, player_count: int, evidence_count: int) -> int:
    """يحسب مدة النقاش الأساسية بناءً على حالة اللعبة وصعوبتها الفعلية،
    لا برقم ثابت: تزداد كل جولة (تعقيد متصاعد)، وتزداد مع عدد اللاعبين
    (نقاش أوسع)، ومع تراكم الأدلة (قضية أعقد). التمديد اللحظي حسب نشاط
    النقاش الفعلي يُحسب بشكل منفصل أثناء الجولة نفسها (راجع game.py)."""
    from config import BASE_DISCUSSION_SECONDS, MAX_DISCUSSION_SECONDS

    seconds = BASE_DISCUSSION_SECONDS
    seconds += (round_number - 1) * 25          # كل جولة أعمق من سابقتها
    seconds += max(0, player_count - 4) * 8      # كل لاعب إضافي = نقاش أوسع
    seconds += min(evidence_count, 5) * 15       # كل دليل متراكم يزيد التعقيد
    return min(seconds, MAX_DISCUSSION_SECONDS)
