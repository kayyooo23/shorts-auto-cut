"""
Рендер одного момента в готовый вертикальный shorts-файл: вырезка сегмента,
кроп/масштаб под 9:16, вшитые субтитры, наложение баннера, и произвольное
число дополнительных видео-дорожек (picture-in-picture) и аудио-дорожек
(музыка/звук), каждая со своими клипами — как в многодорожечном редакторе.

Всё делается одним вызовом ffmpeg (один проход перекодирования).
"""

import subprocess
from pathlib import Path

from app.config import FFMPEG_PATH, FFPROBE_PATH


class RenderError(Exception):
    pass


def _ffmpeg_filter_path(path: str) -> str:
    """
    Экранирует путь для подстановки внутрь значения фильтра ffmpeg
    (subtitles=...) — там ':' и '\\' значимы для парсера filtergraph, что
    на Windows ломает пути вида "C:\\Users\\...\\out.srt" (буква диска с
    двоеточием + обратные слэши): ffmpeg считает всё после первого ':'
    отдельной опцией фильтра вместо части пути.
    """
    return str(path).replace("\\", "/").replace(":", "\\:")


def _format_srt_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def subtitles_to_srt(subtitles: list[dict]) -> str:
    """
    subtitles: [{"start": 0.5, "end": 2.0, "text": "..."}, ...] — таймкоды
    ОТНОСИТЕЛЬНО начала момента (уже так и хранятся в БД, см. models.Subtitle).
    """
    lines = []
    for idx, sub in enumerate(subtitles, start=1):
        lines.append(str(idx))
        lines.append(f"{_format_srt_timestamp(sub['start'])} --> {_format_srt_timestamp(sub['end'])}")
        lines.append(sub["text"])
        lines.append("")
    return "\n".join(lines)


_BANNER_POSITION_EXPR = {
    "top-left": "20:20",
    "top-right": "W-w-20:20",
    "bottom-left": "20:H-h-20",
    "bottom-right": "W-w-20:H-h-20",
}


def _has_audio_stream(path: str) -> bool:
    result = subprocess.run(
        [FFPROBE_PATH, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", path],
        capture_output=True, text=True, timeout=30,
    )
    return bool(result.stdout.strip())


def render_moment(
    source_video_path: str,
    start: float,
    end: float,
    subtitles: list[dict],
    output_path: str,
    banner_path: str | None = None,
    banner_position: str = "bottom-right",
    tracks: list[dict] | None = None,
    target_width: int = 1080,
    target_height: int = 1920,
) -> None:
    """
    Рендерит один момент в готовый файл под shorts (вертикальный 9:16).

    tracks (опционально) — список дорожек как в многодорожечном редакторе:
        [{"type": "video"|"audio", "clips": [
            {"file_path": str, "trim_start": float, "trim_end": float,
             "position_start": float, "position_end": float,
             "volume": float,  # только для audio
             "pip_x": float, "pip_y": float, "pip_width": float, "pip_height": float},  # только для video
            ...
        ]}, ...]
    trim_* — какой кусок ИСХОДНОГО ФАЙЛА клипа используется.
    position_* — КОГДА клип показывается/звучит на шкале МОМЕНТА (0 = начало момента).
    Видео-клипы накладываются как picture-in-picture (pip_x/y/width/height —
    доли кадра 0.0-1.0), видимые только в своём окне [position_start, position_end].
    Аудио-клипы смешиваются с оригинальной звуковой дорожкой момента (или
    друг с другом, если у видео нет своего звука), сдвинутые по времени на
    position_start.

    Поднимает RenderError с сообщением ffmpeg при любой ошибке кодирования.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    tracks = tracks or []
    duration = end - start

    video_chain = ["crop=ih*9/16:ih:(iw-ih*9/16)/2:0", f"scale={target_width}:{target_height}"]

    srt_path = None
    if subtitles:
        srt_path = str(Path(output_path).with_suffix(".srt"))
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(subtitles_to_srt(subtitles))
        video_chain.append(
            f"subtitles='{_ffmpeg_filter_path(srt_path)}':force_style='FontSize=18,PrimaryColour=&HFFFFFF,BorderStyle=3,Outline=2'"
        )

    cmd = [FFMPEG_PATH, "-y", "-ss", str(start), "-to", str(end), "-i", source_video_path]
    next_input_idx = 1

    filter_parts = [f"[0:v]{','.join(video_chain)}[vbase]"]
    video_map = "[vbase]"

    if banner_path:
        cmd += ["-i", banner_path]
        banner_idx = next_input_idx
        next_input_idx += 1
        position = _BANNER_POSITION_EXPR.get(banner_position, _BANNER_POSITION_EXPR["bottom-right"])
        filter_parts.append(f"[vbase][{banner_idx}:v]overlay={position}[vbanner]")
        video_map = "[vbanner]"

    # ---------- Видео-дорожки (picture-in-picture) ----------
    video_tracks = [t for t in tracks if t["type"] == "video"]
    overlay_counter = 0
    for track in video_tracks:
        for clip in track["clips"]:
            cmd += ["-i", clip["file_path"]]
            clip_idx = next_input_idx
            next_input_idx += 1

            w = max(2, int(clip["pip_width"] * target_width) // 2 * 2)
            h = max(2, int(clip["pip_height"] * target_height) // 2 * 2)
            x = int(clip["pip_x"] * target_width)
            y = int(clip["pip_y"] * target_height)

            label_in = f"pipsrc{overlay_counter}"
            label_out = f"vout{overlay_counter}"
            filter_parts.append(
                f"[{clip_idx}:v]trim=start={clip['trim_start']}:end={clip['trim_end']},"
                f"setpts=PTS-STARTPTS+{clip['position_start']}/TB,scale={w}:{h}[{label_in}]"
            )
            filter_parts.append(
                f"{video_map}[{label_in}]overlay={x}:{y}:"
                f"enable='between(t,{clip['position_start']},{clip['position_end']})'[{label_out}]"
            )
            video_map = f"[{label_out}]"
            overlay_counter += 1

    # ---------- Аудио-дорожки ----------
    source_has_audio = _has_audio_stream(source_video_path)
    audio_tracks = [t for t in tracks if t["type"] == "audio"]
    has_overlay_audio = any(track["clips"] for track in audio_tracks)

    audio_map = None

    if not has_overlay_audio:
        # Нет дополнительных аудио-дорожек — просто пробрасываем оригинал как есть
        if source_has_audio:
            audio_map = "0:a"
    else:
        labels = ["[0:a]"] if source_has_audio else []
        mix_counter = 0
        for track in audio_tracks:
            for clip in track["clips"]:
                cmd += ["-i", clip["file_path"]]
                clip_idx = next_input_idx
                next_input_idx += 1

                delay_ms = int(clip["position_start"] * 1000)
                label = f"aov{mix_counter}"
                filter_parts.append(
                    f"[{clip_idx}:a]atrim=start={clip['trim_start']}:end={clip['trim_end']},"
                    f"asetpts=PTS-STARTPTS,volume={clip.get('volume', 1.0)},"
                    f"adelay={delay_ms}:all=1[{label}]"
                )
                labels.append(f"[{label}]")
                mix_counter += 1

        if len(labels) == 1:
            # ровно один источник звука (либо только оригинал, либо только
            # один оверлей без оригинала) — всё равно прогоняем через atrim,
            # чтобы гарантированно не превысить длительность видео
            filter_parts.append(f"{labels[0]}atrim=start=0:end={duration},asetpts=PTS-STARTPTS[outa]")
        else:
            inputs_str = "".join(labels)
            filter_parts.append(f"{inputs_str}amix=inputs={len(labels)}:duration=first:dropout_transition=0[amixed]")
            filter_parts.append(f"[amixed]atrim=start=0:end={duration},asetpts=PTS-STARTPTS[outa]")
        audio_map = "[outa]"

    filter_complex = ";".join(filter_parts)
    cmd += ["-filter_complex", filter_complex, "-map", video_map]
    if audio_map:
        cmd += ["-map", audio_map]

    cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "20"]
    if audio_map:
        cmd += ["-c:a", "aac", "-b:a", "128k"]
    cmd += [output_path]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if srt_path:
        Path(srt_path).unlink(missing_ok=True)

    if result.returncode != 0:
        raise RenderError(f"ffmpeg завершился с ошибкой (код {result.returncode}):\n{result.stderr[-2500:]}")

    if not Path(output_path).exists():
        raise RenderError("ffmpeg отработал без ошибки, но выходной файл не создан")
