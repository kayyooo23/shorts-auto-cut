"""
Подбор рекомендованных хештегов под конкретный момент — анализирует его
текстовое содержимое (субтитры, hook_line, reason, которые уже есть в БД
после find_moments.py) и просит Claude предложить релевантные хештеги
под формат коротких вертикальных видео.
"""

import json
import re

import anthropic

from app.config import ANTHROPIC_API_KEY, CLAUDE_MODEL

SYSTEM_PROMPT = """\
Ты подбираешь хештеги для короткого вертикального видео (TikTok/YouTube \
Shorts/Instagram Reels) по его содержимому.

Правила:
- 8-12 хештегов
- смесь популярных широких тегов (#shorts, #юмор) и специфичных под тему \
конкретного видео — не только общие
- на русском языке, если контент на русском; общие теги вроде #shorts \
можно оставлять на английском
- без пробелов внутри тега, каждый начинается с #
- никаких пояснений — только сам список

Верни ТОЛЬКО валидный JSON-массив строк, без markdown-разметки:
["#тег1", "#тег2", ...]
"""


def suggest_hashtags(text: str, count: int = 10, model: str | None = None) -> list[str]:
    """
    text — содержимое момента (субтитры + краткое описание), по которому
    подбираются теги. Возвращает список строк вида "#тег".
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    model = model or CLAUDE_MODEL

    user_prompt = f"Содержимое видео:\n\n{text}\n\nПредложи {count} хештегов."

    response = client.messages.create(
        model=model,
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_text = "".join(b.text for b in response.content if b.type == "text").strip()
    raw_text = re.sub(r"^```json|```$", "", raw_text.strip()).strip()

    hashtags = json.loads(raw_text)

    # подчищаем на случай, если модель забыла '#' у части тегов
    return [h if h.startswith("#") else f"#{h}" for h in hashtags]
