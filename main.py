"""
بوت المستذئب (Werewolf / Mafia) لتليجرام
مستوحى من فكرة @werewolfbot - لعبة جماعية تُلعب داخل مجموعات تليجرام.

الأدوار المدعومة:
- المستذئب (Werewolf): يختار ضحية كل ليلة مع بقية المستذئبين.
- العرّاف (Seer): يفحص هوية لاعب كل ليلة.
- الطبيب (Doctor): ينقذ لاعبًا واحدًا كل ليلة.
- القروي (Villager): لا قدرات خاصة، يشارك في النقاش والتصويت.

آلية اللعب:
1) اللاعبون ينضمون عبر /join داخل المجموعة.
2) عند اكتمال العدد، يبدأ المنشئ اللعبة عبر /startgame.
3) يُرسل البوت لكل لاعب دوره في الخاص (لازم يضغط Start على البوت أولاً).
4) دورة ليل/نهار: الليل فيه أفعال سرية عبر الخاص، والنهار فيه نقاش وتصويت
   علني داخل المجموعة عبر أزرار Inline.
5) تنتهي اللعبة إذا فنى المستذئبون (فوز القرويين) أو تساووا/تفوقوا
   عدديًا على بقية اللاعبين (فوز المستذئبين).
"""

import logging
import random
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)
from telegram.error import Forbidden, BadRequest

# ------------------------------------------------------------------------
# الإعدادات
# ------------------------------------------------------------------------

import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

BOT_TOKEN = os.environ.get("BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")
PORT = int(os.environ.get("PORT", "8080"))

MIN_PLAYERS = 4
NIGHT_SECONDS = 45
DISCUSSION_SECONDS = 60
VOTE_SECONDS = 40

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("werewolf-bot")


# ------------------------------------------------------------------------
# النماذج (Models)
# ------------------------------------------------------------------------

class Role(Enum):
    WEREWOLF = auto()
    SEER = auto()
    DOCTOR = auto()
    VILLAGER = auto()


ROLE_NAMES = {
    Role.WEREWOLF: "🐺 مستذئب",
    Role.SEER: "🔮 عرّاف",
    Role.DOCTOR: "💉 طبيب",
    Role.VILLAGER: "👤 قروي",
}

ROLE_DESCRIPTIONS = {
    Role.WEREWOLF: "مهمتك أن تفترس القرويين ليلًا دون أن يُكتشف أمرك.",
    Role.SEER: "كل ليلة يمكنك كشف هوية لاعب واحد (مستذئب أم لا).",
    Role.DOCTOR: "كل ليلة يمكنك حماية لاعب واحد من هجوم المستذئبين.",
    Role.VILLAGER: "لا تملك قدرة خاصة، شارك بالنقاش والتصويت لكشف المستذئبين.",
}


class Phase(Enum):
    LOBBY = auto()
    NIGHT = auto()
    DAY_DISCUSSION = auto()
    DAY_VOTE = auto()
    ENDED = auto()


@dataclass
class Player:
    user_id: int
    name: str
    role: Optional[Role] = None
    alive: bool = True


@dataclass
class Game:
    chat_id: int
    host_id: int
    players: Dict[int, Player] = field(default_factory=dict)
    phase: Phase = Phase.LOBBY
    day_number: int = 0

    # حالة الليل المؤقتة
    wolf_votes: Dict[int, int] = field(default_factory=dict)   # wolf_id -> target_id
    doctor_save: Optional[int] = None
    seer_check: Optional[int] = None

    # حالة التصويت النهاري
    day_votes: Dict[int, int] = field(default_factory=dict)    # voter_id -> target_id
    vote_message_id: Optional[int] = None

    def alive_players(self) -> List[Player]:
        return [p for p in self.players.values() if p.alive]

    def alive_werewolves(self) -> List[Player]:
        return [p for p in self.alive_players() if p.role == Role.WEREWOLF]

    def alive_non_werewolves(self) -> List[Player]:
        return [p for p in self.alive_players() if p.role != Role.WEREWOLF]


# chat_id -> Game
GAMES: Dict[int, Game] = {}
# user_id -> private chat_id متاح (بعد الضغط /start في الخاص)
PRIVATE_CHATS: Dict[int, int] = {}


def build_roles(n: int) -> List[Role]:
    """يوزّع الأدوار حسب عدد اللاعبين."""
    n_wolves = max(1, n // 4)
    roles = [Role.WEREWOLF] * n_wolves
    roles.append(Role.SEER)
    if n >= 6:
        roles.append(Role.DOCTOR)
    while len(roles) < n:
        roles.append(Role.VILLAGER)
    random.shuffle(roles)
    return roles[:n]


# ------------------------------------------------------------------------
# أوامر عامة
# ------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type == "private":
        PRIVATE_CHATS[user.id] = chat.id
        await update.message.reply_text(
            "أهلاً بك! تم تفعيل الرسائل الخاصة، الآن يمكنك الانضمام لأي لعبة "
            "مستذئب داخل مجموعاتك عبر أمر /join.\n\n"
            "أوامر داخل المجموعة:\n"
            "/newgame - إنشاء لعبة جديدة\n"
            "/join - الانضمام للعبة\n"
            "/leave - الانسحاب قبل البدء\n"
            "/players - عرض قائمة اللاعبين\n"
            "/startgame - بدء اللعبة (لمنشئ اللعبة)\n"
            "/stopgame - إلغاء اللعبة"
        )
    else:
        await update.message.reply_text(
            "أهلاً! استخدم /newgame لبدء لعبة مستذئب جديدة في هذه المجموعة.\n"
            "⚠️ يجب على كل لاعب مراسلتي أولاً في الخاص (زر Start) حتى أستطيع "
            "إرسال دوره السري له."
        )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, context)


async def cmd_newgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private":
        await update.message.reply_text("هذا الأمر يعمل داخل مجموعات فقط.")
        return
    if chat.id in GAMES and GAMES[chat.id].phase != Phase.ENDED:
        await update.message.reply_text("توجد لعبة قائمة بالفعل في هذه المجموعة. استخدم /stopgame لإلغائها أولاً.")
        return

    game = Game(chat_id=chat.id, host_id=update.effective_user.id)
    GAMES[chat.id] = game
    await update.message.reply_text(
        "🐺 لعبة مستذئب جديدة بدأت!\n"
        "اكتب /join للانضمام. الحد الأدنى للاعبين: %d\n"
        "عندما يكتمل العدد، اكتب /startgame لبدء الجولة." % MIN_PLAYERS
    )


async def cmd_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    game = GAMES.get(chat.id)
    if not game or game.phase != Phase.LOBBY:
        await update.message.reply_text("لا توجد لعبة بانتظار لاعبين حاليًا. استخدم /newgame لإنشاء واحدة.")
        return
    if user.id in game.players:
        await update.message.reply_text("أنت منضم بالفعل.")
        return
    if user.id not in PRIVATE_CHATS:
        await update.message.reply_text(
            f"👋 {user.first_name}، قبل الانضمام يجب أن تراسلني أولاً في الخاص "
            f"(اضغط على اسمي ثم Start) حتى أستطيع إرسال دورك السري لك."
        )
        return

    game.players[user.id] = Player(user_id=user.id, name=user.first_name)
    await update.message.reply_text(
        f"✅ {user.first_name} انضم! عدد اللاعبين الآن: {len(game.players)}"
    )


async def cmd_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    game = GAMES.get(chat.id)
    if not game or game.phase != Phase.LOBBY:
        await update.message.reply_text("لا يمكن الانسحاب الآن.")
        return
    if user.id in game.players:
        del game.players[user.id]
        await update.message.reply_text(f"{user.first_name} انسحب من اللعبة.")
    else:
        await update.message.reply_text("أنت لست منضمًا أصلًا.")


async def cmd_players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = GAMES.get(update.effective_chat.id)
    if not game or not game.players:
        await update.message.reply_text("لا يوجد لاعبون بعد.")
        return
    names = "\n".join(f"• {p.name}" for p in game.players.values())
    await update.message.reply_text(f"👥 اللاعبون ({len(game.players)}):\n{names}")


async def cmd_stopgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    game = GAMES.get(chat.id)
    if not game:
        await update.message.reply_text("لا توجد لعبة لإلغائها.")
        return
    del GAMES[chat.id]
    await update.message.reply_text("🛑 تم إلغاء اللعبة.")


# ------------------------------------------------------------------------
# بدء اللعبة وتوزيع الأدوار
# ------------------------------------------------------------------------

async def cmd_startgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    game = GAMES.get(chat.id)
    if not game or game.phase != Phase.LOBBY:
        await update.message.reply_text("لا توجد لعبة بانتظار البدء.")
        return
    if user.id != game.host_id:
        await update.message.reply_text("فقط منشئ اللعبة يمكنه بدأها.")
        return
    if len(game.players) < MIN_PLAYERS:
        await update.message.reply_text(
            f"تحتاجون على الأقل {MIN_PLAYERS} لاعبين. العدد الحالي: {len(game.players)}"
        )
        return

    roles = build_roles(len(game.players))
    for player, role in zip(game.players.values(), roles):
        player.role = role

    failed_dm = []
    for player in game.players.values():
        pchat = PRIVATE_CHATS.get(player.user_id)
        try:
            await context.bot.send_message(
                pchat,
                f"🎭 دورك في هذه الجولة: *{ROLE_NAMES[player.role]}*\n"
                f"{ROLE_DESCRIPTIONS[player.role]}",
                parse_mode=ParseMode.MARKDOWN,
            )
        except (Forbidden, BadRequest):
            failed_dm.append(player.name)

    if failed_dm:
        await update.message.reply_text(
            "⚠️ تعذّر إرسال الدور خاصة لـ: " + ", ".join(failed_dm) +
            "\nتأكدوا من فتح محادثة خاصة مع البوت والضغط /start."
        )

    await update.message.reply_text(
        f"🎬 بدأت اللعبة بعدد {len(game.players)} لاعبين!\nحُدّدت الأدوار سرًا في الخاص. تبدأ الآن أول ليلة..."
    )
    await start_night(update.effective_chat.id, context)


# ------------------------------------------------------------------------
# مرحلة الليل
# ------------------------------------------------------------------------

def alive_keyboard(game: Game, prefix: str, exclude_id: Optional[int] = None) -> InlineKeyboardMarkup:
    buttons = []
    for p in game.alive_players():
        if p.user_id == exclude_id:
            continue
        buttons.append([InlineKeyboardButton(p.name, callback_data=f"{prefix}:{game.chat_id}:{p.user_id}")])
    return InlineKeyboardMarkup(buttons)


async def start_night(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    game = GAMES.get(chat_id)
    if not game:
        return
    game.phase = Phase.NIGHT
    game.day_number += 1
    game.wolf_votes.clear()
    game.doctor_save = None
    game.seer_check = None

    await context.bot.send_message(
        chat_id,
        f"🌙 الليلة رقم {game.day_number} بدأت. القرية نائمة...\n"
        f"أصحاب الأدوار الخاصة يتلقون تعليماتهم في الخاص الآن. لديكم {NIGHT_SECONDS} ثانية."
    )

    for wolf in game.alive_werewolves():
        try:
            await context.bot.send_message(
                PRIVATE_CHATS.get(wolf.user_id),
                "🐺 اختر ضحية الليلة:",
                reply_markup=alive_keyboard(game, "kill", exclude_id=wolf.user_id),
            )
        except (Forbidden, BadRequest):
            pass

    for p in game.alive_players():
        if p.role == Role.SEER:
            try:
                await context.bot.send_message(
                    PRIVATE_CHATS.get(p.user_id),
                    "🔮 اختر لاعبًا لتكشف هويته:",
                    reply_markup=alive_keyboard(game, "seer", exclude_id=p.user_id),
                )
            except (Forbidden, BadRequest):
                pass
        elif p.role == Role.DOCTOR:
            try:
                await context.bot.send_message(
                    PRIVATE_CHATS.get(p.user_id),
                    "💉 اختر لاعبًا لتحميه الليلة:",
                    reply_markup=alive_keyboard(game, "save"),
                )
            except (Forbidden, BadRequest):
                pass

    context.job_queue.run_once(
        lambda ctx: resolve_night_wrapper(chat_id, ctx),
        NIGHT_SECONDS,
        name=f"night-{chat_id}",
    )


async def resolve_night_wrapper(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    await resolve_night(chat_id, context)


async def cb_night_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action, chat_id_str, target_id_str = query.data.split(":")
    chat_id, target_id = int(chat_id_str), int(target_id_str)
    game = GAMES.get(chat_id)
    user_id = update.effective_user.id

    if not game or game.phase != Phase.NIGHT:
        await query.answer("انتهت هذه المرحلة.", show_alert=True)
        return

    if action == "kill":
        game.wolf_votes[user_id] = target_id
        await query.answer("✅ تم تسجيل اختيارك.")
        await query.edit_message_text("🐺 تم تسجيل اختيارك للضحية.")
    elif action == "seer":
        game.seer_check = target_id
        target = game.players.get(target_id)
        is_wolf = target.role == Role.WEREWOLF
        await query.answer()
        await query.edit_message_text(
            f"🔮 النتيجة: {target.name} هو "
            + ("🐺 مستذئب!" if is_wolf else "✅ ليس مستذئبًا.")
        )
    elif action == "save":
        game.doctor_save = target_id
        await query.answer("✅ تم تسجيل من ستحميه.")
        await query.edit_message_text("💉 تم تسجيل اختيارك للحماية.")


async def resolve_night(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    game = GAMES.get(chat_id)
    if not game or game.phase != Phase.NIGHT:
        return

    # تحديد ضحية المستذئبين (الأكثر تصويتًا بينهم، أو عشوائي لو لم يصوّت أحد)
    victim_id = None
    if game.wolf_votes:
        tally: Dict[int, int] = {}
        for target in game.wolf_votes.values():
            tally[target] = tally.get(target, 0) + 1
        max_votes = max(tally.values())
        top = [t for t, v in tally.items() if v == max_votes]
        victim_id = random.choice(top)

    saved = victim_id is not None and victim_id == game.doctor_save
    if victim_id is not None and not saved:
        game.players[victim_id].alive = False

    lines = [f"☀️ الفجر أشرق - نهاية الليلة رقم {game.day_number}."]
    if victim_id is None:
        lines.append("لم يهاجم أحد الليلة الماضية.")
    elif saved:
        victim = game.players[victim_id]
        lines.append(f"💉 حاول المستذئبون قتل {victim.name}، لكن الطبيب أنقذه!")
    else:
        victim = game.players[victim_id]
        lines.append(f"💀 وُجد {victim.name} ({ROLE_NAMES[victim.role]}) مقتولًا هذا الصباح.")

    await context.bot.send_message(chat_id, "\n".join(lines))

    if await check_win(chat_id, context):
        return

    await start_discussion(chat_id, context)


# ------------------------------------------------------------------------
# مرحلة النقاش والتصويت النهاري
# ------------------------------------------------------------------------

async def start_discussion(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    game = GAMES.get(chat_id)
    game.phase = Phase.DAY_DISCUSSION
    alive_names = "، ".join(p.name for p in game.alive_players())
    await context.bot.send_message(
        chat_id,
        f"💬 وقت النقاش! ناقشوا من برأيكم المستذئب.\n"
        f"الأحياء: {alive_names}\n"
        f"لديكم {DISCUSSION_SECONDS} ثانية قبل بدء التصويت.",
    )
    context.job_queue.run_once(
        lambda ctx: start_vote_wrapper(chat_id, ctx),
        DISCUSSION_SECONDS,
        name=f"discussion-{chat_id}",
    )


async def start_vote_wrapper(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    await start_vote(chat_id, context)


async def start_vote(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    game = GAMES.get(chat_id)
    if not game:
        return
    game.phase = Phase.DAY_VOTE
    game.day_votes.clear()

    buttons = []
    for p in game.alive_players():
        buttons.append([InlineKeyboardButton(f"🗳️ {p.name}", callback_data=f"vote:{chat_id}:{p.user_id}")])
    msg = await context.bot.send_message(
        chat_id,
        f"🗳️ وقت التصويت! صوّتوا لطرد اللاعب الذي تشكّون فيه.\nلديكم {VOTE_SECONDS} ثانية.",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    game.vote_message_id = msg.message_id

    context.job_queue.run_once(
        lambda ctx: resolve_vote_wrapper(chat_id, ctx),
        VOTE_SECONDS,
        name=f"vote-{chat_id}",
    )


async def cb_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, chat_id_str, target_id_str = query.data.split(":")
    chat_id, target_id = int(chat_id_str), int(target_id_str)
    game = GAMES.get(chat_id)
    user_id = update.effective_user.id

    if not game or game.phase != Phase.DAY_VOTE:
        await query.answer("انتهى التصويت.", show_alert=True)
        return
    if user_id not in game.players or not game.players[user_id].alive:
        await query.answer("الأموات لا يصوّتون 👻", show_alert=True)
        return

    game.day_votes[user_id] = target_id
    await query.answer(f"✅ صوّتّ ضد {game.players[target_id].name}")


async def resolve_vote_wrapper(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    await resolve_vote(chat_id, context)


async def resolve_vote(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    game = GAMES.get(chat_id)
    if not game or game.phase != Phase.DAY_VOTE:
        return

    if not game.day_votes:
        await context.bot.send_message(chat_id, "🤷 لم يصوّت أحد، لن يُطرد أحد اليوم.")
    else:
        tally: Dict[int, int] = {}
        for target in game.day_votes.values():
            tally[target] = tally.get(target, 0) + 1
        max_votes = max(tally.values())
        top = [t for t, v in tally.items() if v == max_votes]

        if len(top) > 1:
            names = "، ".join(game.players[t].name for t in top)
            await context.bot.send_message(chat_id, f"⚖️ تعادل بين: {names}. لن يُطرد أحد اليوم.")
        else:
            eliminated = game.players[top[0]]
            eliminated.alive = False
            await context.bot.send_message(
                chat_id,
                f"🪦 قررت القرية طرد {eliminated.name}.\nكان دوره: {ROLE_NAMES[eliminated.role]}"
            )

    if await check_win(chat_id, context):
        return

    await start_night(chat_id, context)


# ------------------------------------------------------------------------
# فحص شرط الفوز
# ------------------------------------------------------------------------

async def check_win(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    game = GAMES.get(chat_id)
    if not game:
        return True

    wolves = len(game.alive_werewolves())
    others = len(game.alive_non_werewolves())

    if wolves == 0:
        await context.bot.send_message(chat_id, "🎉 تم القضاء على كل المستذئبين! فاز القرويون 👏")
        await announce_roles(chat_id, context)
        game.phase = Phase.ENDED
        del GAMES[chat_id]
        return True

    if wolves >= others:
        await context.bot.send_message(chat_id, "🐺 تفوّق المستذئبون عدديًا! فاز المستذئبون 🏆")
        await announce_roles(chat_id, context)
        game.phase = Phase.ENDED
        del GAMES[chat_id]
        return True

    return False


async def announce_roles(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    game = GAMES.get(chat_id)
    if not game:
        return
    lines = ["📋 كشف الأدوار:"]
    for p in game.players.values():
        status = "🟢 حي" if p.alive else "⚰️ ميت"
        lines.append(f"• {p.name}: {ROLE_NAMES[p.role]} ({status})")
    await context.bot.send_message(chat_id, "\n".join(lines))


# ------------------------------------------------------------------------
# التشغيل
# ------------------------------------------------------------------------

class _HealthHandler(BaseHTTPRequestHandler):
    """سيرفر HTTP بسيط جدًا فقط ليبقي البوت 'حيًا' على استضافات تتطلب فتح
    منفذ (Render مثلًا)، ولتستطيع خدمات مثل UptimeRobot الاتصال بالبوت
    كل بضع دقائق لمنعه من النوم."""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Werewolf bot is running.")

    def log_message(self, format, *args):
        return  # تعطيل سجلات HTTP الافتراضية


def keep_alive():
    server = HTTPServer(("0.0.0.0", PORT), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Health check server listening on port {PORT}")


def main():
    if BOT_TOKEN == "PUT_YOUR_TOKEN_HERE":
        raise SystemExit(
            "ضع توكن البوت في متغير البيئة BOT_TOKEN قبل التشغيل."
        )

    keep_alive()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("newgame", cmd_newgame))
    app.add_handler(CommandHandler("join", cmd_join))
    app.add_handler(CommandHandler("leave", cmd_leave))
    app.add_handler(CommandHandler("players", cmd_players))
    app.add_handler(CommandHandler("startgame", cmd_startgame))
    app.add_handler(CommandHandler("stopgame", cmd_stopgame))

    app.add_handler(CallbackQueryHandler(cb_night_action, pattern=r"^(kill|seer|save):"))
    app.add_handler(CallbackQueryHandler(cb_vote, pattern=r"^vote:"))

    logger.info("Werewolf bot starting (polling mode)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
