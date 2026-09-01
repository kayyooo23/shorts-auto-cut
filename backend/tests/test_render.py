"""
Тесты рендера гоняются реальным ffmpeg на реально сгенерированных файлах —
не моки. Это осознанно: рендер — единственное место в приложении, где
"код без ошибок" и "код, который работает" могут заметно разойтись
(проблемы с фильтрами ffmpeg проявляются только на реальном вызове).
"""

import subprocess

import pytest

from pipeline.render import render_moment, subtitles_to_srt, RenderError


@pytest.fixture(scope="module")
def source_video(tmp_path_factory):
    path = tmp_path_factory.mktemp("render_src") / "source.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=640x480:duration=8:rate=15",
         "-c:v", "libx264", str(path)],
        capture_output=True, check=True,
    )
    return str(path)


@pytest.fixture(scope="module")
def banner_image(tmp_path_factory):
    path = tmp_path_factory.mktemp("render_banner") / "banner.png"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=100x50", "-frames:v", "1", str(path)],
        capture_output=True, check=True,
    )
    return str(path)


def test_subtitles_to_srt_format():
    srt = subtitles_to_srt([{"start": 0.5, "end": 2.25, "text": "Привет"}])
    assert "00:00:00,500 --> 00:00:02,250" in srt
    assert "Привет" in srt


def test_render_produces_valid_output(tmp_path, source_video):
    output_path = str(tmp_path / "out.mp4")
    render_moment(
        source_video_path=source_video,
        start=1.0, end=4.0,
        subtitles=[{"start": 0.2, "end": 1.5, "text": "Тест"}],
        output_path=output_path,
    )

    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", output_path],
        capture_output=True, text=True,
    )
    duration = float(result.stdout.strip())
    assert abs(duration - 3.0) < 0.3  # 4.0 - 1.0 = 3 секунды


def test_render_output_is_vertical_9_16(tmp_path, source_video):
    output_path = str(tmp_path / "out_vertical.mp4")
    render_moment(
        source_video_path=source_video,
        start=0.0, end=2.0,
        subtitles=[],
        output_path=output_path,
    )

    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", output_path],
        capture_output=True, text=True,
    )
    width, height = map(int, result.stdout.strip().split(","))
    assert width == 1080
    assert height == 1920


def test_render_with_banner_succeeds(tmp_path, source_video, banner_image):
    output_path = str(tmp_path / "out_banner.mp4")
    render_moment(
        source_video_path=source_video,
        start=0.0, end=2.0,
        subtitles=[],
        output_path=output_path,
        banner_path=banner_image,
        banner_position="top-left",
    )
    import os
    assert os.path.exists(output_path)
    assert os.path.getsize(output_path) > 0


def test_render_invalid_source_raises_render_error(tmp_path):
    with pytest.raises(RenderError):
        render_moment(
            source_video_path="/nonexistent/file.mp4",
            start=0.0, end=2.0,
            subtitles=[],
            output_path=str(tmp_path / "out.mp4"),
        )


def test_render_task_rejects_non_approved_moment(client, register_and_login, source_video):
    """Celery-задача рендера должна отказаться рендерить момент, который
    пользователь ещё не одобрил в редакторе."""
    from app.models import User, Video, Moment, VideoStatus, MomentStatus
    from app.database import SessionLocal
    from app.tasks import render_moment_task

    headers, _tokens, email = register_and_login()

    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    video = Video(owner_id=user.id, filename="e.mp4", filepath=source_video, status=VideoStatus.READY)
    db.add(video); db.flush()
    moment = Moment(video_id=video.id, start=0, end=2, status=MomentStatus.PENDING)  # НЕ approved
    db.add(moment); db.flush()
    moment_id = moment.id
    db.commit()
    db.close()

    with pytest.raises(Exception):
        render_moment_task.run(moment_id)


def test_render_endpoint_requires_approved_status(client, register_and_login, source_video):
    from app.models import User, Video, Moment, VideoStatus, MomentStatus
    from app.database import SessionLocal

    headers, _tokens, email = register_and_login()

    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    video = Video(owner_id=user.id, filename="e.mp4", filepath=source_video, status=VideoStatus.READY)
    db.add(video); db.flush()
    moment = Moment(video_id=video.id, start=0, end=2, status=MomentStatus.PENDING)
    db.add(moment); db.flush()
    moment_id = moment.id
    db.commit()
    db.close()

    r = client.post(f"/moments/{moment_id}/render", headers=headers)
    assert r.status_code == 400


def test_full_pipeline_approve_render_via_api(client, register_and_login, source_video):
    """Сквозной тест через API: момент approved -> POST /render -> задача
    выполняется синхронно (моки Celery.delay отключены здесь намеренно) ->
    проверяем, что после ручного запуска .run() статус и файл появляются."""
    from app.models import User, Video, Moment, VideoStatus, MomentStatus
    from app.database import SessionLocal
    from app.tasks import render_moment_task

    headers, _tokens, email = register_and_login()

    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    video = Video(owner_id=user.id, filename="e.mp4", filepath=source_video, status=VideoStatus.READY)
    db.add(video); db.flush()
    moment = Moment(video_id=video.id, start=0, end=2, status=MomentStatus.APPROVED)
    db.add(moment); db.flush()
    moment_id = moment.id
    db.commit()
    db.close()

    r = client.post(f"/moments/{moment_id}/render", headers=headers)
    assert r.status_code == 200  # задача поставлена (delay замокан в conftest)

    # выполняем задачу по-настоящему, синхронно, чтобы проверить результат
    render_moment_task.run(moment_id)

    db = SessionLocal()
    m = db.query(Moment).filter(Moment.id == moment_id).first()
    assert m.status == MomentStatus.RENDERED
    assert m.output_path is not None
    import os
    assert os.path.exists(m.output_path)
    db.close()
