"""
Уникализация видео перед публикацией: рандомизированный набор лёгких
визуальных/аудио-трансформаций, чтобы разные копии одного рендера (для
разных подключённых аккаунтов) не были побитово идентичны и не совпадали
по видео-хэшу платформы.

Важно понимать реалистично, что это даёт и чего не даёт:
- Снижает вероятность точного match'а по хэшу контента между копиями.
- НЕ гарантирует, что платформа не свяжет аккаунты по другим признакам
  (паттерны публикации, устройство/IP, поведенческие сигналы) и НЕ отменяет
  того, что массовая публикация похожего контента с разных аккаунтов
  одного человека нарушает пользовательские соглашения YouTube/TikTok/
  Instagram (политики про спам и множественные аккаунты). Это инструмент
  снижения технического дублирования, не защита от бана как таковая.

Каждый вызов apply_uniqueization() использует новый случайный набор
параметров в заданных безопасных для просмотра диапазонах — изменения
достаточно лёгкие, чтобы не быть заметными зрителю, но достаточные, чтобы
дать разный результат кодирования.
"""

import random
import subprocess
from pathlib import Path

from app.config import FFMPEG_PATH


class UniqueizeError(Exception):
    pass


def _random_params(seed: int | None = None) -> dict:
    rng = random.Random(seed)
    return {
        "flip": rng.random() < 0.5,
        "speed": round(rng.uniform(0.97, 1.05), 4),
        "zoom_percent": round(rng.uniform(1.5, 5.0), 2),        # кроп по краям, %
        "brightness": round(rng.uniform(-0.03, 0.03), 4),
        "contrast": round(rng.uniform(0.96, 1.05), 4),
        "saturation": round(rng.uniform(0.94, 1.08), 4),
        "noise_strength": rng.randint(3, 10),                    # noise=alls=N
        "pitch_semitones": round(rng.uniform(-0.6, 0.6), 3),      # едва заметный сдвиг тона
        "rotate_degrees": round(rng.uniform(-1.2, 1.2), 3),
    }


def apply_uniqueization(
    input_path: str,
    output_path: str,
    seed: int | None = None,
    strip_metadata: bool = True,
) -> dict:
    """
    Применяет случайный набор лёгких трансформаций к видео. Возвращает
    использованные параметры (полезно залогировать — на случай если
    понадобится объяснить, почему конкретная копия выглядит чуть иначе).

    seed: если задан — параметры детерминированы (для тестов); None —
    каждый вызов даёт новый случайный набор (обычный режим работы).
    """
    params = _random_params(seed)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Порядок фильтров важен: поворот генерирует чёрные поля по краям,
    # zoom/crop их обрезает; flip/eq/noise применяются к уже готовому кадру.
    video_filters = []

    if abs(params["rotate_degrees"]) > 0.01:
        deg = params["rotate_degrees"]
        video_filters.append(f"rotate={deg}*PI/180:fillcolor=black")

    zoom = params["zoom_percent"] / 100
    # обрезаем края (эффект лёгкого зума), затем масштабируем обратно —
    # iw/ih внутри scale здесь ссылаются на уже ОБРЕЗАННЫЙ кадр, поэтому
    # деление на (1-zoom) корректно возвращает исходный размер
    video_filters.append(f"crop=iw*(1-{zoom}):ih*(1-{zoom})")
    video_filters.append(f"scale=trunc(iw/(1-{zoom})/2)*2:trunc(ih/(1-{zoom})/2)*2")

    if params["flip"]:
        video_filters.append("hflip")

    video_filters.append(
        f"eq=brightness={params['brightness']}:contrast={params['contrast']}:saturation={params['saturation']}"
    )
    video_filters.append(f"noise=alls={params['noise_strength']}:allf=t")

    if abs(params["speed"] - 1.0) > 0.001:
        video_filters.append(f"setpts=PTS/{params['speed']}")

    cmd = [FFMPEG_PATH, "-y", "-i", input_path]

    audio_filters = []
    if abs(params["speed"] - 1.0) > 0.001:
        audio_filters.append(f"atempo={params['speed']}")
    if abs(params["pitch_semitones"]) > 0.01:
        pitch_scale = params["pitch_semitones"] / 12  # rubberband pitch= — множитель октавы
        audio_filters.append(f"rubberband=pitch={2 ** pitch_scale}")

    cmd += ["-vf", ",".join(video_filters)]
    if audio_filters:
        cmd += ["-af", ",".join(audio_filters)]

    if strip_metadata:
        cmd += ["-map_metadata", "-1"]

    cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "20", "-c:a", "aac", "-b:a", "128k", output_path]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        raise UniqueizeError(f"ffmpeg завершился с ошибкой (код {result.returncode}):\n{result.stderr[-2000:]}")
    if not Path(output_path).exists():
        raise UniqueizeError("ffmpeg отработал без ошибки, но выходной файл не создан")

    return params
