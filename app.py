import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramAPIError

from config import BOT_TOKEN, GAME_MIN_PLAYERS, GAME_MAX_PLAYERS
import abilities
import db
import game
import roles as roles_module
import telegram_utils
from texts import GAME_EXPLANATION, RULES_TEXT

DIFFICULTY_LABELS = {
    "easy": "🟢 سهل",
    "medium": "🔵 متوسط",
    "hard": "🟠 صعب",
    "expert": "🔴 خبير",
    "impossible": "☠️ مستحيل",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app")

dp = Dispatcher()


def join_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="🚪 انضمام", callback_data="join_game")
    return kb.as_markup()


async def _is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in {"creator", "administrator"}
    except TelegramAPIError:
        return False


# ------------------------------------------------------------------ START --

async def _send_lobby_prompt(message: Message):
    """يعرض زر الانضمام إن كانت الردهة مفتوحة فعلًا، وإلا يوضّح للمستخدم أن
    جولة أخرى تعمل حاليًا (بلا أي زر بدء يدوي؛ اللعبة تبدأ تلقائيًا بمجرد
    اكتمال العدد)."""
    chat_id = message.chat.id
    if not game.is_registration_open(chat_id):
        await message.answer(
            "🚫 هناك جولة قيد التشغيل حاليًا في هذه المجموعة. "
            "بمجرد انتهائها ستُفتح ردهة انضمام جديدة تلقائيًا."
        )
        return

    sent = await message.answer(GAME_EXPLANATION, reply_markup=join_keyboard(), parse_mode="Markdown")
    game.register_lobby_message(chat_id, sent.message_id)


@dp.message(Command("start"))
async def start(message: Message):
    await _send_lobby_prompt(message)


@dp.message(Command("help"))
async def help_command(message: Message):
    await _send_lobby_prompt(message)


@dp.message(Command("rules"))
async def rules_command(message: Message):
    await message.answer(RULES_TEXT, parse_mode="Markdown")


# ------------------------------------------------------------------- JOIN --

@dp.callback_query(F.data == "join_game")
async def join_game(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    user = callback.from_user

    ok, payload = await game.try_join(chat_id, user.id, user.full_name, user.username)
    if not ok:
        await callback.answer(payload, show_alert=True)
        return

    count = payload["count"]
    target = payload["target"]

    await callback.answer("تم انضمامك. ✅")
    await callback.message.answer(
        f"تم انضمام **{user.full_name}** إلى الجولة.\n👥 عدد اللاعبين الآن: **{count}/{target}**",
        parse_mode="Markdown",
    )

    if payload["just_became_full"]:
        # اكتمل العدد بهذا الانضمام بالذات: أغلق التسجيل وابدأ الجولة فورًا،
        # دون أي أمر يدوي أو زر "ابدأ اللعبة".
        await game.close_registration_and_launch(callback.bot, chat_id, user.id)


# ----------------------------------------------------------------- STATUS --

STATUS_LABELS = {
    game.GameStatus.WAITING: "بانتظار أول انضمام ⏳",
    game.GameStatus.JOINING: f"التسجيل مفتوح 🚪 ({GAME_MIN_PLAYERS}-{GAME_MAX_PLAYERS} لاعبين)",
    game.GameStatus.FULL: "اكتمل العدد، يتم الإغلاق 🔒",
    game.GameStatus.STARTING: "يتم تجهيز الجولة ⚙️",
    game.GameStatus.RUNNING: "تعمل 🎮",
    game.GameStatus.FINISHED: "انتهت آخر جولة 🏁 — /start لردهة جديدة",
}


@dp.message(Command("status"))
async def status(message: Message):
    session = game.state_for(message.chat.id)
    players = await db.get_players(message.chat.id)
    state_label = STATUS_LABELS.get(session.status, session.status)
    if session.paused:
        state_label = "متوقفة مؤقتًا ⏸️"
    round_label = f"{session.round_number}/{session.total_rounds}" if session.active else "-"
    await message.answer(
        f"👥 اللاعبون: {len(players)}/{GAME_MAX_PLAYERS}\n🎮 حالة اللعبة: {state_label}\n"
        f"🧭 الجولة: {round_label}\n🧠 المرحلة: {session.phase}"
    )


@dp.message(Command("players"))
async def players_command(message: Message):
    players = await db.get_players(message.chat.id)
    if not players:
        await message.answer("لا يوجد لاعبون منضمّون بعد.")
        return
    lines = [f"{i+1}. {name}" for i, (_uid, name, _uname) in enumerate(players)]
    await message.answer(f"👥 اللاعبون ({len(players)}/{GAME_MAX_PLAYERS}):\n" + "\n".join(lines))


@dp.message(Command("end"))
async def end_command(message: Message, bot: Bot):
    if not await _is_admin(bot, message.chat.id, message.from_user.id):
        await message.answer("فقط مشرف المجموعة يستطيع إنهاء الجولة.")
        return

    cancelled = await game.cancel_game(message.chat.id)
    if cancelled:
        await message.answer("جارٍ إنهاء الجولة الحالية...")
    else:
        await message.answer("لا توجد جولة نشطة الآن.")


# --------------------------------------------------------- PAUSE / RESUME --

@dp.message(Command("pause"))
async def pause_command(message: Message, bot: Bot):
    if not await _is_admin(bot, message.chat.id, message.from_user.id):
        await message.answer("فقط مشرف المجموعة يستطيع إيقاف الجولة مؤقتًا.")
        return
    if game.pause_game(message.chat.id):
        await message.answer("⏸️ تم إيقاف الجولة مؤقتًا. لن تمر أي مؤقتات حتى استخدام /resume.")
    else:
        await message.answer("لا توجد جولة نشطة يمكن إيقافها مؤقتًا الآن.")


@dp.message(Command("resume"))
async def resume_command(message: Message, bot: Bot):
    if not await _is_admin(bot, message.chat.id, message.from_user.id):
        await message.answer("فقط مشرف المجموعة يستطيع استئناف الجولة.")
        return
    if game.resume_game(message.chat.id):
        await message.answer("▶️ تابعت الجولة من حيث توقفت.")
    else:
        await message.answer("لا توجد جولة متوقفة مؤقتًا الآن.")


@dp.message(Command("extend"))
async def extend_command(message: Message, bot: Bot):
    if not await _is_admin(bot, message.chat.id, message.from_user.id):
        await message.answer("فقط مشرف المجموعة يستطيع تمديد وقت النقاش.")
        return

    parts = (message.text or "").split(maxsplit=1)
    seconds = 60
    if len(parts) > 1 and parts[1].strip().isdigit():
        seconds = max(10, min(300, int(parts[1].strip())))

    if game.request_extension(message.chat.id, seconds):
        await message.answer(f"⏳ سيُضاف {seconds} ثانية لوقت النقاش الحالي.")
    else:
        await message.answer("لا توجد جولة نشطة الآن لتمديد وقتها.")


# ------------------------------------------------------------------- KICK --

@dp.message(Command("kick"))
async def kick_command(message: Message, bot: Bot):
    if not await _is_admin(bot, message.chat.id, message.from_user.id):
        await message.answer("فقط مشرف المجموعة يستطيع إزالة لاعب.")
        return
    if game.is_running(message.chat.id):
        await message.answer("لا يمكن إزالة لاعب أثناء جولة نشطة. استخدم /end أولًا إذا لزم.")
        return
    if not message.reply_to_message:
        await message.answer("استخدم هذا الأمر كردّ (reply) على رسالة اللاعب الذي تريد إزالته.")
        return

    target = message.reply_to_message.from_user
    removed = await db.remove_player(message.chat.id, target.id)
    if removed:
        await message.answer(f"تمت إزالة **{target.full_name}** من الجولة.", parse_mode="Markdown")
    else:
        await message.answer("هذا الشخص ليس منضمًا للجولة أصلًا.")


# --------------------------------------------------------------- DIFFICULTY -

@dp.message(Command("difficulty"))
async def difficulty_command(message: Message, bot: Bot):
    if not await _is_admin(bot, message.chat.id, message.from_user.id):
        await message.answer("فقط مشرف المجموعة يستطيع ضبط مستوى الصعوبة.")
        return
    if game.is_running(message.chat.id):
        await message.answer("لا يمكن تغيير الصعوبة أثناء جولة نشطة. استخدم الأمر قبل اكتمال العدد وبدء الجولة.")
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or parts[1].strip().lower() not in DIFFICULTY_LABELS:
        current = await db.get_difficulty(message.chat.id)
        options = "\n".join(f"- `{k}` → {v}" for k, v in DIFFICULTY_LABELS.items())
        await message.answer(
            f"الصعوبة الحالية: {DIFFICULTY_LABELS.get(current, current)}\n\n"
            f"لتغييرها استخدم: `/difficulty easy|medium|hard|expert|impossible`\n\n{options}",
            parse_mode="Markdown",
        )
        return

    chosen = parts[1].strip().lower()
    await db.set_difficulty(message.chat.id, chosen)
    await message.answer(f"✅ تم ضبط مستوى الصعوبة على: {DIFFICULTY_LABELS[chosen]}")


# -------------------------------------------------------------- MY ROLE ----

@dp.message(Command("myrole"))
async def myrole_command(message: Message):
    if message.chat.type != "private":
        await message.answer("أرسل لي هذا الأمر في محادثة خاصة لعرض بطاقة دورك بأمان.")
        return

    chat_ids = await db.get_active_game_chat_ids_for_user(message.from_user.id)
    if not chat_ids:
        await message.answer("لا يوجد دور نشط لك حاليًا. انتظر بدء جولة تشارك فيها.")
        return

    for chat_id in chat_ids:
        player = await db.get_player_row(chat_id, message.from_user.id)
        role = roles_module.get_role(player["role_id"]) if player else None
        if role:
            await message.answer(roles_module.role_card_text(role), parse_mode="Markdown")


# --------------------------------------------------------------- ABILITY ---

def _ability_target_keyboard(chat_id: int, round_number: int, players, exclude_user_id: int):
    kb = InlineKeyboardBuilder()
    for user_id, full_name, _username in players:
        if user_id == exclude_user_id:
            continue
        kb.button(text=full_name[:24], callback_data=f"ability_t:{chat_id}:{round_number}:{user_id}")
    kb.adjust(2)
    return kb.as_markup()


@dp.message(Command("ability"))
async def ability_command(message: Message):
    if message.chat.type != "private":
        await message.answer("استخدم قدرتك من هنا فقط في محادثتنا الخاصة، حفاظًا على سريتها.")
        return

    chat_ids = await db.get_active_game_chat_ids_for_user(message.from_user.id)
    if not chat_ids:
        await message.answer("لا توجد جولة نشطة لك حاليًا لاستخدام أي قدرة فيها.")
        return

    # عادة لاعب واحد سيكون في جولة نشطة واحدة فقط في وقت معين.
    chat_id = chat_ids[0]
    session = game.state_for(chat_id)
    round_number = session.round_number

    player = await db.get_player_row(chat_id, message.from_user.id)
    role = roles_module.get_role(player["role_id"]) if player else None
    if role is None:
        await message.answer("تعذّر تحديد دورك الحالي.")
        return

    if role.ability_type == "passive":
        await message.answer(f"دور «{role.name}» ليس له قدرة تُستخدم يدويًا؛ تأثيره سردي دائم طوال اللعبة.")
        return

    if player["ability_uses_left"] <= 0:
        await message.answer(f"استنفدت كل استخدامات قدرة «{role.ability_name}» هذه الجولة.")
        return

    if role.needs_target:
        players = await db.get_players(chat_id)
        if len(players) < 2:
            await message.answer("لا يوجد لاعبون كافون لاختيار هدف الآن.")
            return
        await message.answer(
            f"⚡ اختر هدف قدرة «{role.ability_name}»:",
            reply_markup=_ability_target_keyboard(chat_id, round_number, players, message.from_user.id),
        )
        return

    try:
        result = await abilities.use_ability(chat_id, message.from_user.id, round_number, target_id=None)
    except abilities.AbilityError as exc:
        await message.answer(str(exc))
        return
    await message.answer(result)


@dp.callback_query(F.data.startswith("ability_t:"))
async def ability_target_callback(callback: CallbackQuery):
    try:
        _, chat_id_s, round_s, target_s = callback.data.split(":")
        chat_id, round_number, target_id = int(chat_id_s), int(round_s), int(target_s)
    except ValueError:
        await callback.answer()
        return

    try:
        result = await abilities.use_ability(chat_id, callback.from_user.id, round_number, target_id=target_id)
    except abilities.AbilityError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await callback.answer("تم استخدام القدرة.")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass
    await callback.message.answer(result)


# ------------------------------------------------------------- CASE LOG ----

@dp.message(Command("case"))
async def case_command(message: Message):
    events = await db.get_events(message.chat.id, limit=15)
    evidence = await db.get_evidence(message.chat.id, limit=15)
    decisions = await db.get_decisions(message.chat.id, limit=10)
    confrontations = await db.get_confrontations(message.chat.id, limit=8)

    if not events and not evidence and not decisions and not confrontations:
        await message.answer("لا يوجد سجل قضية بعد. ابدأ جولة أولًا عبر /start ثم انتظر اكتمال عدد اللاعبين.")
        return

    lines = ["📜 **سجل القضية حتى الآن**"]
    if events:
        lines.append("\n🌒 *أحداث مهمة:*")
        lines.extend(f"- {e}" for e in events[-10:])
    if evidence:
        lines.append("\n🔎 *أدلة مكتشفة:*")
        lines.extend(f"- ({reliability}) {content}" for content, reliability in evidence[-10:])
    if decisions:
        lines.append("\n⚖️ *قرارات:*")
        for decision_type, prompt, outcome in decisions[-8:]:
            outcome_part = f" → {outcome}" if outcome else ""
            lines.append(f"- [{decision_type}] {prompt}{outcome_part}")
    if confrontations:
        verdict_labels = {"convincing": "مقنع", "unconvincing": "غير مقنع", "unclear": "غير حاسم"}
        lines.append("\n🎭 *مواجهات:*")
        for accuser_name, accused_name, verdict, outcome_note in confrontations:
            label = verdict_labels.get(verdict, verdict)
            lines.append(f"- {accuser_name} ↔ {accused_name}: {label} — {outcome_note}")

    await telegram_utils.safe_send(message.bot, message.chat.id, "\n".join(lines), parse_mode="Markdown")


# -------------------------------------------------------- SECRET DECISION --

@dp.callback_query(F.data.startswith("secretdec:"))
async def secret_decision_callback(callback: CallbackQuery):
    try:
        _, chat_id_s, round_s, choice = callback.data.split(":")
        chat_id, round_number = int(chat_id_s), int(round_s)
    except ValueError:
        await callback.answer()
        return

    recorded = game.record_secret_answer(chat_id, round_number, callback.from_user.id, choice)
    if recorded:
        await callback.answer("تم تسجيل اختيارك سرًا. ✅")
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
    else:
        await callback.answer("انتهت مهلة هذا القرار.", show_alert=True)


# --------------------------------------------------------------- VOTING ---

@dp.callback_query(F.data.startswith("vote:"))
async def vote_callback(callback: CallbackQuery):
    try:
        _, chat_id_s, round_s, target_s = callback.data.split(":")
        chat_id, round_number, target_id = int(chat_id_s), int(round_s), int(target_s)
    except ValueError:
        await callback.answer()
        return

    recorded = game.record_vote(chat_id, round_number, callback.from_user.id, target_id)
    if recorded:
        await callback.answer("تم تسجيل تصويتك.")
    else:
        await callback.answer("انتهت مهلة هذا التصويت.", show_alert=True)


# ----------------------------------------------------------- CONFRONTATION -

@dp.callback_query(F.data.startswith("confrvote:"))
async def confrontation_vote_callback(callback: CallbackQuery):
    try:
        _, chat_id_s, round_s, choice = callback.data.split(":")
        chat_id, round_number = int(chat_id_s), int(round_s)
    except ValueError:
        await callback.answer()
        return

    recorded = game.record_confrontation_vote(chat_id, round_number, callback.from_user.id, choice)
    if recorded:
        await callback.answer("تم تسجيل تصويتك.")
    else:
        await callback.answer("انتهت مهلة هذا التصويت.", show_alert=True)


# ------------------------------------------------------------- DISCUSSION --

@dp.message(F.text & ~F.text.startswith("/"))
async def collect_discussion(message: Message):
    if message.chat.type == "private":
        return  # الرسائل الخاصة لا تُحسب كنقاش جماعي
    await game.record_discussion(
        message.chat.id, message.from_user.id, message.from_user.full_name, message.text
    )


# ------------------------------------------------------------------- MAIN --

async def _recover_interrupted_games(bot: Bot):
    """عند إعادة تشغيل البوت، أي جولة كانت 'running' في قاعدة البيانات تكون قد
    فقدت مهمتها (asyncio.Task) فعليًا مع إعادة التشغيل. نعلّمها كمنقطعة ونخبر
    المجموعة بوضوح بدل أن تبقى عالقة في حالة تبدو نشطة بينما لا شيء يعمل."""
    try:
        stuck = await db.get_chat_ids_by_status("running")
    except Exception:
        logger.exception("Failed to check for interrupted games on startup")
        return

    for chat_id in stuck:
        await db.upsert_game(chat_id, status="interrupted", phase="interrupted")
        await telegram_utils.safe_send(
            chat_id=chat_id,
            bot=bot,
            text="⚠️ انقطعت الجولة السابقة بسبب إعادة تشغيل البوت (مثل تحديث أو صيانة). "
            "استخدموا /start لفتح ردهة انضمام جديدة؛ الجولة ستبدأ تلقائيًا فور اكتمال العدد.",
        )
        logger.info("Marked interrupted game as recovered for chat_id=%s", chat_id)


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN غير موجود. أنشئ ملف .env وضع التوكن داخله، أو اضبطه كمتغير بيئة.")

    await db.init_db()
    bot = Bot(token=BOT_TOKEN)
    await _recover_interrupted_games(bot)
    logger.info("Bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
