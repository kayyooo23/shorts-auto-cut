"""
Транскрипция видео с таймкодами. То же самое, что было в CLI-версии,
но оформлено как импортируемая функция для вызова из Celery-задачи.
"""

from faster_whisper import WhisperModel

_model_cache: dict[str, WhisperModel] = {}


def _get_model(model_size: str, device: str) -> WhisperModel:
    """Кэшируем загруженную модель — иначе каждый вызов будет заново
    грузить веса в память, это дорого."""
    key = f"{model_size}:{device}"
    if key not in _model_cache:
        compute_type = "float16" if device == "cuda" else "int8"
        _model_cache[key] = WhisperModel(model_size, device=device, compute_type=compute_type)
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
