"""
منطق التنويع ومنع التكرار.

كل اختيار (سيناريو، موضوع فلسفي، قالب قرار، نوع نهاية...) يتجنب ما استُخدم
مؤخرًا في نفس المجموعة (chat_id)، بحيث لا تشعر كل جلسة لعب في مجموعة معيّنة
بأنها تكرار لسابقتها، مع بقاء كل مجموعة مستقلة عن غيرها تمامًا.
"""

import random

import db
from content_bank import (
    SCENARIOS,
    PHILOSOPHICAL_TOPICS,
    ROLE_NAME_POOL,
    DECISION_TEMPLATES,
    ENDING_TYPES,
)


async def pick_scenario(chat_id: int) -> dict:
    used = set(await db.get_recently_used(chat_id, "scenario", limit=8))
    pool = [s for s in SCENARIOS if s["id"] not in used] or SCENARIOS
    scenario = random.choice(pool)
    await db.mark_used(chat_id, "scenario", scenario["id"])
    return scenario


async def pick_philosophical_topic(chat_id: int) -> str:
    used = set(await db.get_recently_used(chat_id, "topic", limit=5))
    pool = [t for t in PHILOSOPHICAL_TOPICS if t not in used] or PHILOSOPHICAL_TOPICS
    topic = random.choice(pool)
    await db.mark_used(chat_id, "topic", topic)
    return topic


async def pick_decision_template(chat_id: int) -> dict:
    used = set(await db.get_recently_used(chat_id, "decision_template", limit=4))
    pool = [d for d in DECISION_TEMPLATES if d["type"] not in used] or DECISION_TEMPLATES
    template = random.choice(pool)
    await db.mark_used(chat_id, "decision_template", template["type"])
    return template


async def pick_ending_type(chat_id: int) -> str:
    used = set(await db.get_recently_used(chat_id, "ending_type", limit=3))
    pool = [e for e in ENDING_TYPES if e not in used] or ENDING_TYPES
    ending = random.choice(pool)
    await db.mark_used(chat_id, "ending_type", ending)
    return ending


def pick_role_names(count: int) -> list:
    pool = ROLE_NAME_POOL.copy()
    random.shuffle(pool)
    if count <= len(pool):
        return pool[:count]
    # إن زاد عدد اللاعبين عن الأدوار المتاحة، كرر الأسماء بأرقام مميزة
    return [f"{pool[i % len(pool)]} {i // len(pool) + 1}" for i in range(count)]


async def recent_ai_avoid_list(chat_id: int, content_type: str, limit: int = 12) -> list:
    return await db.get_recently_used(chat_id, content_type, limit=limit)


async def mark_ai_text_used(chat_id: int, content_type: str, text: str):
    key = (text or "").strip()[:120]
    if key:
        await db.mark_used(chat_id, content_type, key)


async def pick_unused(chat_id: int, content_type: str, pool: list, keep: int = 6):
    """يختار عنصرًا من pool مع تجنب ما استُخدم مؤخرًا، ويسجّل الاستخدام."""
    used = set(await db.get_recently_used(chat_id, content_type, limit=keep))
    candidates = [p for p in pool if (p if isinstance(p, str) else p[0])[:120] not in used] or pool
    choice = random.choice(candidates)
    key = choice if isinstance(choice, str) else choice[0]
    await db.mark_used(chat_id, content_type, key)
    return choice
