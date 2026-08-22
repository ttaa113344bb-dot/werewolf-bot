"""
إرسال آمن للرسائل عبر تيليجرام.

يُستخدم في كل مكان بدل bot.send_message مباشرة، لأنه:
- يقسّم أي رسالة أطول من حد تيليجرام (4096 حرفًا) إلى أجزاء متتالية.
- يتعامل مع تحديد المعدل (FloodWait / TelegramRetryAfter) بإعادة المحاولة
  تلقائيًا بعد الانتظار المطلوب، دون تجميد بقية البوت (الانتظار محلي
  لهذه المهمة فقط عبر asyncio.sleep).
- يمتص أي خطأ آخر من واجهة تيليجرام (حظر المستخدم للبوت، حذف الدردشة...)
  بحيث لا تتوقف اللعبة كاملة بسبب فشل إرسال رسالة واحدة.
"""

import asyncio
import logging

from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError, TelegramAPIError

logger = logging.getLogger("telegram_utils")

TELEGRAM_MESSAGE_LIMIT = 4096
_SAFE_CHUNK_SIZE = 3900  # هامش أمان تحت الحد الفعلي
MAX_FLOOD_RETRIES = 3


def _split_text(text: str, limit: int = _SAFE_CHUNK_SIZE) -> list:
    if len(text) <= limit:
        return [text]

    chunks = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind("\n", 0, limit)
        if cut == -1:
            cut = remaining.rfind(" ", 0, limit)
        if cut == -1 or cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


async def safe_send(bot, chat_id, text: str, **kwargs):
    """يرسل نصًا بأمان: يقسّمه إن كان طويلًا، ويعيد المحاولة عند تحديد المعدل،
    ولا يرفع استثناءً عند فشل الإرسال (يُسجَّل فقط في اللوج). يعيد True/False."""
    chunks = _split_text(text)
    ok = True
    for chunk in chunks:
        ok = await _send_with_retry(bot, chat_id, chunk, **kwargs) and ok
    return ok


async def _send_with_retry(bot, chat_id, text: str, **kwargs) -> bool:
    for attempt in range(MAX_FLOOD_RETRIES + 1):
        try:
            await bot.send_message(chat_id, text, **kwargs)
            return True
        except TelegramRetryAfter as exc:
            wait_for = getattr(exc, "retry_after", 3)
            logger.warning("Flood control: waiting %s seconds before retrying chat_id=%s", wait_for, chat_id)
            await asyncio.sleep(wait_for + 1)
        except TelegramForbiddenError:
            logger.info("Cannot message chat_id=%s (bot blocked or chat unreachable)", chat_id)
            return False
        except TelegramAPIError as exc:
            logger.warning("Telegram API error sending to chat_id=%s: %s", chat_id, exc)
            return False
        except Exception as exc:  # noqa: BLE001 - إرسال رسالة واحدة يجب ألا يوقف اللعبة أبدًا
            logger.warning("Unexpected error sending to chat_id=%s: %s", chat_id, exc)
            return False
    logger.error("Giving up sending message to chat_id=%s after repeated flood waits", chat_id)
    return False
