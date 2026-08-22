"""
محرك اللعبة.

كل مجموعة (chat_id) لها جلستها الخاصة بالكامل: حالتها، مهمتها غير المتزامنة
(asyncio.Task)، وبياناتها في قاعدة البيانات. لا يوجد أي "sleep" يوقف
استقبال البوت للرسائل أو الأوامر؛ كل انتظار يتم عبر asyncio.sleep داخل
مهمة الجولة فقط، وتستمر بقية المجموعات والأوامر بالعمل بصورة طبيعية أثناءه.
"""

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Dict, Optional

from aiogram.exceptions import TelegramAPIError

import ai_engine
import db
import memory
import phases
import roles as roles_module
import telegram_utils
import variety
from config import (
    GAME_MIN_PLAYERS,
    GAME_MAX_PLAYERS,
)
from content_bank import ENDING_LABELS

logger = logging.getLogger("game")


class GameStatus:
    """حالات واضحة لدورة حياة الردهة/الجولة، مستقلة عن `GameSession.active`
    (الذي يبقى للتوافق الخلفي مع بقية الكود الذي يعتمد عليه فعليًا أثناء
    تشغيل الجولة نفسها).

    WAITING  → لا أحد انضم بعد (أو ردهة جديدة بعد انتهاء جولة سابقة).
    JOINING  → التسجيل مفتوح، لاعب واحد على الأقل منضم، لم يكتمل العدد بعد.
    FULL     → اكتمل العدد للتو، التسجيل يُغلق وتبدأ إجراءات الإطلاق.
    STARTING → جارٍ تجهيز الجولة (توزيع أدوار، إلخ) قبل أن تصبح فعليًا نشطة.
    RUNNING  → الجولة تعمل فعليًا (جولات اللعب جارية).
    FINISHED → انتهت آخر جولة (بنجاح أو إلغاء)؛ ردهة جديدة ستُفتح تلقائيًا
               عند أول محاولة انضمام لاحقة.
    """

    WAITING = "waiting"
    JOINING = "joining"
    FULL = "full"
    STARTING = "starting"
    RUNNING = "running"
    FINISHED = "finished"


@dataclass
class GameSession:
    active: bool = False
    round_number: int = 0
    total_rounds: int = 0
    phase: str = "waiting"
    scenario_title: str = ""
    used_deep_phases: list = field(default_factory=list)
    task: Optional[asyncio.Task] = None
    admin_id: Optional[int] = None
    paused: bool = False
    pending_extension: int = 0
    pause_event: asyncio.Event = field(default_factory=asyncio.Event)
    status: str = GameStatus.WAITING
    lobby_message_ids: list = field(default_factory=list)
    recent_confrontation_accused: list = field(default_factory=list)

    def __post_init__(self):
        self.pause_event.set()  # set = تعمل بصورة طبيعية، clear = متوقفة مؤقتًا


sessions: Dict[int, GameSession] = {}

# قفل واحد لكل مجموعة يحمي تسلسل "تحقق ثم أضِف" في try_join من الـ
# Race Condition عند ضغط عدة لاعبين على زر الانضمام في نفس اللحظة تقريبًا.
_join_locks: Dict[int, asyncio.Lock] = {}


def _lock_for(chat_id: int) -> asyncio.Lock:
    return _join_locks.setdefault(chat_id, asyncio.Lock())

# إجابات القرارات السرية والتصويت العام، مؤقتة في الذاكرة لكل جولة نشطة فقط.
_secret_answers: Dict[tuple, Dict[int, str]] = {}
_vote_answers: Dict[tuple, Dict[int, int]] = {}

# نصوص المواجهة (اتهام/دفاع/ردود) وأصوات تصويت "هل كان مقنعًا؟"، مؤقتة بالذاكرة
# لكل مواجهة نشطة فقط. المفتاح: (chat_id, round_number). القيمة الداخلية تخزّن
# النص الملتقط لكل مرحلة، محددة بـ user_id المسموح له بالكتابة في تلك المرحلة.
_confrontation_capture: Dict[tuple, dict] = {}
_confrontation_votes: Dict[tuple, Dict[int, str]] = {}


def state_for(chat_id: int) -> GameSession:
    return sessions.setdefault(chat_id, GameSession())


def is_running(chat_id: int) -> bool:
    session = sessions.get(chat_id)
    return bool(session and session.active)


async def _interruptible_sleep(session: "GameSession", seconds: float):
    """مثل asyncio.sleep لكنه يتوقف فعليًا أثناء إيقاف مؤقت (/pause) ويكمل بعد /resume،
    دون إهدار الوقت المتبقي ودون تجميد أي شيء آخر في البوت."""
    remaining = seconds
    while remaining > 0:
        if session.paused:
            await session.pause_event.wait()
            continue
        step = min(1.0, remaining)
        started = asyncio.get_event_loop().time()
        await asyncio.sleep(step)
        remaining -= (asyncio.get_event_loop().time() - started)


def request_extension(chat_id: int, seconds: int) -> bool:
    session = sessions.get(chat_id)
    if not session or not session.active:
        return False
    session.pending_extension += seconds
    return True


def pause_game(chat_id: int) -> bool:
    session = sessions.get(chat_id)
    if not session or not session.active or session.paused:
        return False
    session.paused = True
    session.pause_event.clear()
    return True


def resume_game(chat_id: int) -> bool:
    session = sessions.get(chat_id)
    if not session or not session.active or not session.paused:
        return False
    session.paused = False
    session.pause_event.set()
    return True


def is_paused(chat_id: int) -> bool:
    session = sessions.get(chat_id)
    return bool(session and session.paused)


# ------------------------------------------------------------- JOIN FLOW ---

async def try_join(chat_id: int, user_id: int, full_name: str, username: Optional[str]):
    """محاولة انضمام لاعب واحد، بصورة ذرّية بالكامل عبر قفل خاص بكل مجموعة.

    يعيد (ok, payload):
    - عند الرفض: payload نص رسالة الخطأ المناسبة لعرضها للاعب.
    - عند النجاح: payload = {"count": ..., "target": ..., "just_became_full": bool}.
      `just_became_full` تكون True لمحاولة انضمام واحدة بالضبط (تلك التي
      أوصلت العدد للحد المطلوب)، وهي الإشارة التي يجب على الطبقة المستدعية
      (app.py) استخدامها لإغلاق التسجيل وإطلاق الجولة فورًا.
    """
    lock = _lock_for(chat_id)
    async with lock:
        session = state_for(chat_id)

        if session.status in (GameStatus.STARTING, GameStatus.RUNNING):
            return False, "لا يمكن الانضمام الآن، الجولة الحالية قيد التشغيل بالفعل."
        if session.status == GameStatus.FULL:
            return False, "اكتمل العدد وتُغلق التسجيلات الآن، ستبدأ الجولة خلال لحظات."

        # ردهة جديدة تلقائيًا بعد انتهاء آخر جولة: نظّف بيانات الجولة
        # السابقة فقط عند أول انضمام فعلي لردهة تالية (لا نمسحها فور
        # الانتهاء مباشرة، حتى يبقى /case ونحوه قابلًا للمراجعة لفترة).
        if session.status == GameStatus.FINISHED:
            await db.reset_game_data(chat_id)
            session.status = GameStatus.WAITING
            session.lobby_message_ids = []

        players = await db.get_players(chat_id)
        if any(p[0] == user_id for p in players):
            return False, "أنت منضم أصلًا."
        if len(players) >= GAME_MAX_PLAYERS:
            # حماية دفاعية إضافية؛ لا يُفترض الوصول لهذا المسار عادة لأن
            # الحالة تتحول إلى FULL فور اكتمال العدد فتُرفض المحاولات التالية أعلاه.
            return False, "اكتمل عدد اللاعبين في هذه الجولة."

        await db.add_player(chat_id, user_id, full_name, username)
        count = len(players) + 1

        if session.status == GameStatus.WAITING:
            session.status = GameStatus.JOINING

        just_became_full = False
        if count >= GAME_MAX_PLAYERS:
            session.status = GameStatus.FULL
            just_became_full = True

        return True, {"count": count, "target": GAME_MAX_PLAYERS, "just_became_full": just_became_full}


def register_lobby_message(chat_id: int, message_id: int):
    """سجّل معرّف رسالة تحمل زر الانضمام، لنتمكن من تعطيله/حذفه لاحقًا فور
    اكتمال العدد، بدل ترك الزر ظاهرًا في القديم وهو معطّل منطقيًا فقط."""
    session = state_for(chat_id)
    session.lobby_message_ids.append(message_id)


def is_registration_open(chat_id: int) -> bool:
    session = sessions.get(chat_id)
    if not session:
        return True
    return session.status in (GameStatus.WAITING, GameStatus.JOINING, GameStatus.FINISHED)


async def close_registration_and_launch(bot, chat_id: int, trigger_user_id: int):
    """يُستدعى مرة واحدة بالضبط، فور أن يوصل انضمامٌ ما العددَ إلى الحد
    المطلوب (just_became_full=True). يغلق التسجيل (يعطّل/يحذف كل أزرار
    الانضمام المعروضة)، ثم يطلق الجولة تلقائيًا دون أي أمر يدوي."""
    session = state_for(chat_id)
    if session.status != GameStatus.FULL:
        # حماية إضافية: لو استُدعيت هذه الدالة أكثر من مرة بطريق الخطأ،
        # لن تُطلق الجولة إلا من الاستدعاء الأول الذي وجد الحالة FULL فعلًا.
        return

    for message_id in session.lobby_message_ids:
        try:
            await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
        except TelegramAPIError:
            pass
    session.lobby_message_ids = []

    await telegram_utils.safe_send(
        bot, chat_id, "✅ اكتمل عدد اللاعبين! تُغلق التسجيلات الآن، ويبدأ توزيع الأدوار والجولة الأولى تلقائيًا..."
    )

    session.status = GameStatus.STARTING
    task = asyncio.create_task(_auto_start_and_report(bot, chat_id, trigger_user_id))
    session.task = task


async def _auto_start_and_report(bot, chat_id: int, trigger_user_id: int):
    session = state_for(chat_id)
    try:
        ok, result = await start_game(bot, chat_id, trigger_user_id)
        if not ok:
            logger.error("Auto-start failed unexpectedly for chat_id=%s: %s", chat_id, result)
            await telegram_utils.safe_send(
                bot, chat_id, "⚠️ تعذّر بدء الجولة تلقائيًا رغم اكتمال العدد. جرّبوا /start لفتح ردهة جديدة."
            )
            session.status = GameStatus.FINISHED
            session.active = False
            session.task = None
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Unhandled error auto-starting game for chat_id=%s", chat_id)
        await telegram_utils.safe_send(bot, chat_id, "⚠️ حدث خطأ غير متوقع وتم إيقاف محاولة بدء الجولة بأمان.")


# ------------------------------------------------------------- MAIN LOOP ---

async def start_game(bot, chat_id: int, admin_id: int):
    session = state_for(chat_id)
    if session.active:
        return False, "الجولة تعمل بالفعل."

    players = await db.get_players(chat_id)
    if len(players) < GAME_MIN_PLAYERS:
        return False, f"لا يمكن البدء بعد. نحتاج على الأقل {GAME_MIN_PLAYERS} لاعبين."

    session.active = True
    session.status = GameStatus.RUNNING
    session.admin_id = admin_id
    session.used_deep_phases = []
    session.round_number = 0
    session.phase = "starting"
    session.paused = False
    session.pending_extension = 0
    session.pause_event.set()

    try:
        await _run_game(bot, chat_id, session, players)
    except asyncio.CancelledError:
        await db.upsert_game(chat_id, status="cancelled", phase="cancelled")
        await telegram_utils.safe_send(bot, chat_id, "⏹️ تم إنهاء الجولة الحالية.")
        raise
    except Exception:
        logger.exception("Game crashed for chat_id=%s", chat_id)
        await telegram_utils.safe_send(bot, 
            chat_id,
            "⚠️ حدث خطأ غير متوقع أثناء اللعبة، وتم إيقافها بأمان. ستُفتح ردهة انضمام جديدة تلقائيًا عبر /start.",
        )
    finally:
        session.active = False
        session.phase = "finished"
        session.task = None
        # بغضّ النظر عن سبب الانتهاء (نجاح، إلغاء، أو خطأ)، أصبحت الردهة
        # جاهزة لدورة جديدة تلقائيًا؛ بيانات الجولة السابقة تُنظَّف لاحقًا
        # (بصورة كسولة) عند أول انضمام فعلي في الردهة التالية.
        session.status = GameStatus.FINISHED

    return True, "تمت الجولة."


async def _run_game(bot, chat_id: int, session: GameSession, players):
    await db.upsert_game(chat_id, status="running", phase="starting", admin_id=session.admin_id)

    scenario = await variety.pick_scenario(chat_id)
    session.scenario_title = scenario["title"]
    await db.upsert_game(chat_id, scenario_id=scenario["id"], scenario_title=scenario["title"])

    difficulty = await db.get_difficulty(chat_id)
    chosen_roles = await roles_module.assign_roles(chat_id, len(players), difficulty)
    for (user_id, _name, _username), role in zip(players, chosen_roles):
        await db.set_role(chat_id, user_id, role.id, role.name, role.ability_uses)

    total_rounds = phases.decide_total_rounds(len(players))
    session.total_rounds = total_rounds
    await db.upsert_game(chat_id, total_rounds=total_rounds)

    avoid_openings = await variety.recent_ai_avoid_list(chat_id, "opening", limit=5)
    opening = await ai_engine.generate_opening(scenario["title"], scenario["hook"], avoid_openings)
    await variety.mark_ai_text_used(chat_id, "opening", opening)
    await memory.remember_event(chat_id, 0, f"بداية القصة: {opening}")

    await telegram_utils.safe_send(bot, 
        chat_id,
        f"🎬 **{scenario['title']}**\n\n{opening}\n\n"
        f"👥 عدد اللاعبين: {len(players)} — عدد الجولات المتوقع: {total_rounds}\n"
        f"🎭 كل لاعب يحمل الآن دورًا وسرًا خاصًا به، سيصله عبر رسالة خاصة إن كان قد بدأ محادثة مع البوت.",
        parse_mode="Markdown",
    )

    await _assign_secrets(bot, chat_id, scenario["title"], players)

    for round_number in range(1, total_rounds + 1):
        session.round_number = round_number
        await _run_round(bot, chat_id, session, round_number, total_rounds)

    await _run_ending(bot, chat_id, session, scenario)
    await db.upsert_game(chat_id, status="finished", phase="finished")


async def _assign_secrets(bot, chat_id: int, scenario_title: str, players):
    for user_id, full_name, _username in players:
        player_row = await db.get_player_row(chat_id, user_id)
        role = roles_module.get_role(player_row["role_id"]) if player_row and player_row["role_id"] else None

        # أرسل بطاقة الدور الكاملة أولًا (هدف علني/سري، قدرة، نقطة ضعف...).
        if role is not None:
            delivered_card = await telegram_utils.safe_send(
                bot, user_id, roles_module.role_card_text(role), parse_mode="Markdown"
            )
            if not delivered_card:
                logger.info("Could not DM role card to user_id=%s (needs to start bot privately first)", user_id)

        avoid = await variety.recent_ai_avoid_list(chat_id, "secret", limit=6)
        role_name = role.name if role else "الحاضر"
        base_secret = role.secret_template if role else None
        secret = await ai_engine.secret_for_player(scenario_title, role_name, avoid)
        if base_secret:
            # اجمع السر المرتبط بالدور تحديدًا مع نكهة السر المولّد بالذكاء
            # الاصطناعي، حتى لا تتشابه أسرار حاملي نفس الدور بين مباراة وأخرى.
            secret = f"{base_secret}\n\n(إضافة خاصة بهذه الجولة: {secret})"
        await variety.mark_ai_text_used(chat_id, "secret", secret)
        await db.add_secret(chat_id, user_id, secret)
        delivered = await telegram_utils.safe_send(
            bot, user_id, f"🤫 **سرّك الخاص في هذه الجولة:**\n\n{secret}", parse_mode="Markdown"
        )
        if not delivered:
            logger.info("Could not DM secret to user_id=%s (needs to start bot privately first)", user_id)


# ------------------------------------------------------------------ ROUND --

async def _run_round(bot, chat_id: int, session: GameSession, round_number: int, total_rounds: int):
    session.phase = "event"
    await db.upsert_game(chat_id, round_number=round_number, phase="event")
    mem_context = await memory.build_memory_context(chat_id, session.scenario_title)

    if round_number > 1:
        avoid_events = await variety.recent_ai_avoid_list(chat_id, "event", limit=6)
        event_text = await ai_engine.generate_event(mem_context, avoid_events)
        await variety.mark_ai_text_used(chat_id, "event", event_text)
        await telegram_utils.safe_send(bot, chat_id, f"🌒 {event_text}")
        await memory.remember_event(chat_id, round_number, event_text, importance=1)

    session.phase = "question"
    avoid_questions = await variety.recent_ai_avoid_list(chat_id, "question", limit=10)
    mem_context = await memory.build_memory_context(chat_id, session.scenario_title)
    question = await ai_engine.create_round_question(avoid_questions, mem_context)
    await variety.mark_ai_text_used(chat_id, "question", question)

    await db.create_round(chat_id, round_number, question)
    await db.upsert_game(chat_id, phase="discussion")

    await telegram_utils.safe_send(bot, 
        chat_id,
        f"📖 **الجولة {round_number} من {total_rounds}**\n\n**المسألة:**\n{question}\n\n"
        "💬 النقاش مفتوح الآن.",
        parse_mode="Markdown",
    )

    await _run_discussion_window(bot, chat_id, round_number, session)

    discussion = await memory.get_discussion_text(chat_id, round_number)
    await memory.remember_round(chat_id, round_number, question, discussion)
    await memory.compact_if_needed(chat_id)
    await db.close_round(chat_id, round_number)

    await _run_deep_phases(bot, chat_id, session, round_number, total_rounds, question)

    session.phase = "analysis"
    mem_context = await memory.build_memory_context(chat_id, session.scenario_title)
    discussion = await memory.get_discussion_text(chat_id, round_number)
    ending_note = await ai_engine.narrate_round(question, discussion, mem_context)
    await telegram_utils.safe_send(bot, chat_id, f"🤖 **تحليل الجولة**\n\n{ending_note}", parse_mode="Markdown")
    await memory.remember_event(chat_id, round_number, f"خلاصة الجولة {round_number}: {ending_note}", importance=1)


async def _run_discussion_window(bot, chat_id: int, round_number: int, session: GameSession):
    """ينتظر مدة النقاش بلا تجميد البوت. المدة الأساسية تُحسب من حالة اللعبة
    الفعلية (رقم الجولة، عدد اللاعبين، الأدلة المتراكمة)، وتستمر بالتزايد
    أثناء النقاش نفسه طالما النشاط الفعلي (عدد الرسائل) لا يزال مرتفعًا قرب
    نهاية الوقت — وليس تمديدًا واحدًا فقط، بل بقدر ما يستدعيه النقاش حتى
    السقف الأقصى. كما تحترم طلبات التمديد اليدوية من المشرف (/extend)
    والإيقاف المؤقت (/pause)."""
    from config import MAX_DISCUSSION_SECONDS, DISCUSSION_POLL_INTERVAL_SECONDS

    player_count = len(await db.get_players(chat_id))
    evidence_count = len(await db.get_evidence(chat_id, limit=50))
    target = phases.discussion_seconds(round_number, player_count, evidence_count)

    elapsed = 0
    last_count = 0

    while elapsed < target:
        if session.paused:
            await session.pause_event.wait()
            continue

        step = min(DISCUSSION_POLL_INTERVAL_SECONDS, target - elapsed)
        await _interruptible_sleep(session, step)
        elapsed += step

        if session.pending_extension:
            added = session.pending_extension
            session.pending_extension = 0
            target = min(target + added, MAX_DISCUSSION_SECONDS)
            await telegram_utils.safe_send(
                bot, chat_id, f"⏳ تم تمديد وقت النقاش {added} ثانية إضافية بطلب من المشرف."
            )
            continue

        # كلما اقتربنا من نهاية الوقت الحالي، نتحقق من نشاط النقاش الفعلي
        # ونمدّد بقدر حيويته، وليس بمقدار ثابت دائمًا — وقد يتكرر هذا أكثر
        # من مرة إن استمر النقاش حيويًا، حتى السقف الأقصى.
        if target < MAX_DISCUSSION_SECONDS and elapsed >= target - DISCUSSION_POLL_INTERVAL_SECONDS:
            count_now = await db.count_recent_messages(chat_id, round_number)
            recent_activity = count_now - last_count
            last_count = count_now
            if recent_activity >= 3:
                extra = min(20 + recent_activity * 5, MAX_DISCUSSION_SECONDS - target)
                if extra > 0:
                    target += extra
                    await telegram_utils.safe_send(
                        bot, chat_id, f"⏳ النقاش لا يزال حيويًا. تم تمديد الوقت {extra} ثانية إضافية."
                    )


async def _run_deep_phases(bot, chat_id, session: GameSession, round_number, total_rounds, question):
    player_count = len(await db.get_players(chat_id))
    chosen = phases.choose_deep_phases(round_number, session.used_deep_phases, player_count)
    session.used_deep_phases.extend(chosen)

    for phase_name in chosen:
        session.phase = phase_name
        await db.upsert_game(chat_id, phase=phase_name)
        mem_context = await memory.build_memory_context(chat_id, session.scenario_title)
        discussion = await memory.get_discussion_text(chat_id, round_number)

        if phase_name == "philosophical":
            topic = await variety.pick_philosophical_topic(chat_id)
            text = await ai_engine.philosophical_phase(topic, discussion, mem_context)
            await telegram_utils.safe_send(bot, chat_id, f"🜂 **مرحلة فلسفية — {topic}**\n\n{text}", parse_mode="Markdown")
            await memory.remember_event(chat_id, round_number, f"مرحلة فلسفية ({topic}): {text}")
            from config import PHILOSOPHICAL_DISCUSSION_SECONDS

            await _interruptible_sleep(session, PHILOSOPHICAL_DISCUSSION_SECONDS)

        elif phase_name == "evidence":
            content, reliability = await ai_engine.evidence_phase(discussion, mem_context)
            await db.add_evidence(chat_id, round_number, content, reliability)
            await telegram_utils.safe_send(bot, chat_id, f"🔎 **دليل جديد**\n\n{content}")
            await memory.remember_event(chat_id, round_number, f"دليل ({reliability}): {content}")

        elif phase_name == "investigation":
            avoid = await variety.recent_ai_avoid_list(chat_id, "interrogation", limit=6)
            q = await ai_engine.interrogation_question(discussion, mem_context, avoid)
            await variety.mark_ai_text_used(chat_id, "interrogation", q)
            await telegram_utils.safe_send(bot, chat_id, f"🕵️ **تحقيق**\n\n{q}")
            await memory.remember_event(chat_id, round_number, f"سؤال تحقيق: {q}")

        elif phase_name == "interrogation":
            avoid = await variety.recent_ai_avoid_list(chat_id, "interrogation", limit=6)
            q = await ai_engine.interrogation_question(discussion, mem_context, avoid)
            await variety.mark_ai_text_used(chat_id, "interrogation", q)
            await telegram_utils.safe_send(bot, chat_id, f"❓ **استجواب**\n\n{q}\n\nلأي لاعب فرصة الرد أو الدفاع عن نفسه.")
            await memory.remember_event(chat_id, round_number, f"استجواب: {q}")

        elif phase_name == "decision":
            template = await variety.pick_decision_template(chat_id)
            prompt = await ai_engine.decision_context(template["prompt"], mem_context)
            await db.add_decision(chat_id, round_number, template["type"], prompt)
            await telegram_utils.safe_send(bot, chat_id, f"⚖️ **قرار جماعي**\n\n{prompt}\n\nناقشوا واتفقوا على رأي جماعي.")
            await memory.remember_decision(chat_id, round_number, template["type"], prompt)

        elif phase_name == "secret_decision":
            await _run_secret_decision(bot, chat_id, round_number, mem_context, session)

        elif phase_name == "alliance":
            text = await ai_engine.alliance_phase(discussion, mem_context)
            await telegram_utils.safe_send(bot, chat_id, f"🤝 **تحوّلات في العلاقات**\n\n{text}")
            await memory.remember_event(chat_id, round_number, f"علاقات: {text}")

        elif phase_name == phases.CONFRONTATION_PHASE:
            await _run_confrontation(bot, chat_id, session, round_number, discussion, mem_context)

    if phases.should_vote_this_round(round_number, total_rounds):
        await _run_group_vote(bot, chat_id, round_number, session)


# ----------------------------------------------------------- CONFRONTATION -

async def _run_confrontation(
    bot, chat_id: int, session: GameSession, round_number: int, discussion: str, mem_context: str
):
    """مواجهة بين لاعبين: اتهام → دفاع → رد المتّهِم → رد المتّهَم → تصويت جماعي
    على مدى إقناع الطرفين. أي مرحلة لم يكتبها اللاعب المعني خلال الوقت المتاح
    يتولاها الراوي (ai_engine) تلقائيًا حتى لا تتوقف الجولة أبدًا بانتظار أحد.
    """
    from config import (
        CONFRONTATION_STAGE_WINDOW_SECONDS,
        CONFRONTATION_REPLY_WINDOW_SECONDS,
        CONFRONTATION_VOTE_WINDOW_SECONDS,
    )

    players = await db.get_players(chat_id)
    if len(players) < 2:
        return

    candidates = [p for p in players if p[0] not in session.recent_confrontation_accused[-1:]] or players
    accuser, accused = random.sample(candidates, 2) if len(candidates) >= 2 else random.sample(players, 2)
    accuser_id, accuser_name = accuser[0], accuser[1]
    accused_id, accused_name = accused[0], accused[1]

    session.recent_confrontation_accused.append(accused_id)
    session.recent_confrontation_accused = session.recent_confrontation_accused[-3:]

    key = (chat_id, round_number)

    async def _capture_stage(stage: str, expected_user_id: int, window: int) -> Optional[str]:
        """يفتح نافذة التقاط لمرحلة واحدة محصورة بلاعب واحد محدد فقط، ثم يغلقها."""
        _confrontation_capture[key] = {"stage": stage, "user_id": expected_user_id, "text": None}
        await _interruptible_sleep(session, window)
        slot = _confrontation_capture.pop(key, None)
        return slot.get("text") if slot else None

    await telegram_utils.safe_send(
        bot, chat_id,
        f"🎭 **مواجهة**\n\n"
        f"يواجه {accuser_name} الآن {accused_name} بشيء لاحظه في النقاش.\n\n"
        f"⏳ لدى {accuser_name} {CONFRONTATION_STAGE_WINDOW_SECONDS} ثانية لكتابة اتهامه في المجموعة.",
    )
    accusation = await _capture_stage(
        "accusation", accuser_id, CONFRONTATION_STAGE_WINDOW_SECONDS
    ) or await ai_engine.confrontation_accusation(discussion, mem_context, accuser_name, accused_name)
    await telegram_utils.safe_send(bot, chat_id, f"👉 **اتهام {accuser_name}:**\n\n{accusation}")

    await telegram_utils.safe_send(
        bot, chat_id,
        f"⏳ لدى {accused_name} {CONFRONTATION_STAGE_WINDOW_SECONDS} ثانية للرد والدفاع عن نفسه.",
    )
    defense = await _capture_stage(
        "defense", accused_id, CONFRONTATION_STAGE_WINDOW_SECONDS
    ) or await ai_engine.confrontation_defense(accusation, discussion, mem_context, accused_name)
    await telegram_utils.safe_send(bot, chat_id, f"🛡️ **دفاع {accused_name}:**\n\n{defense}")

    await telegram_utils.safe_send(
        bot, chat_id, f"⏳ رد أخير: {CONFRONTATION_REPLY_WINDOW_SECONDS} ثانية لكل طرف."
    )
    accuser_reply = await _capture_stage(
        "accuser_reply", accuser_id, CONFRONTATION_REPLY_WINDOW_SECONDS
    ) or await ai_engine.confrontation_rebuttal(accusation, defense, accuser_name, is_accuser=True)
    await telegram_utils.safe_send(bot, chat_id, f"↩️ {accuser_name}: {accuser_reply}")

    defense_reply = await _capture_stage(
        "defense_reply", accused_id, CONFRONTATION_REPLY_WINDOW_SECONDS
    ) or await ai_engine.confrontation_rebuttal(accusation, defense, accused_name, is_accuser=False)
    await telegram_utils.safe_send(bot, chat_id, f"↩️ {accused_name}: {defense_reply}")

    # ---- تصويت: هل كان دفاع المتّهَم مقنعًا؟ ----
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    _confrontation_votes[key] = {}
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ مقنع", callback_data=f"confrvote:{chat_id}:{round_number}:convincing")
    kb.button(text="❌ غير مقنع", callback_data=f"confrvote:{chat_id}:{round_number}:unconvincing")
    kb.button(text="🤔 غير متأكد", callback_data=f"confrvote:{chat_id}:{round_number}:unclear")
    kb.adjust(3)

    await telegram_utils.safe_send(
        bot, chat_id,
        f"🗳️ **تصويت:** هل كان دفاع {accused_name} مقنعًا؟",
        reply_markup=kb.as_markup(),
    )
    await _interruptible_sleep(session, CONFRONTATION_VOTE_WINDOW_SECONDS)
    votes = _confrontation_votes.pop(key, {})

    convinced = sum(1 for v in votes.values() if v == "convincing")
    unconvinced = sum(1 for v in votes.values() if v == "unconvincing")
    unsure = sum(1 for v in votes.values() if v == "unclear")

    if convinced > unconvinced and convinced > unsure:
        verdict, verdict_label = "convincing", "مقنع"
    elif unconvinced >= convinced and unconvinced >= unsure and (unconvinced or unsure):
        verdict, verdict_label = "unconvincing", "غير مقنع"
    else:
        verdict, verdict_label = "unclear", "غير حاسم"

    outcome_note = await ai_engine.confrontation_outcome_narration(accusation, defense, mem_context, verdict_label)
    await telegram_utils.safe_send(
        bot, chat_id,
        f"📊 **نتيجة المواجهة — {verdict_label}** "
        f"(✅ {convinced} · ❌ {unconvinced} · 🤔 {unsure})\n\n{outcome_note}",
    )

    await db.add_confrontation(
        chat_id, round_number, accuser_id, accuser_name, accused_id, accused_name,
        accusation, defense, accuser_reply, defense_reply, verdict,
        convinced, unconvinced, unsure, outcome_note,
    )
    await memory.remember_decision(
        chat_id, round_number, "confrontation",
        f"مواجهة {accuser_name}↔{accused_name}: {verdict_label} — {outcome_note}",
    )

    # فرصة صغيرة أن تُسفر مواجهة حادة عن دليل جديد يعقّد القضية أكثر بدل أن تحسمها.
    if verdict != "unclear" and random.random() < 0.25:
        content, reliability = await ai_engine.evidence_phase(discussion, mem_context)
        await db.add_evidence(chat_id, round_number, content, reliability)
        await telegram_utils.safe_send(bot, chat_id, f"🔎 **دليل جديد ظهر أثناء المواجهة**\n\n{content}")
        await memory.remember_event(chat_id, round_number, f"دليل بعد مواجهة ({reliability}): {content}")


def record_confrontation_text(chat_id: int, round_number: int, user_id: int, text: str) -> bool:
    """يلتقط رسالة من اللاعب المسموح له بالكتابة في مرحلة المواجهة النشطة حاليًا
    فقط (المتّهِم أو المتّهَم بحسب المرحلة)؛ رسائل أي لاعب آخر أو خارج نافذة
    الالتقاط الحالية تُتجاهَل هنا (لكنها تبقى تُسجَّل كنقاش عادي في db.messages)."""
    key = (chat_id, round_number)
    slot = _confrontation_capture.get(key)
    if slot is None or slot.get("user_id") != user_id or slot.get("text") is not None:
        return False
    slot["text"] = text
    return True


def record_confrontation_vote(chat_id: int, round_number: int, voter_id: int, choice: str) -> bool:
    key = (chat_id, round_number)
    if key in _confrontation_votes:
        _confrontation_votes[key][voter_id] = choice
        return True
    return False


# --------------------------------------------------------- SECRET DECISION -

async def _run_secret_decision(bot, chat_id: int, round_number: int, mem_context: str, session: GameSession):
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    template = await variety.pick_decision_template(chat_id)
    prompt = await ai_engine.decision_context(template["prompt"], mem_context)
    key = (chat_id, round_number)
    _secret_answers[key] = {}

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ نعم", callback_data=f"secretdec:{chat_id}:{round_number}:yes")
    kb.button(text="❌ لا", callback_data=f"secretdec:{chat_id}:{round_number}:no")

    await telegram_utils.safe_send(bot, 
        chat_id,
        f"🔒 **قرار سرّي**\n\n{prompt}\n\n"
        "كل لاعب سيصله هذا القرار في الخاص (يجب أن يكون قد بدأ محادثة مع البوت مسبقًا). "
        "النتيجة الإجمالية فقط ستُعلن، دون كشف اختيار أي شخص.",
        parse_mode="Markdown",
    )

    players = await db.get_players(chat_id)
    reached = 0
    for user_id, _name, _username in players:
        delivered = await telegram_utils.safe_send(
            bot, user_id, f"🔒 قرار سرّي من الجولة {round_number}:\n\n{prompt}", reply_markup=kb.as_markup()
        )
        if delivered:
            reached += 1

    if reached == 0:
        await telegram_utils.safe_send(bot, chat_id, "لم يتمكن أي لاعب من استلام القرار في الخاص، فتم تجاوز هذه المرحلة بهدوء.")
        _secret_answers.pop(key, None)
        return

    from config import SECRET_DECISION_WINDOW_SECONDS

    await _interruptible_sleep(session, SECRET_DECISION_WINDOW_SECONDS)

    answers = _secret_answers.pop(key, {})
    yes_count = sum(1 for v in answers.values() if v == "yes")
    no_count = sum(1 for v in answers.values() if v == "no")
    outcome = f"{yes_count} اختاروا نعم، و{no_count} اختاروا لا (من أصل {reached} تم الوصول إليهم)."
    await db.add_decision(chat_id, round_number, template["type"], prompt, outcome)
    await memory.remember_decision(chat_id, round_number, template["type"] + " (سرّي)", outcome)
    await telegram_utils.safe_send(bot, chat_id, f"🔓 **نتيجة القرار السرّي:**\n\n{outcome}")


def record_secret_answer(chat_id: int, round_number: int, user_id: int, choice: str):
    key = (chat_id, round_number)
    if key in _secret_answers:
        _secret_answers[key][user_id] = choice
        return True
    return False


# ------------------------------------------------------------- GROUP VOTE --

async def _run_group_vote(bot, chat_id: int, round_number: int, session: GameSession):
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    players = await db.get_players(chat_id)
    if len(players) < 2:
        return

    key = (chat_id, round_number)
    _vote_answers[key] = {}

    kb = InlineKeyboardBuilder()
    for user_id, full_name, _username in players:
        kb.button(text=full_name[:24], callback_data=f"vote:{chat_id}:{round_number}:{user_id}")
    kb.button(text="🤷 امتناع", callback_data=f"vote:{chat_id}:{round_number}:0")
    kb.adjust(2)

    await telegram_utils.safe_send(bot, 
        chat_id,
        "🗳️ **تصويت الشك**\n\nمن يبدو الأكثر إثارة للريبة حتى الآن؟ هذا تصويت للنقاش لا يقصي أحدًا بالضرورة.",
        reply_markup=kb.as_markup(),
        parse_mode="Markdown",
    )

    from config import GROUP_VOTE_WINDOW_SECONDS

    await _interruptible_sleep(session, GROUP_VOTE_WINDOW_SECONDS)

    votes = _vote_answers.pop(key, {})
    if not votes:
        await telegram_utils.safe_send(bot, chat_id, "لم يشارك أحد في التصويت هذه المرة.")
        return

    tally: Dict[int, int] = {}
    for target in votes.values():
        tally[target] = tally.get(target, 0) + 1

    id_to_name = {p[0]: p[1] for p in players}
    lines = []
    for target_id, count in sorted(tally.items(), key=lambda kv: -kv[1]):
        name = "امتناع" if target_id == 0 else id_to_name.get(target_id, "لاعب غير معروف")
        lines.append(f"- {name}: {count} صوت")

    result_text = "\n".join(lines)
    await telegram_utils.safe_send(bot, chat_id, f"📊 **نتيجة تصويت الشك:**\n\n{result_text}")
    await db.add_decision(chat_id, round_number, "suspicion_vote", "تصويت الشك", result_text)
    await memory.remember_decision(chat_id, round_number, "تصويت الشك", result_text)


def record_vote(chat_id: int, round_number: int, voter_id: int, target_id: int):
    key = (chat_id, round_number)
    if key in _vote_answers:
        _vote_answers[key][voter_id] = target_id
        return True
    return False


# ---------------------------------------------------------------- ENDING ---

async def _run_ending(bot, chat_id: int, session: GameSession, scenario: dict):
    session.phase = "ending"
    await db.upsert_game(chat_id, phase="ending")

    ending_type = await variety.pick_ending_type(chat_id)
    ending_label = ENDING_LABELS.get(ending_type, ending_type)
    mem_context = await memory.build_memory_context(chat_id, session.scenario_title)
    ending_text = await ai_engine.generate_ending(mem_context, ending_type, ending_label)

    await telegram_utils.safe_send(bot, 
        chat_id,
        f"🏁 **نهاية القصة — {ending_label}**\n\n{ending_text}",
        parse_mode="Markdown",
    )
    await db.add_game_history(chat_id, scenario["title"], ending_type, ending_text)
    await telegram_utils.safe_send(bot, 
        chat_id,
        "انتهت هذه الجولة. جولة جديدة ستحمل سيناريو وأسئلة ومسارًا مختلفًا. "
        "استخدموا /start لفتح ردهة انضمام جديدة، وستبدأ الجولة تلقائيًا فور اكتمال العدد.",
    )


# --------------------------------------------------------------- MESSAGES --

async def record_discussion(chat_id: int, user_id: int, full_name: str, text: str):
    session = sessions.get(chat_id)
    if not session or not session.active:
        return
    if session.phase == phases.CONFRONTATION_PHASE:
        record_confrontation_text(chat_id, session.round_number, user_id, text)
        await db.save_message(chat_id, session.round_number, user_id, full_name, text)
        return
    if session.phase not in {"question", "discussion", "philosophical", "investigation", "interrogation"}:
        return
    await db.save_message(chat_id, session.round_number, user_id, full_name, text)


async def cancel_game(chat_id: int) -> bool:
    session = sessions.get(chat_id)
    if not session or not session.task:
        return False
    session.task.cancel()
    return True
