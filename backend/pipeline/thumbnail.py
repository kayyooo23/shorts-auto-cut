"""
Извлекает кадр из видео в заданный момент времени через ffmpeg — для
миниатюр на карточках моментов/клипов в редакторе (вместо чёрных
прямоугольников-заглушек).

Кэшируется на диске по хешу (путь_к_файлу, время) — повторный запрос той
же миниатюры не гоняет ffmpeg заново.
"""

import hashlib
import subprocess
from pathlib import Path

from app.config import OUTPUTS_DIR, FFMPEG_PATH


class ThumbnailError(Exception):
    pass


def get_or_create_thumbnail(source_path: str, time_seconds: float) -> str:
    key = hashlib.sha256(f"{source_path}:{time_seconds:.2f}".encode()).hexdigest()[:20]
    thumb_path = OUTPUTS_DIR / f"thumb_{key}.jpg"

    if thumb_path.exists():
        return str(thumb_path)

    result = subprocess.run(
        [FFMPEG_PATH, "-y", "-ss", str(max(time_seconds, 0)), "-i", source_path,
         "-frames:v", "1", "-q:v", "3", str(thumb_path)],
        capture_output=True, text=True, timeout=30,
    )

    if result.returncode != 0 or not thumb_path.exists():
        raise ThumbnailError(f"Не удалось извлечь кадр: {result.stderr[-500:]}")

    return str(thumb_path)
