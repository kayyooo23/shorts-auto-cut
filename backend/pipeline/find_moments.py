"""
Поиск интересных моментов в транскрипте через Claude API.
Та же логика, что в CLI-версии, оформлена как функция.
"""

import json
import re

import anthropic

from app.config import CLAUDE_MODEL, get_anthropic_api_key


class MissingApiKeyError(Exception):
    """Anthropic API ключ не задан — поиск моментов недоступен, пока
    пользователь не впишет его на экране настроек (desktop-режим) или
    не задаст ANTHROPIC_API_KEY (облачный режим)."""
    pass

SYSTEM_PROMPT = """\
Ты — опытный монтажёр коротких видео (shorts/reels/tiktok). Тебе дают транскрипт \
эпизода с таймкодами. Твоя задача — найти фрагменты для нарезки в вертикальные \
короткие видео (30-60 секунд).

Критерии отбора:
- эмоциональный пик, конфликт, неожиданный поворот, шутка или яркая реплика
- фрагмент должен быть самодостаточным и понятным без контекста всего эпизода
- сильное начало (первые 2-3 секунды должны цеплять внимание)
- избегай фрагментов, которые обрываются на полуслове

Верни ТОЛЬКО валидный JSON без пояснений и markdown-разметки:

[
  {
    "start": 125.4,
    "end": 168.2,
    "reason": "краткое объяснение почему момент цепляет",
    "hook_line": "первая фраза для заголовка/затравки"
  }
]
"""


def _format_transcript(transcript: list[dict]) -> str:
    return "\n".join(f"[{seg['start']:.1f} - {seg['end']:.1f}] {seg['text']}" for seg in transcript)


def find_moments(transcript: list[dict], count: int = 6, model: str = None) -> list[dict]:
    api_key = get_anthropic_api_key()
    if not api_key:
        raise MissingApiKeyError(
            "Anthropic API ключ не задан — укажи его в Настройках, чтобы искать моменты."
        )
    client = anthropic.Anthropic(api_key=api_key)
    model = model or CLAUDE_MODEL

    user_prompt = (
        f"Вот транскрипт эпизода с таймкодами в секундах:\n\n{_format_transcript(transcript)}\n\n"
        f"Найди {count} лучших фрагментов для нарезки на shorts."
    )

    response = client.messages.create(
        model=model,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_text = "".join(b.text for b in response.content if b.type == "text").strip()
    raw_text = re.sub(r"^```json|```$", "", raw_text.strip()).strip()

    return json.loads(raw_text)


def build_subtitles_for_moment(transcript: list[dict], moment_start: float, moment_end: float) -> list[dict]:
    """
    Вырезает из полного транскрипта те реплики, что попадают в диапазон момента,
    и пересчитывает их таймкоды относительно начала момента (а не всего видео).
    Используется, чтобы сразу предзаполнить субтитры для каждого найденного фрагмента.
    """
    subtitles = []
    for seg in transcript:
        # берём сегменты, которые хотя бы частично пересекаются с моментом
        if seg["end"] <= moment_start or seg["start"] >= moment_end:
            continue
        rel_start = max(0.0, seg["start"] - moment_start)
        rel_end = min(moment_end - moment_start, seg["end"] - moment_start)
        subtitles.append({"start": round(rel_start, 2), "end": round(rel_end, 2), "text": seg["text"]})

    return subtitles
