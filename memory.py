"""
نظام الذاكرة.

- ذاكرة قصيرة: نص النقاش الحالي للجولة (يُقرأ مباشرة من جدول الرسائل).
- ذاكرة طويلة: ملخصات مضغوطة للأحداث والقرارات المهمة، تُرسَل للذكاء الاصطناعي
  بدل تاريخ المحادثة الكامل غير المحدود.

هذا يمنع تضخم كل طلب إلى الذكاء الاصطناعي مع تقدّم اللعبة.
"""

import db
import ai_engine
from config import LONG_MEMORY_LIMIT, SHORT_MEMORY_MESSAGE_LIMIT


async def get_discussion_text(chat_id: int, round_number: int, limit: int = SHORT_MEMORY_MESSAGE_LIMIT) -> str:
    rows = await db.recent_messages(chat_id, round_number, limit)
    if not rows:
        return ""
    return "\n".join(f"{name}: {text}" for name, text in rows)


async def get_long_term_summary(chat_id: int) -> str:
    rows = await db.get_memories(chat_id, kind="long", limit=LONG_MEMORY_LIMIT)
    if not rows:
        return ""
    return "\n".join(f"- {content}" for content, _importance, _round in rows)


async def build_memory_context(chat_id: int, scenario_title: str = "") -> str:
    """يبني سياقًا مضغوطًا يُرسل للذكاء الاصطناعي بدل كل تاريخ اللعبة."""
    parts = []
    if scenario_title:
        parts.append(f"عالم القصة: {scenario_title}")
    summary = await get_long_term_summary(chat_id)
    if summary:
        parts.append("أهم ما حدث حتى الآن:\n" + summary)
    return "\n\n".join(parts) or "بداية القصة، لا أحداث سابقة بعد."


async def remember_round(chat_id: int, round_number: int, question: str, discussion_text: str) -> str:
    """يضغط نقاش الجولة ويحفظه في الذاكرة الطويلة بدل إرسال كل الرسائل لاحقًا."""
    if not discussion_text.strip():
        summary = f"الجولة {round_number}: لم يشارك اللاعبون نقاشًا مكتوبًا يُذكر حول: {question}"
    else:
        raw = f"موضوع الجولة {round_number}: {question}\n\n{discussion_text}"
        summary = await ai_engine.summarize_for_memory(raw)
    await db.add_memory(chat_id, kind="long", content=summary, importance=2, round_number=round_number)
    return summary


async def remember_event(chat_id: int, round_number: int, content: str, importance: int = 2):
    await db.add_memory(chat_id, kind="long", content=content, importance=importance, round_number=round_number)
    await db.add_event(chat_id, round_number, content)


async def remember_decision(chat_id: int, round_number: int, decision_type: str, choice_summary: str):
    await db.add_memory(
        chat_id, kind="long",
        content=f"قرار ({decision_type}) في الجولة {round_number}: {choice_summary}",
        importance=3, round_number=round_number,
    )


async def get_decisions_summary(chat_id: int) -> str:
    rows = await db.get_memories(chat_id, kind="long", limit=LONG_MEMORY_LIMIT)
    decisions = [c for c, _i, _r in rows if c.startswith("قرار (")]
    return "\n".join(f"- {d}" for d in decisions)


async def compact_if_needed(chat_id: int):
    """عند تضخم الذاكرة الطويلة، اضغطها إلى ملخص واحد أعمق للحفاظ على حجم السياق."""
    rows = await db.get_memories(chat_id, kind="long", limit=200)
    if len(rows) <= LONG_MEMORY_LIMIT:
        return
    joined = "\n".join(f"- {c}" for c, _i, _r in rows)
    compact = await ai_engine.summarize_for_memory(joined, max_output_tokens=300)
    await db.clear_memory_kind(chat_id, "long")
    await db.add_memory(chat_id, kind="long", content=f"ملخص مضغوط للأحداث السابقة: {compact}", importance=3)
