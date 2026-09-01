"""
Транскрипция видео с таймкодами. То же самое, что было в CLI-версии,
но оформлено как импортируемая функция для вызова из Celery-задачи.
"""

import threading

from faster_whisper import WhisperModel

_model_cache: dict[str, WhisperModel] = {}

# Whisper-модель НЕ вшита в инсталлятор (десятки-сотни МБ) — faster-whisper
# качает её сам при первом использовании и кэширует на диске. Загрузка может
# занять несколько минут на медленном интернете, и без индикатора это
# выглядит как зависшая транскрипция — см. GET /system/whisper-status в
# app/main.py, которое фронтенд поллит, чтобы показать понятное сообщение.
_download_state_lock = threading.Lock()
_download_state = {"downloading": False, "model_size": None}


def get_whisper_download_state() -> dict:
    with _download_state_lock:
        return dict(_download_state)


def _get_model(model_size: str, device: str) -> WhisperModel:
    """Кэшируем загруженную модель — иначе каждый вызов будет заново
    грузить веса в память, это дорого."""
    key = f"{model_size}:{device}"
    if key not in _model_cache:
        compute_type = "float16" if device == "cuda" else "int8"
        with _download_state_lock:
            _download_state["downloading"] = True
            _download_state["model_size"] = model_size
        try:
            _model_cache[key] = WhisperModel(model_size, device=device, compute_type=compute_type)
        finally:
            with _download_state_lock:
                _download_state["downloading"] = False
    return _model_cache[key]


def transcribe(video_path: str, model_size: str = "medium", device: str = "cpu", language: str | None = "ru") -> list[dict]:
    """
    Возвращает список сегментов: [{"start": .., "end": .., "text": ..}, ...]
    """
    model = _get_model(model_size, device)

    segments, _info = model.transcribe(
        video_path,
        language=language,
        word_timestamps=True,
        vad_filter=True,
    )

    return [
        {"start": round(seg.start, 2), "end": round(seg.end, 2), "text": seg.text.strip()}
        for seg in segments
    ]
