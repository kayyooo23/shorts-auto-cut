"""
Фоновые задачи:
  process_video               — транскрибировать видео → найти моменты → сохранить в БД.
  render_moment_task          — рендер момента через ffmpeg.
  publish_target               — опубликовать один рендер момента на одной платформе.
  dispatch_scheduled_publishes — Celery Beat: раз в минуту проверяет отложенные публикации.

Каждая задача разбита на "core"-функцию (чистая бизнес-логика, без Celery
self/retry) и тонкую Celery-обёртку. Core-функция также регистрируется как
локальная реализация через job_runner.register_local() — так одна и та же
логика работает и через Celery (SaaS), и в пуле потоков (desktop),
см. app/job_runner.py.
"""

import json
import time
import traceback
from datetime import datetime
from pathlib import Path

from app.celery_app import celery_app
from app.config import (
    WHISPER_MODEL_SIZE, WHISPER_DEVICE, DEFAULT_MOMENTS_COUNT, OUTPUTS_DIR,
)
from app.database import SessionLocal
from app.models import Video, Moment, Subtitle, VideoStatus, PublishTarget, PublishStatus, Platform, MomentStatus
from pipeline.transcribe import transcribe
from pipeline.find_moments import find_moments, build_subtitles_for_moment
from pipeline.render import render_moment, RenderError
from pipeline.uniqueize import apply_uniqueization
from app.publishers import get_publisher
from app.publishers.base import PublishError
from app.job_runner import register_local, dispatch


def _retry_sync(fn, *args, exc_types, max_retries: int, delay_seconds: float):
    """
    Простой синхронный retry для локального (desktop) режима — заменяет
    Celery self.retry()/max_retries для случаев, когда брокера нет вообще.
    Выполняется прямо в фоновом потоке, поэтому time.sleep() здесь не
    блокирует ничего, кроме этого одного потока из пула.
    """
    attempt = 0
    while True:
        try:
            return fn(*args)
        except exc_types:
            attempt += 1
            if attempt > max_retries:
                raise
            time.sleep(delay_seconds)


# ---------- process_video ----------

def _process_video_core(video_id: str) -> None:
    db = SessionLocal()
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if video is None:
            return

        # --- Шаг 1: транскрипция ---
        video.status = VideoStatus.TRANSCRIBING
        db.commit()

        transcript = transcribe(video.filepath, model_size=WHISPER_MODEL_SIZE, device=WHISPER_DEVICE)

        transcript_path = OUTPUTS_DIR / f"{video.id}_transcript.json"
        transcript_path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
        video.transcript_path = str(transcript_path)
        db.commit()

        # --- Шаг 2: поиск моментов ---
        video.status = VideoStatus.FINDING_MOMENTS
        db.commit()

        moments_data = find_moments(transcript, count=DEFAULT_MOMENTS_COUNT)

        for m in moments_data:
            moment = Moment(
                video_id=video.id,
                start=m["start"],
                end=m["end"],
                reason=m.get("reason"),
                hook_line=m.get("hook_line"),
            )
            db.add(moment)
            db.flush()  # чтобы получить moment.id для субтитров

            subs = build_subtitles_for_moment(transcript, m["start"], m["end"])
            for idx, s in enumerate(subs):
                db.add(Subtitle(
                    moment_id=moment.id,
                    start=s["start"],
                    end=s["end"],
                    text=s["text"],
                    order_index=idx,
                ))

        video.status = VideoStatus.READY
        db.commit()

    except Exception as e:
        db.rollback()
        video = db.query(Video).filter(Video.id == video_id).first()
        if video:
            video.status = VideoStatus.FAILED
            video.error_message = f"{e}\n{traceback.format_exc()}"
            db.commit()
        raise
    finally:
        db.close()


@celery_app.task(bind=True)
def process_video(self, video_id: str):
    _process_video_core(video_id)


register_local(process_video.name)(_process_video_core)


# ---------- render_moment_task ----------

def _render_moment_core(moment_id: str) -> None:
    db = SessionLocal()
    try:
        moment = db.query(Moment).filter(Moment.id == moment_id).first()
        if moment is None:
            return

        if moment.status != MomentStatus.APPROVED:
            raise RenderError(f"Момент должен быть в статусе approved для рендера, сейчас: {moment.status}")

        video = moment.video
        subtitles = [
            {"start": s.start, "end": s.end, "text": s.text}
            for s in sorted(moment.subtitles, key=lambda s: s.order_index)
        ]

        output_path = str(OUTPUTS_DIR / f"{moment.id}_rendered.mp4")

        tracks_payload = [
            {
                "type": track.type.value,
                "clips": [
                    {
                        "file_path": clip.file_path,
                        "trim_start": clip.trim_start,
                        "trim_end": clip.trim_end,
                        "position_start": clip.position_start,
                        "position_end": clip.position_end,
                        "volume": clip.volume,
                        "pip_x": clip.pip_x,
                        "pip_y": clip.pip_y,
                        "pip_width": clip.pip_width,
                        "pip_height": clip.pip_height,
                    }
                    for clip in track.clips
                ],
            }
            for track in moment.tracks
        ]

        render_moment(
            source_video_path=video.filepath,
            start=moment.start,
            end=moment.end,
            subtitles=subtitles,
            output_path=output_path,
            banner_path=moment.banner_path,
            banner_position=moment.banner_position,
            tracks=tracks_payload,
        )

        moment.output_path = output_path
        moment.status = MomentStatus.RENDERED
        db.commit()

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def render_moment_task(self, moment_id: str):
    """
    Рендерит одобренный момент в готовый вертикальный файл (ffmpeg):
    вырезка из исходного видео, вшитые субтитры, наложение баннера.
    Момент должен быть в статусе APPROVED. По завершении переводит его
    в RENDERED и заполняет output_path — после этого момент готов к
    /moments/{id}/publish.
    """
    try:
        _render_moment_core(moment_id)
    except RenderError as e:
        raise self.retry(exc=e)


def _render_moment_local(moment_id: str) -> None:
    _retry_sync(_render_moment_core, moment_id, exc_types=RenderError, max_retries=2, delay_seconds=30)


register_local(render_moment_task.name)(_render_moment_local)


# ---------- publish_target ----------

def _publish_target_core(target_id: str) -> None:
    """
    Публикует один PublishTarget на своей платформе. Требует, чтобы момент
    уже был отрендерен (moment.output_path заполнен ffmpeg-задачей рендера).

    Если target.uniqueize=True — перед загрузкой генерируется отдельная
    случайно уникализированная копия рендера (pipeline/uniqueize.py) под
    именно ЭТОТ таргет, так что разные аккаунты не публикуют побитово
    идентичный файл. Временный файл удаляется после попытки публикации
    независимо от её исхода.

    Instagram — особый случай: publishers/instagram.py ожидает публичный URL,
    а не локальный путь. Если PUBLIC_STORAGE_BASE_URL не настроен, публикация
    в Instagram завершится ошибкой с понятным сообщением — это ожидаемо,
    пока рендеры не выгружаются на публичное хранилище (S3 и т.п.).
    """
    db = SessionLocal()
    temp_uniqueized_path = None
    try:
        target = db.query(PublishTarget).filter(PublishTarget.id == target_id).first()
        if target is None:
            return

        moment = target.moment
        if not moment.output_path:
            target.status = PublishStatus.FAILED
            target.error_message = "Момент ещё не отрендерен (нет output_path)"
            db.commit()
            return

        target.status = PublishStatus.PUBLISHING
        db.commit()

        video_path = moment.output_path

        if target.uniqueize:
            temp_uniqueized_path = str(OUTPUTS_DIR / f"{target.id}_unique.mp4")
            apply_uniqueization(video_path, temp_uniqueized_path)
            video_path = temp_uniqueized_path

        if target.platform == Platform.INSTAGRAM:
            from app.config import PUBLIC_STORAGE_BASE_URL
            if not PUBLIC_STORAGE_BASE_URL:
                raise PublishError(
                    "PUBLIC_STORAGE_BASE_URL не настроен — Instagram требует "
                    "публичную ссылку на видео, локальный путь не подойдёт"
                )
            video_path = f"{PUBLIC_STORAGE_BASE_URL}/{video_path}"

        publisher = get_publisher(target.social_account)

        # Хештеги — отдельное поле в UI (и в PublishTarget) для удобства
        # редактирования, но платформы не различают "описание" и "хештеги"
        # как разные сущности — это всё один текст подписи, поэтому
        # склеиваем их непосредственно перед загрузкой.
        full_description = target.description or ""
        if target.hashtags:
            full_description = f"{full_description}\n\n{target.hashtags}".strip()

        result = publisher.upload(
            video_path=video_path,
            title=target.title or moment.hook_line or "",
            description=full_description,
        )

        target.status = PublishStatus.PUBLISHED
        target.remote_id = result.remote_id
        target.remote_url = result.remote_url
        target.published_at = datetime.utcnow()
        target.error_message = None
        db.commit()

    except PublishError as e:
        db.rollback()
        target = db.query(PublishTarget).filter(PublishTarget.id == target_id).first()
        if target:
            target.status = PublishStatus.FAILED
            target.error_message = str(e)
            db.commit()
        raise
    except Exception as e:
        db.rollback()
        target = db.query(PublishTarget).filter(PublishTarget.id == target_id).first()
        if target:
            target.status = PublishStatus.FAILED
            target.error_message = f"{e}\n{traceback.format_exc()}"
            db.commit()
        raise
    finally:
        if temp_uniqueized_path:
            Path(temp_uniqueized_path).unlink(missing_ok=True)
        db.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def publish_target(self, target_id: str):
    try:
        _publish_target_core(target_id)
    except PublishError as e:
        raise self.retry(exc=e)


def _publish_target_local(target_id: str) -> None:
    _retry_sync(_publish_target_core, target_id, exc_types=PublishError, max_retries=3, delay_seconds=60)


register_local(publish_target.name)(_publish_target_local)


# ---------- dispatch_scheduled_publishes ----------

def _dispatch_scheduled_publishes_core() -> dict:
    """
    Находит PublishTarget со status=QUEUED и scheduled_at <= сейчас, и
    ставит их в очередь на реальную публикацию через job_runner.dispatch()
    (работает одинаково что в Celery-режиме, что в локальном).

    Защита от повторной отправки: статус меняется на PUBLISHING сразу,
    ОДНИМ bulk-update внутри одной транзакции, ДО постановки в очередь.
    """
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        due_targets = (
            db.query(PublishTarget)
            .filter(PublishTarget.status == PublishStatus.QUEUED, PublishTarget.scheduled_at <= now)
            .all()
        )

        due_ids = [t.id for t in due_targets]
        if not due_ids:
            return {"dispatched": 0}

        for t in due_targets:
            t.status = PublishStatus.PUBLISHING
        db.commit()

        for target_id in due_ids:
            dispatch(publish_target, target_id)

        return {"dispatched": len(due_ids)}
    finally:
        db.close()


@celery_app.task
def dispatch_scheduled_publishes():
    return _dispatch_scheduled_publishes_core()


register_local(dispatch_scheduled_publishes.name)(lambda: _dispatch_scheduled_publishes_core())
