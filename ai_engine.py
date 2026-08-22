"""
طبقة الذكاء الاصطناعي.

كل دالة هنا لها fallback غني ومتنوع (من content_bank) في حال:
- لم يوجد OPENAI_API_KEY، أو
- فشل الاتصال بواجهة OpenAI، أو
- انتهت المهلة الزمنية.

بهذا لا يتجمد البوت أبدًا بانتظار رد الذكاء الاصطناعي، ولا تتوقف اللعبة
إن كانت الواجهة غير متاحة مؤقتًا.

ملاحظة مهمة: لا تدّعي أي دالة هنا معرفة النوايا الحقيقية لأي لاعب أو صفاته
النفسية الفعلية؛ كل تحليل هو قراءة درامية لما قيل في النقاش فقط، وتُصاغ
التعليمات المرسلة للنموذج بما يمنع الادعاء بخلاف ذلك.
"""

import asyncio
import logging
import random

from openai import AsyncOpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL, AI_REQUEST_TIMEOUT_SECONDS, AI_MAX_RETRIES
from content_bank import (
    FALLBACK_OPENINGS,
    FALLBACK_QUESTIONS,
    FALLBACK_NARRATIONS,
    FALLBACK_EVENTS,
    FALLBACK_EVIDENCE,
    FALLBACK_INTERROGATION,
    FALLBACK_SECRETS,
    FALLBACK_ENDINGS,
    FALLBACK_ACCUSATIONS,
    FALLBACK_DEFENSES,
    FALLBACK_CONFRONTATION_REBUTTALS,
    FALLBACK_CONFRONTATION_FINAL,
)

logger = logging.getLogger("ai_engine")

client = AsyncOpenAI(api_key=OPENAI_API_KEY, timeout=AI_REQUEST_TIMEOUT_SECONDS) if OPENAI_API_KEY else None

_NO_FAKE_INSIGHT_RULE = (
    " لا تدّعِ معرفة النوايا الحقيقية لأي شخص فعليًا ولا تصف شخصيته النفسية كحقيقة ثابتة؛ "
    "تعامل مع كلامه كمعطى درامي داخل القصة فقط."
)


async def ai_text(instructions: str, prompt: str, max_output_tokens: int = 500) -> str | None:
    """ينادي واجهة OpenAI مع مهلة زمنية وإعادة محاولة محدودة. يعيد None عند الفشل النهائي."""
    if client is None:
        return None

    last_error = None
    for attempt in range(AI_MAX_RETRIES + 1):
        try:
            response = await asyncio.wait_for(
                client.responses.create(
                    model=OPENAI_MODEL,
                    instructions=instructions + _NO_FAKE_INSIGHT_RULE,
                    input=prompt,
                    max_output_tokens=max_output_tokens,
                ),
                timeout=AI_REQUEST_TIMEOUT_SECONDS,
            )
            text = (response.output_text or "").strip()
            if text:
                return text
            return None
        except asyncio.TimeoutError as exc:
            last_error = exc
            logger.warning("AI request timed out (attempt %s)", attempt + 1)
        except Exception as exc:  # noqa: BLE001 - أي خطأ من مكتبة OpenAI يجب ألا يوقف اللعبة
            last_error = exc
            logger.warning("AI request failed (attempt %s): %s", attempt + 1, exc)
        await asyncio.sleep(1 + attempt)

    logger.error("AI request failed after retries: %s", last_error)
    return None


def _fallback(pool, avoid: list[str] | None = None):
    avoid = set(avoid or [])
    candidates = [p for p in pool if (p if isinstance(p, str) else p[0]) not in avoid] or pool
    return random.choice(candidates)


async def generate_opening(scenario_title: str, scenario_hook: str, avoid: list[str]) -> str:
    text = await ai_text(
        "أنت راوٍ عربي محترف يكتب مقدمة قصيرة (فقرتين كحد أقصى) لبداية لعبة جماعية غامضة وفلسفية. "
        "اعتمد على السيناريو المعطى لكن أضف تفصيلًا جديدًا يجعل هذه الجلسة مختلفة عن أي جلسة سابقة. "
        "لا تستخدم كلمات الذئب أو المافيا أو القروي.",
        f"عنوان العالم: {scenario_title}\nالفكرة: {scenario_hook}\nمقدمات سابقة يجب تجنب تكرار أسلوبها:\n"
        + "\n".join(avoid[-5:]),
        350,
    )
    return text or f"{scenario_hook} {_fallback(FALLBACK_OPENINGS, avoid)}"


async def create_round_question(avoid: list[str], memory_context: str) -> str:
    text = await ai_text(
        "أنت مصمم لعبة عربية عميقة. ابتكر سؤالًا أو مأزقًا واحدًا جديدًا فقط لجولة نقاش جماعي، "
        "مرتبطًا بسياق القصة أدناه إن وُجد. اجعله قابلًا للنقاش وليس نعم/لا بسيطة، بلا تكرار لما سبق.",
        f"سياق القصة حتى الآن:\n{memory_context}\n\nأسئلة سابقة يجب تجنّب تكرارها:\n" + "\n".join(avoid[-8:]),
        250,
    )
    return text or _fallback(FALLBACK_QUESTIONS, avoid)


async def generate_event(memory_context: str, avoid: list[str]) -> str:
    text = await ai_text(
        "أنت راوٍ يضيف حدثًا قصيرًا (سطرين إلى ثلاثة) يدفع القصة الجماعية إلى الأمام، "
        "مبنيًا على ما جرى سابقًا. لا تحسم الأمور نهائيًا، اترك مجالًا للنقاش.",
        f"ما جرى حتى الآن:\n{memory_context}",
        200,
    )
    return text or _fallback(FALLBACK_EVENTS, avoid)


async def philosophical_phase(topic: str, discussion: str, memory_context: str) -> str:
    text = await ai_text(
        f"أنت مدير لعبة فلسفية عربية. انقل النقاش إلى مستوى أعمق حول موضوع «{topic}» "
        "اعتمادًا على كلام اللاعبين والسياق العام. اكتب فقرة قصيرة مشوّقة ثم سؤالًا واحدًا حادًا، بلا تكرار.",
        f"سياق القصة:\n{memory_context}\n\nملخص النقاش الحالي:\n{discussion}",
        400,
    )
    return text or f"سؤال حول {topic}: {_fallback(FALLBACK_QUESTIONS)}"


async def evidence_phase(discussion: str, memory_context: str):
    """يعيد (نص الدليل, درجة الموثوقية)."""
    text = await ai_text(
        "أنت راوٍ يكشف دليلًا جديدًا واحدًا مرتبطًا بالنقاش، مع الإشارة إلى مدى موثوقيته "
        "(solid أو partial أو uncertain أو misleading) في السطر الأخير بصيغة: RELIABILITY: <word>",
        f"سياق القصة:\n{memory_context}\n\nالنقاش:\n{discussion}",
        300,
    )
    if not text:
        content, reliability = _fallback(FALLBACK_EVIDENCE)
        return content, reliability

    reliability = "uncertain"
    lines = text.splitlines()
    body = text
    for line in lines:
        if line.strip().upper().startswith("RELIABILITY:"):
            reliability = line.split(":", 1)[1].strip().lower() or "uncertain"
            body = text.replace(line, "").strip()
    return body, reliability


async def interrogation_question(discussion: str, memory_context: str, avoid: list[str] | None = None) -> str:
    avoid = avoid or []
    text = await ai_text(
        "ابنِ سؤال استجواب واحد مباشر وحاد، مستمدًا من تناقض أو نقطة غامضة ظهرت فعليًا في النقاش أدناه. "
        "لا تخترع اتهامًا لم يُذكر مطلقًا، ولا تكرر أسئلة استجواب سابقة.",
        f"سياق القصة:\n{memory_context}\n\nالنقاش:\n{discussion}\n\nأسئلة استجواب سابقة يجب تجنّب تكرارها:\n"
        + "\n".join(avoid[-6:]),
        150,
    )
    return text or _fallback(FALLBACK_INTERROGATION, avoid)


async def decision_context(template_prompt: str, memory_context: str) -> str:
    text = await ai_text(
        "أعد صياغة سؤال القرار التالي بحيث يرتبط بسياق القصة الحالي بجملة أو جملتين تمهيديتين قبله، "
        "دون تغيير جوهر القرار المطلوب.",
        f"سياق القصة:\n{memory_context}\n\nالقرار المطلوب صياغته: {template_prompt}",
        200,
    )
    return text or template_prompt


async def secret_for_player(scenario_title: str, role_name: str, avoid: list[str]) -> str:
    text = await ai_text(
        "اكتب سرًا شخصيًا قصيرًا (جملة أو جملتين) يخص لاعبًا واحدًا في لعبة جماعية غامضة، "
        "مرتبطًا بعالم القصة ودوره، ولا يجعله بالضرورة مذنبًا بأي شيء.",
        f"عالم القصة: {scenario_title}\nدور اللاعب: {role_name}\nأسرار سابقة يجب تجنب تكرار فكرتها:\n"
        + "\n".join(avoid[-6:]),
        150,
    )
    return text or _fallback(FALLBACK_SECRETS, avoid)


async def alliance_phase(discussion: str, memory_context: str) -> str:
    text = await ai_text(
        "صف بإيجاز (جملتين) كيف تتغيّر العلاقات بين اللاعبين بناءً على النقاش الأخير: "
        "من يقترب من من، ومن يبتعد. اجعلها ملاحظة سردية وليست حكمًا قاطعًا.",
        f"سياق القصة:\n{memory_context}\n\nالنقاش:\n{discussion}",
        200,
    )
    return text or "بدأت تتشكل انطباعات غير معلنة بين بعض الحاضرين، لم يعبّر عنها أحد صراحةً بعد."


async def confrontation_accusation(
    discussion: str, memory_context: str, accuser_name: str, accused_name: str
) -> str:
    """يولّد اتهامًا يوجهه لاعب لآخر، لو لم يكتب اللاعب اتهامه بنفسه في الوقت المتاح."""
    text = await ai_text(
        f"اكتب اتهامًا قصيرًا (جملتان كحد أقصى) يمكن أن يوجهه اللاعب «{accuser_name}» "
        f"إلى اللاعب «{accused_name}» بصيغة المتكلم، مبنيًا على تناقض أو نقطة غامضة فعلية "
        "وردت في النقاش أدناه. لا تخترع اعترافًا لم يحدث، واجعله اتهامًا احتماليًا لا حكمًا قاطعًا.",
        f"سياق القصة:\n{memory_context}\n\nالنقاش:\n{discussion}",
        150,
    )
    if text:
        return text
    return _fallback(FALLBACK_ACCUSATIONS)


async def confrontation_defense(
    accusation: str, discussion: str, memory_context: str, accused_name: str
) -> str:
    """يولّد دفاع اللاعب المتّهم، لو لم يكتب دفاعه بنفسه في الوقت المتاح."""
    text = await ai_text(
        f"اكتب دفاعًا قصيرًا (جملتان كحد أقصى) بصيغة المتكلم يقوله اللاعب «{accused_name}» "
        "ردًا على الاتهام الموجّه إليه أدناه. لا يجب أن يكون الدفاع اعترافًا ولا إثباتًا قاطعًا للبراءة؛ "
        "اجعله معقولًا ومقنعًا جزئيًا فقط.",
        f"سياق القصة:\n{memory_context}\n\nالاتهام:\n{accusation}\n\nالنقاش:\n{discussion}",
        150,
    )
    if text:
        return text
    return _fallback(FALLBACK_DEFENSES)


async def confrontation_rebuttal(accusation: str, defense: str, speaker_name: str, is_accuser: bool) -> str:
    """رد قصير إضافي (من المتّهِم أو المتّهَم) بعد الاتهام والدفاع الأولين."""
    role_label = "المتّهِم" if is_accuser else "المتّهَم"
    text = await ai_text(
        f"اكتب ردًا قصيرًا جدًا (جملة واحدة) بصيغة المتكلم يقوله {role_label} «{speaker_name}» "
        "في نهاية مواجهة بين لاعبين، دون حسم النتيجة نهائيًا.",
        f"الاتهام الأصلي:\n{accusation}\n\nالدفاع:\n{defense}",
        80,
    )
    if text:
        return text
    return _fallback(FALLBACK_CONFRONTATION_REBUTTALS if is_accuser else FALLBACK_CONFRONTATION_FINAL)


async def confrontation_outcome_narration(
    accusation: str, defense: str, memory_context: str, verdict_label: str
) -> str:
    """وصف قصير لأثر نتيجة المواجهة على مجرى القصة (بلا حسم قاطع للحقيقة)."""
    text = await ai_text(
        f"اكتب جملتين كحد أقصى تصفان أثر مواجهة انتهت بنتيجة «{verdict_label}» على أجواء المجموعة، "
        "دون كشف الحقيقة الكاملة أو تبرئة/إدانة أحد بشكل نهائي.",
        f"سياق القصة:\n{memory_context}\n\nالاتهام:\n{accusation}\n\nالدفاع:\n{defense}",
        150,
    )
    if text:
        return text
    return _fallback(FALLBACK_NARRATIONS)


async def narrate_round(question: str, discussion: str, memory_context: str) -> str:
    text = await ai_text(
        "أنت راوٍ ذكي للعبة جماعية عربية. حلل التناقضات والاتفاقات الظاهرة في النقاش، "
        "واكتب خاتمة درامية قصيرة ومحترمة للجولة تدفع القصة قدمًا.",
        f"سياق القصة:\n{memory_context}\n\nسؤال الجولة: {question}\n\nالنقاش:\n{discussion}",
        450,
    )
    return text or _fallback(FALLBACK_NARRATIONS)


async def generate_ending(memory_context: str, ending_type: str, ending_label: str) -> str:
    text = await ai_text(
        f"اكتب خاتمة نهائية للعبة من نوع «{ending_label}» بناءً على كل ما جرى في القصة. "
        "اشرح بإيجاز: ماذا حدث، لماذا حدث، وأي القرارات أثّرت أكثر. لا تلتزم بكشف كل شيء؛ "
        "يمكن أن يبقى جزء غامضًا إن كان هذا يناسب نوع النهاية.",
        f"سياق القصة الكامل:\n{memory_context}",
        550,
    )
    return text or FALLBACK_ENDINGS.get(ending_type, _fallback(list(FALLBACK_ENDINGS.values())))


async def summarize_for_memory(raw_text: str, max_output_tokens: int = 250) -> str:
    text = await ai_text(
        "لخّص المقطع التالي من أحداث/نقاش لعبة جماعية في نقاط مركّزة جدًا (لا تتجاوز 4 أسطر)، "
        "احتفظ فقط بما قد يكون مهمًا لاحقًا في القصة.",
        raw_text,
        max_output_tokens,
    )
    if text:
        return text
    trimmed = raw_text.strip()
    return trimmed[:300] + ("…" if len(trimmed) > 300 else "")
