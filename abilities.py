# -*- coding: utf-8 -*-
"""
محرك تنفيذ القدرات الخاصة بالأدوار.

كل قدرة تمر عبر use_ability(): يتحقق من صلاحية اللاعب (له دور، له جولة
نشطة، لديه استخدامات متبقية)، ثم ينفّذ منطق نوع القدرة (ability_type في
roles.py)، ثم يسجّل الاستخدام في قاعدة البيانات والذاكرة طويلة المدى،
ويعيد نص نتيجة واضح يُرسل للاعب في الخاص فقط (لا يُفشي القدرات للمجموعة).

لا تفترض أي دالة هنا صحة معلومة اللاعب المستهدف نفسيًا أو أخلاقيًا؛ كل
نتيجة هي معطى درامي داخل اللعبة فقط.
"""

import random
from typing import Optional, Tuple

import ai_engine
import db
import memory
import roles


class AbilityError(Exception):
    """يُرفع عند رفض استخدام القدرة، مع رسالة صالحة للعرض المباشر للاعب."""


async def _require_active_role(chat_id: int, user_id: int) -> Tuple[roles.Role, "sqlite3.Row"]:
    player = await db.get_player_row(chat_id, user_id)
    if not player or not player["role_id"]:
        raise AbilityError("لا تملك دورًا نشطًا في جولة حالية بهذه المجموعة.")

    role = roles.get_role(player["role_id"])
    if role is None:
        raise AbilityError("تعذّر التعرف على دورك الحالي. راسل المشرف إن استمرت المشكلة.")

    if role.ability_type == "passive":
        raise AbilityError(f"دور «{role.name}» ليس له قدرة تُستخدم يدويًا؛ تأثيره سردي دائم.")

    if player["ability_uses_left"] <= 0:
        raise AbilityError(f"استنفدت كل استخدامات قدرة «{role.ability_name}» في هذه الجولة.")

    return role, player


async def use_ability(chat_id: int, user_id: int, round_number: int, target_id: Optional[int] = None) -> str:
    role, player = await _require_active_role(chat_id, user_id)

    if role.needs_target and target_id is None:
        raise AbilityError("هذه القدرة تحتاج اختيار هدف أولًا.")
    if target_id is not None and target_id == user_id and role.ability_type != "stats_report":
        raise AbilityError("لا يمكنك استهداف نفسك بهذه القدرة.")

    handler = _HANDLERS.get(role.ability_type)
    if handler is None:
        raise AbilityError("هذه القدرة غير مفعّلة بعد في هذا الإصدار من البوت.")

    result = await handler(chat_id, round_number, user_id, target_id)

    consumed = await db.consume_ability_use(chat_id, user_id, round_number)
    if not consumed:
        # حالة نادرة (تسابق نداءات)؛ لا نطبّق النتيجة إن لم يبقَ استخدام فعليًا.
        raise AbilityError(f"استنفدت كل استخدامات قدرة «{role.ability_name}» في هذه الجولة.")

    await db.add_ability_log(chat_id, round_number, user_id, role.id, role.ability_type, target_id, result)
    await memory.remember_event(
        chat_id, round_number,
        f"(سرّي) استخدم صاحب دور «{role.name}» قدرته هذه الجولة.",
        importance=1,
    )
    return result


# ------------------------------------------------------------- HANDLERS ----

async def _h_investigate_evidence(chat_id, round_number, user_id, target_id) -> str:
    evidence = await db.get_evidence(chat_id, limit=10)
    if not evidence:
        return "🔎 لا يوجد دليل كافٍ متداول بعد لتحقيقه؛ حاول مجددًا في جولة لاحقة."
    content, reliability = random.choice(evidence)
    extra = await ai_engine.ai_text(
        "أنت محقق يفحص دليلًا موجودًا بعمق أكبر. أضف تفصيلًا فنيًا واحدًا جديدًا يوضّح مصداقيته "
        "دون حسم الحقيقة الكاملة نهائيًا.",
        f"الدليل: {content}\nموثوقيته المعلنة: {reliability}",
        150,
    ) or "فحصك الدقيق لم يغيّر تقييم موثوقية هذا الدليل، لكنه أكد أنه يستحق المتابعة."
    return f"🔎 نتيجة تحقيقك في الدليل:\n«{content}»\n\n{extra}"


async def _h_analyze_evidence(chat_id, round_number, user_id, target_id) -> str:
    evidence = await db.get_evidence(chat_id, limit=10)
    if len(evidence) < 2:
        return "🧪 لا يوجد عدد كافٍ من الأدلة بعد لمقارنتها؛ حاول لاحقًا حين تتراكم أدلة أكثر."
    a, b = random.sample(evidence, 2)
    extra = await ai_engine.ai_text(
        "قارن بين قطعتي الدليل التاليتين بجملتين فقط: هل تتفقان أم تتناقضان، ولماذا هذا مهم؟",
        f"الدليل الأول: {a[0]} (موثوقية: {a[1]})\nالدليل الثاني: {b[0]} (موثوقية: {b[1]})",
        180,
    ) or "المقارنة لم تحسم اتفاقًا أو تناقضًا واضحًا، لكنها تستحق إثارتها في النقاش."
    return f"🧪 نتيجة تحليلك:\n1) «{a[0]}»\n2) «{b[0]}»\n\n{extra}"


async def _h_protect(chat_id, round_number, user_id, target_id) -> str:
    if target_id is None:
        target_id = user_id
    await db.add_protection(chat_id, round_number, target_id, protected_by=user_id)
    return "🛡️ تم تفعيل الحماية على الهدف المختار لهذه الجولة. لن يعرف أحد بهذا سوى بينك وبين نفسك."


async def _h_spy_info(chat_id, round_number, user_id, target_id) -> str:
    if target_id is None:
        return "🕵️ تحتاج هذه القدرة اختيار هدف."
    rows = await db.recent_messages(chat_id, round_number, limit=50)
    target_row = await db.get_player_row(chat_id, target_id)
    target_name = target_row["full_name"] if target_row else "اللاعب المستهدف"
    target_messages = [text for name, text in rows if target_row and name == target_row["full_name"]]
    if target_messages:
        sample = random.choice(target_messages[-5:])
        return f"🕵️ آخر ما لاحظته من {target_name} في النقاش الحالي:\n«{sample}»"
    return f"🕵️ لم يشارك {target_name} بعد بما يكفي في نقاش هذه الجولة لملاحظة شيء محدد."


async def _h_extra_question(chat_id, round_number, user_id, target_id) -> str:
    mem_context = await memory.build_memory_context(chat_id)
    discussion = await memory.get_discussion_text(chat_id, round_number)
    question = await ai_engine.interrogation_question(discussion, mem_context)
    await memory.remember_event(chat_id, round_number, f"سؤال إضافي (من قدرة خاصة): {question}", importance=1)
    return f"❓ طرحت سؤالًا إضافيًا سيراه بقية اللاعبين كجزء من نقاش الجولة:\n«{question}»"


async def _h_reveal_hint(chat_id, round_number, user_id, target_id) -> str:
    mem_context = await memory.build_memory_context(chat_id)
    hint = await ai_engine.ai_text(
        "اكتب تلميحًا غامضًا واحدًا (جملة واحدة فقط) عن اتجاه محتمل للأحداث القادمة، دون حسم أو تفاصيل مؤكدة.",
        mem_context,
        100,
    ) or "شيء ما في الخلفية لم يُقل بعد سيصبح مهمًا قريبًا."
    return f"🔮 تلميحك الغامض:\n{hint}"


async def _h_steal_info(chat_id, round_number, user_id, target_id) -> str:
    if target_id is None:
        return "🗝️ تحتاج هذه القدرة اختيار هدف."
    target_row = await db.get_player_row(chat_id, target_id)
    if not target_row or not target_row["role_id"]:
        return "🗝️ لم تتمكن من الحصول على معلومة واضحة عن هذا الهدف الآن."
    target_role = roles.get_role(target_row["role_id"])
    if target_role is None:
        return "🗝️ لم تتمكن من الحصول على معلومة واضحة عن هذا الهدف الآن."
    return (
        f"🗝️ عرفت جزءًا من طبيعة الهدف (وليس سرّه الكامل):\n"
        f"هدفه المعلن للمجموعة يبدو أنه: «{target_role.public_goal}»"
    )


async def _h_neutralize_note(chat_id, round_number, user_id, target_id) -> str:
    await memory.remember_event(
        chat_id, round_number, "تم تحييد أثر اتهام واحد غير مدعوم بدليل كافٍ هذه الجولة.", importance=1
    )
    return "⚖️ تم تسجيل تحييدك لأثر اتهام غير عادل هذه الجولة في سياق القصة."


async def _h_influence_decision(chat_id, round_number, user_id, target_id) -> str:
    await memory.remember_event(
        chat_id, round_number, "أثّر أحد الحاضرين بهدوء في صياغة القرار الجماعي القادم.", importance=1
    )
    return "⚖️ سيأخذ القرار الجماعي القادم في الحسبان تأثيرك الصامت هذه المرة."


async def _h_propagate_rumor(chat_id, round_number, user_id, target_id) -> str:
    mem_context = await memory.build_memory_context(chat_id)
    rumor = await ai_engine.ai_text(
        "اكتب جملة واحدة تبدو كدليل لكنها غير مؤكدة أو مضلّلة، لتُضاف كدليل مشكوك في مصداقيته.",
        mem_context, 100,
    ) or "قيل إن أحدهم غادر المكان في توقيت مريب، لكن لا أحد يستطيع تأكيد ذلك فعليًا."
    await db.add_evidence(chat_id, round_number, rumor, "misleading")
    return f"🕸️ نشرت تفصيلًا سيظهر للمجموعة كدليل مشكوك في مصداقيته:\n«{rumor}»"


async def _h_unlock_secret_evidence(chat_id, round_number, user_id, target_id) -> str:
    mem_context = await memory.build_memory_context(chat_id)
    content = await ai_engine.ai_text(
        "اكتب دليلًا سريًا واحدًا موثوقًا (جملة أو جملتين) يعرفه شخص واحد فقط حاليًا، مرتبطًا بسياق القصة.",
        mem_context, 150,
    ) or "وجدت إشارة صغيرة لا يعرفها أحد غيرك بعد، تربط بين مكانين مختلفين في القصة."
    await db.add_evidence(chat_id, round_number, f"(سرّي) {content}", "solid")
    return f"🗝️ فتحت دليلًا سريًا يعرفه أنت فقط الآن:\n«{content}»\n\nبإمكانك مشاركته مع المجموعة متى شئت."


async def _h_recall_memory(chat_id, round_number, user_id, target_id) -> str:
    rows = await db.get_memories(chat_id, kind="long", limit=40)
    if not rows:
        return "📖 لا توجد أحداث سابقة كافية بعد لاستحضارها."
    content, _importance, r_number = random.choice(rows)
    label = f"الجولة {r_number}" if r_number else "بداية القصة"
    return f"📖 استحضرت من ذاكرتك ({label}):\n{content}"


async def _h_puzzle_hint(chat_id, round_number, user_id, target_id) -> str:
    mem_context = await memory.build_memory_context(chat_id)
    hint = await ai_engine.ai_text(
        "اكتب تلميحًا واحدًا قصيرًا يساعد في ربط تفاصيل متفرقة من القصة ببعضها، دون حل اللغز كاملًا.",
        mem_context, 120,
    ) or "التفاصيل الصغيرة التي بدت غير مترابطة قد تشكّل نمطًا واحدًا لو نُظر إليها معًا."
    return f"🧩 تلميح اللغز:\n{hint}"


async def _h_stats_report(chat_id, round_number, user_id, target_id) -> str:
    rows = await db.recent_messages(chat_id, round_number, limit=200)
    if not rows:
        return "📊 لا توجد مشاركة كافية بعد في نقاش هذه الجولة لتحليلها."
    counts = {}
    for name, _text in rows:
        counts[name] = counts.get(name, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: -kv[1])
    most = ordered[0]
    least = ordered[-1]
    silent_note = ""
    players = await db.get_players(chat_id)
    talked_names = set(counts.keys())
    silent = [name for _uid, name, _uname in players if name not in talked_names]
    if silent:
        silent_note = f"\nلم يشارك بعد في هذا النقاش: {', '.join(silent[:5])}."
    return (
        f"📊 تقرير النشاط لهذه الجولة:\n"
        f"الأكثر مشاركة: {most[0]} ({most[1]} رسالة).\n"
        f"الأقل مشاركة ممن تحدث: {least[0]} ({least[1]} رسالة)."
        f"{silent_note}\n\nهذه ملاحظة إحصائية ظاهرية فقط، وليست دليلًا قاطعًا على شيء."
    )


_HANDLERS = {
    "investigate_evidence": _h_investigate_evidence,
    "analyze_evidence": _h_analyze_evidence,
    "protect": _h_protect,
    "spy_info": _h_spy_info,
    "extra_question": _h_extra_question,
    "reveal_hint": _h_reveal_hint,
    "steal_info": _h_steal_info,
    "neutralize_note": _h_neutralize_note,
    "influence_decision": _h_influence_decision,
    "propagate_rumor": _h_propagate_rumor,
    "unlock_secret_evidence": _h_unlock_secret_evidence,
    "recall_memory": _h_recall_memory,
    "puzzle_hint": _h_puzzle_hint,
    "stats_report": _h_stats_report,
}
