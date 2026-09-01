import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, ApiError } from '../api/client';
import PublishModal from '../components/PublishModal';
import { MomentBlock, ClipBlock } from '../components/TimelineBlocks';

function formatTime(seconds) {
  if (seconds == null) return '00:00';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

/** "мм:сс" или "сс" (число секунд) -> секунды. Возвращает null, если не удалось разобрать. */
function parseTimeInput(value) {
  const trimmed = value.trim();
  if (/^\d+(\.\d+)?$/.test(trimmed)) return parseFloat(trimmed);
  const match = trimmed.match(/^(\d+):(\d{1,2}(?:\.\d+)?)$/);
  if (!match) return null;
  const minutes = parseInt(match[1], 10);
  const seconds = parseFloat(match[2]);
  return minutes * 60 + seconds;
}

const BANNER_POSITIONS = ['top-left', 'top-right', 'bottom-left', 'bottom-right'];

export default function EditorPage() {
  const { videoId } = useParams();
  const [video, setVideo] = useState(null);
  const [selectedMomentId, setSelectedMomentId] = useState(null);
  const [error, setError] = useState(null);
  const videoRef = useRef(null);
  const [previewTime, setPreviewTime] = useState(0);
  const [busy, setBusy] = useState(false);
  const [publishOpen, setPublishOpen] = useState(false);
  const [saveProjectOpen, setSaveProjectOpen] = useState(false);
  const [projectNote, setProjectNote] = useState('');
  const [savingProject, setSavingProject] = useState(false);
  const [uploadingAsset, setUploadingAsset] = useState(null); // 'banner' | trackId | null
  const [selectedClipId, setSelectedClipId] = useState(null);

  const [whisperDownloading, setWhisperDownloading] = useState(false);

  const load = useCallback(async () => {
    const data = await api.getVideo(videoId);
    setVideo(data);
    setSelectedMomentId((current) => current || data.moments[0]?.id || null);
  }, [videoId]);

  useEffect(() => { load(); }, [load]);

  // Пока видео транскрибируется/ищутся моменты — поллим статус, чтобы
  // редактор сам обновился, когда обработка закончится (без ручного F5).
  // Отдельно поллим /system/whisper-status: первая транскрипция может
  // скачивать модель распознавания речи несколько минут — без этого
  // индикатора это выглядит как зависший процесс без объяснений.
  useEffect(() => {
    if (!video || ['ready', 'failed'].includes(video.status)) return;
    const interval = setInterval(async () => {
      load().catch(() => {});
      if (video.status === 'transcribing') {
        try {
          const s = await api.getWhisperStatus();
          setWhisperDownloading(s.downloading);
        } catch {
          /* не критично — просто не покажем индикатор */
        }
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [video, load]);
  useEffect(() => { setSelectedClipId(null); }, [selectedMomentId]);

  // При переключении на другой момент того же видео перематываем плеер
  // к началу нового момента — иначе он останется там, где был.
  useEffect(() => {
    if (videoRef.current && selectedMomentId) {
      const moment = video?.moments.find((m) => m.id === selectedMomentId);
      if (moment) {
        videoRef.current.currentTime = moment.start;
        videoRef.current.play().catch(() => {});
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedMomentId]);

  const selectedMoment = useMemo(
    () => video?.moments.find((m) => m.id === selectedMomentId) || null,
    [video, selectedMomentId]
  );

  // Горячие клавиши: пробел — пауза/воспроизведение, стрелки — перемотка
  // (Shift — крупный шаг), Delete/Backspace — удалить выбранный клип,
  // Escape — снять выделение. Не срабатывают, пока фокус в текстовом поле —
  // иначе пробел при вводе таймкода перематывал бы видео вместо ввода символа.
  useEffect(() => {
    function handleKeyDown(e) {
      const tag = e.target.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA') return;

      const v = videoRef.current;

      if (e.code === 'Space') {
        e.preventDefault();
        if (!v) return;
        if (v.paused) v.play().catch(() => {}); else v.pause();
      } else if (e.code === 'ArrowLeft') {
        e.preventDefault();
        if (!v || !selectedMoment) return;
        const step = e.shiftKey ? 5 : 1;
        v.currentTime = Math.max(selectedMoment.start, v.currentTime - step);
      } else if (e.code === 'ArrowRight') {
        e.preventDefault();
        if (!v || !selectedMoment) return;
        const step = e.shiftKey ? 5 : 1;
        v.currentTime = Math.min(selectedMoment.end, v.currentTime + step);
      } else if (e.code === 'Delete' || e.code === 'Backspace') {
        if (selectedClipId) {
          e.preventDefault();
          handleDeleteClip(selectedClipId);
          setSelectedClipId(null);
        }
      } else if (e.code === 'Escape') {
        setSelectedClipId(null);
      }
    }

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedMoment, selectedClipId]);

  // Текущий субтитр для наложения поверх видео — subtitle.start/end хранятся
  // ОТНОСИТЕЛЬНО начала момента, а previewTime — это currentTime плеера
  // относительно ВСЕГО исходного файла, поэтому сравниваем со сдвигом.
  const activeSubtitle = useMemo(() => {
    if (!selectedMoment) return null;
    const relativeTime = previewTime - selectedMoment.start;
    return selectedMoment.subtitles.find((s) => relativeTime >= s.start && relativeTime <= s.end) || null;
  }, [selectedMoment, previewTime]);

  async function updateMoment(patch) {
    if (!selectedMoment) return;
    setBusy(true);
    setError(null);
    try {
      await api.updateMoment(selectedMoment.id, patch);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось обновить момент');
    } finally {
      setBusy(false);
    }
  }

  async function updateSubtitle(id, patch) {
    setBusy(true);
    try {
      await api.updateSubtitle(id, patch);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось обновить субтитр');
    } finally {
      setBusy(false);
    }
  }

  async function handleAddSubtitle() {
    if (!selectedMoment) return;
    const last = [...selectedMoment.subtitles].sort((a, b) => a.start - b.start).pop();
    const start = last ? last.end : 0;
    const end = start + 2;
    setBusy(true);
    setError(null);
    try {
      await api.createSubtitle(selectedMoment.id, { start, end, text: 'Новая реплика' });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось добавить субтитр');
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteSubtitle(id) {
    setBusy(true);
    setError(null);
    try {
      await api.deleteSubtitle(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось удалить субтитр');
    } finally {
      setBusy(false);
    }
  }

  function handleTimecodeBlur(field, rawValue) {
    const seconds = parseTimeInput(rawValue);
    if (seconds == null) {
      setError('Таймкод должен быть в формате мм:сс или числом секунд');
      return;
    }
    updateMoment({ [field]: seconds });
  }

  async function handleUploadBanner(e) {
    const file = e.target.files?.[0];
    if (!file || !selectedMoment) return;
    setUploadingAsset('banner');
    setError(null);
    try {
      await api.uploadBanner(selectedMoment.id, file);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось загрузить баннер');
    } finally {
      setUploadingAsset(null);
      e.target.value = '';
    }
  }

  async function handleDeleteBanner() {
    if (!selectedMoment) return;
    setBusy(true);
    try {
      await api.deleteBanner(selectedMoment.id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось удалить баннер');
    } finally {
      setBusy(false);
    }
  }

  async function handleAddTrack(type) {
    if (!selectedMoment) return;
    setBusy(true);
    setError(null);
    try {
      await api.createTrack(selectedMoment.id, type);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось создать дорожку');
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteTrack(trackId) {
    setBusy(true);
    setError(null);
    try {
      await api.deleteTrack(trackId);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось удалить дорожку');
    } finally {
      setBusy(false);
    }
  }

  async function handleUploadClip(trackId, e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadingAsset(trackId);
    setError(null);
    try {
      await api.uploadClip(trackId, file);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось загрузить клип');
    } finally {
      setUploadingAsset(null);
      e.target.value = '';
    }
  }

  async function handleUpdateClip(clipId, patch) {
    setBusy(true);
    setError(null);
    try {
      await api.updateClip(clipId, patch);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось обновить клип');
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteClip(clipId) {
    setBusy(true);
    setError(null);
    try {
      await api.deleteClip(clipId);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось удалить клип');
    } finally {
      setBusy(false);
    }
  }

  function handleClipTimeBlur(clipId, field, rawValue) {
    const seconds = parseTimeInput(rawValue);
    if (seconds == null) {
      setError('Таймкод должен быть в формате мм:сс или числом секунд');
      return;
    }
    handleUpdateClip(clipId, { [field]: seconds });
  }

  async function handleApprove() {
    await updateMoment({ status: 'approved' });
  }

  async function handleRender() {
    if (!selectedMoment) return;
    setBusy(true);
    setError(null);
    try {
      await api.renderMoment(selectedMoment.id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось запустить рендер');
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveProject() {
    setSavingProject(true);
    setError(null);
    try {
      await api.createProject({
        video_id: video.id,
        moment_id: selectedMoment?.id || null,
        note: projectNote.trim() || null,
      });
      setSaveProjectOpen(false);
      setProjectNote('');
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось сохранить проект');
    } finally {
      setSavingProject(false);
    }
  }

  if (!video) return <p style={{ color: 'var(--text-soft)' }}>Загружаем…</p>;

  if (video.status === 'failed') {
    const isMissingKey = (video.error_message || '').includes('API ключ не задан');
    return (
      <div className="empty-state">
        <p style={{ color: 'var(--danger)' }}>Не удалось обработать видео.</p>
        <p style={{ color: 'var(--text-faint)', fontSize: 13, maxWidth: 480, whiteSpace: 'pre-wrap' }}>
          {isMissingKey
            ? 'Не задан Anthropic API ключ — без него поиск моментов не работает.'
            : (video.error_message || '').split('\n')[0]}
        </p>
        {isMissingKey && (
          <Link to="/settings" className="btn btn-primary" style={{ marginTop: 12 }}>Указать ключ в Настройках</Link>
        )}
      </div>
    );
  }

  if (video.status !== 'ready') {
    const PROCESSING_LABELS = {
      uploaded: 'В очереди на обработку…',
      transcribing: 'Распознаём речь…',
      finding_moments: 'Ищем яркие моменты…',
    };
    return (
      <div className="empty-state">
        <p>{PROCESSING_LABELS[video.status] || 'Обрабатываем видео…'}</p>
        {whisperDownloading && (
          <p style={{ color: 'var(--text-faint)', fontSize: 13, maxWidth: 480 }}>
            Скачивается модель распознавания речи — в первый раз это может занять
            несколько минут в зависимости от скорости интернета. Дальше будет быстрее,
            модель скачивается один раз.
          </p>
        )}
      </div>
    );
  }

  const duration = video.duration_seconds || 1;

  return (
    <div className="editor-screen">
      <div className="editor-topline">
        <span className="mono" style={{ color: 'var(--text-faint)', fontSize: 12 }}>{video.filename}</span>
        {error && <div className="form-error">{error}</div>}
      </div>

      <div className="editor-workspace">
        <div className="preview-area">
          {selectedMoment ? (
            <div className="frame-916">
              <video
                ref={videoRef}
                key={video.id}
                src={api.getVideoFileUrl(video.id)}
                className="preview-video"
                controls
                autoPlay
                muted
                onLoadedMetadata={(e) => {
                  e.target.currentTime = selectedMoment.start;
                  e.target.play().catch(() => {});
                }}
                onTimeUpdate={(e) => {
                  const t = e.target.currentTime;
                  setPreviewTime(t);
                  if (t >= selectedMoment.end || t < selectedMoment.start) {
                    e.target.currentTime = selectedMoment.start;
                  }
                }}
              />
              {activeSubtitle && (
                <div className="preview-caption">{activeSubtitle.text}</div>
              )}
              {selectedMoment.banner_path && (
                <img
                  key={selectedMoment.banner_path}
                  src={api.getBannerFileUrl(selectedMoment.id)}
                  className={`preview-banner-img pos-${selectedMoment.banner_position}`}
                  alt="Баннер"
                />
              )}
              <div className="timecode">
                <span>{formatTime(selectedMoment.start)}</span>
                <span>{formatTime(selectedMoment.end)}</span>
              </div>
            </div>
          ) : (
            <p style={{ color: 'var(--text-faint)' }}>Нет моментов — дождись окончания обработки видео</p>
          )}
        </div>

        {selectedMoment && (
          <div className="properties">
            <div>
              <div className="prop-section-title">Таймкоды момента</div>
              <div className="timecode-edit-row" key={`${selectedMoment.id}-${selectedMoment.start}-${selectedMoment.end}`}>
                <input
                  type="text" className="timecode-input mono" defaultValue={formatTime(selectedMoment.start)}
                  onBlur={(e) => handleTimecodeBlur('start', e.target.value)}
                />
                <span style={{ color: 'var(--text-faint)' }}>–</span>
                <input
                  type="text" className="timecode-input mono" defaultValue={formatTime(selectedMoment.end)}
                  onBlur={(e) => handleTimecodeBlur('end', e.target.value)}
                />
              </div>
            </div>

            <div>
              <div className="prop-section-title" style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Субтитры</span>
                <span className="link-btn" onClick={handleAddSubtitle}>+ добавить</span>
              </div>
              {selectedMoment.subtitles.length === 0 && (
                <p style={{ fontSize: 12, color: 'var(--text-faint)' }}>Субтитров нет</p>
              )}
              {selectedMoment.subtitles.map((s) => (
                <div className="subtitle-row" key={s.id}>
                  <div className="subtitle-row-main">
                    <div className="subtitle-timecode-edit">
                      <input
                        type="text" className="timecode-input-sm mono" defaultValue={formatTime(s.start)}
                        onBlur={(e) => {
                          const val = parseTimeInput(e.target.value);
                          if (val != null) updateSubtitle(s.id, { start: val });
                        }}
                      />
                      <span style={{ color: 'var(--text-faint)', fontSize: 10 }}>–</span>
                      <input
                        type="text" className="timecode-input-sm mono" defaultValue={formatTime(s.end)}
                        onBlur={(e) => {
                          const val = parseTimeInput(e.target.value);
                          if (val != null) updateSubtitle(s.id, { end: val });
                        }}
                      />
                    </div>
                    <textarea
                      className="subtitle-text-input"
                      defaultValue={s.text}
                      onBlur={(e) => {
                        if (e.target.value !== s.text) updateSubtitle(s.id, { text: e.target.value });
                      }}
                    />
                  </div>
                  <button className="subtitle-delete-btn" onClick={() => handleDeleteSubtitle(s.id)} aria-label="Удалить реплику">×</button>
                </div>
              ))}
            </div>

            <div>
              <div className="prop-section-title" style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Позиция баннера</span>
                <label className="link-btn" style={{ cursor: 'pointer' }}>
                  {uploadingAsset === 'banner' ? 'Загрузка…' : selectedMoment.banner_path ? 'Заменить' : '+ загрузить'}
                  <input type="file" accept="image/png,image/jpeg,image/webp" style={{ display: 'none' }} onChange={handleUploadBanner} />
                </label>
              </div>
              {selectedMoment.banner_path && (
                <div className="asset-chip">
                  <span>Баннер загружен</span>
                  <button className="asset-chip-remove" onClick={handleDeleteBanner} aria-label="Удалить баннер">×</button>
                </div>
              )}
              <div className="banner-positions">
                {BANNER_POSITIONS.map((pos) => (
                  <button
                    key={pos}
                    className={`banner-pos-btn${selectedMoment.banner_position === pos ? ' active' : ''}`}
                    onClick={() => updateMoment({ banner_position: pos })}
                  >
                    <div className={`banner-pos-dot pos-${pos}`} />
                  </button>
                ))}
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 'auto' }}>
              {selectedMoment.status === 'pending' && (
                <button className="btn btn-primary" disabled={busy} onClick={handleApprove}>Одобрить</button>
              )}
              {selectedMoment.status === 'approved' && (
                <button className="btn btn-primary" disabled={busy} onClick={handleRender}>Рендерить</button>
              )}
              {selectedMoment.status === 'rendered' && (
                <button className="btn btn-primary" disabled={busy} onClick={() => setPublishOpen(true)}>Опубликовать</button>
              )}
              {!['pending', 'approved', 'rendered'].includes(selectedMoment.status) && (
                <span className="tag tag-neutral" style={{ justifyContent: 'center' }}>{selectedMoment.status}</span>
              )}
              <button className="btn btn-ghost" onClick={() => setSaveProjectOpen(true)}>
                Отложить в проекты
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="bottom-zone">
        <div className="moments-strip">
          {video.moments.map((m) => (
            <button
              key={m.id}
              className={`moment-card${m.id === selectedMomentId ? ' active' : ''}`}
              onClick={() => setSelectedMomentId(m.id)}
            >
              <img className="moment-thumb" src={api.getMomentThumbnailUrl(m.id)} alt="" loading="lazy" />
              <div className="moment-card-text">
                <div className="moment-card-title">{m.hook_line || 'Момент'}</div>
                <div className="moment-card-time mono">{formatTime(m.start)}–{formatTime(m.end)}</div>
              </div>
            </button>
          ))}
        </div>

        <div className="timeline-panel">
          <div className="timeline-ruler mono">
            {Array.from({ length: 6 }, (_, i) => (
              <span key={i}>{formatTime((duration / 5) * i)}</span>
            ))}
          </div>
          <div
            className="timeline-track"
            onClick={(e) => {
              // клик по пустому месту таймлайна — перемотка; клик по
              // существующему moment-block обрабатывается им самим
              // (stopPropagation там нет, но MomentBlock вызывает onSelect,
              // а сюда событие всплывает уже после — поэтому дополнительно
              // не перематываем, если target это сам блок)
              if (e.target.closest('.moment-block')) return;
              const rect = e.currentTarget.getBoundingClientRect();
              const fraction = (e.clientX - rect.left) / rect.width;
              const targetTime = Math.max(0, Math.min(duration, fraction * duration));
              if (videoRef.current) videoRef.current.currentTime = targetTime;
            }}
          >
            <div className="timeline-ticks" />
            <div className="timeline-playhead" style={{ left: `${(previewTime / duration) * 100}%` }} />
            {video.moments.map((m) => (
              <MomentBlock
                key={m.id}
                moment={m}
                videoDuration={duration}
                isActive={m.id === selectedMomentId}
                onSelect={() => setSelectedMomentId(m.id)}
                onCommitResize={(start, end) => updateMoment({ start, end })}
              />
            ))}
          </div>
        </div>

        {selectedMoment && (
          <div className="tracks-panel">
            <div className="tracks-panel-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                <span className="tracks-panel-title">Дорожки момента</span>
                <span className="shortcuts-hint mono" title="Пробел — пауза/воспроизведение · ←/→ — перемотка (Shift — на 5с) · Delete — удалить выбранный клип · Esc — снять выделение">
                  ⌘ пробел · ←→ · del · esc
                </span>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => handleAddTrack('video')}>+ видео-дорожка</button>
                <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => handleAddTrack('audio')}>+ аудио-дорожка</button>
              </div>
            </div>

            {/* Базовая видео-дорожка — сам момент, всегда снизу по стеку,
                неинтерактивная (это не Track/Clip, а само исходное видео) */}
            <div className="track-row">
              <div className="track-row-label">
                <span className="tag tag-neutral" style={{ fontSize: 9 }}>video</span>
                <span>Оригинал</span>
              </div>
              <div className="track-row-lane">
                <div className="track-clip-block track-clip-base" style={{ left: 0, width: '100%' }}>
                  {video.filename}
                </div>
              </div>
            </div>

            {selectedMoment.tracks.map((track) => {
              const momentDuration = selectedMoment.end - selectedMoment.start;
              return (
                <div className="track-row" key={track.id}>
                  <div className="track-row-label">
                    <span className={`tag ${track.type === 'video' ? 'tag-progress' : 'tag-success'}`} style={{ fontSize: 9 }}>
                      {track.type}
                    </span>
                    <span>{track.name || (track.type === 'video' ? 'Наложение видео' : 'Звук')}</span>
                    <button className="track-row-delete" onClick={() => handleDeleteTrack(track.id)} aria-label="Удалить дорожку">×</button>
                  </div>
                  <div className="track-row-lane">
                    {track.clips.length === 0 ? (
                      <label className="track-empty-upload">
                        {uploadingAsset === track.id ? 'Загрузка…' : '+ загрузить клип'}
                        <input
                          type="file"
                          accept={track.type === 'video' ? 'video/mp4,video/quicktime,video/webm' : 'audio/mpeg,audio/wav,audio/mp4,audio/aac,audio/ogg'}
                          style={{ display: 'none' }}
                          onChange={(e) => handleUploadClip(track.id, e)}
                        />
                      </label>
                    ) : (
                      track.clips.map((clip) => (
                        <ClipBlock
                          key={clip.id}
                          clip={{ ...clip, _trackType: track.type, _thumbnailUrl: track.type === 'video' ? api.getClipThumbnailUrl(clip.id) : null }}
                          momentDuration={momentDuration}
                          isSelected={selectedClipId === clip.id}
                          onSelect={() => setSelectedClipId(selectedClipId === clip.id ? null : clip.id)}
                          onCommitChange={(result) => handleUpdateClip(clip.id, result)}
                        />
                      ))
                    )}
                  </div>

                  {selectedClipId && track.clips.some((c) => c.id === selectedClipId) && (() => {
                    const clip = track.clips.find((c) => c.id === selectedClipId);
                    return (
                      <div
                        className="clip-editor"
                        key={`${clip.id}-${clip.position_start}-${clip.position_end}-${clip.trim_start}-${clip.trim_end}`}
                      >
                        <div className="clip-editor-row">
                          <label>Позиция на моменте</label>
                          <input type="text" className="timecode-input-sm mono" defaultValue={formatTime(clip.position_start)}
                            onBlur={(e) => handleClipTimeBlur(clip.id, 'position_start', e.target.value)} />
                          <span className="mono" style={{ fontSize: 10 }}>–</span>
                          <input type="text" className="timecode-input-sm mono" defaultValue={formatTime(clip.position_end)}
                            onBlur={(e) => handleClipTimeBlur(clip.id, 'position_end', e.target.value)} />
                        </div>
                        <div className="clip-editor-row">
                          <label>Обрезка исходника</label>
                          <input type="text" className="timecode-input-sm mono" defaultValue={formatTime(clip.trim_start)}
                            onBlur={(e) => handleClipTimeBlur(clip.id, 'trim_start', e.target.value)} />
                          <span className="mono" style={{ fontSize: 10 }}>–</span>
                          <input type="text" className="timecode-input-sm mono" defaultValue={formatTime(clip.trim_end)}
                            onBlur={(e) => handleClipTimeBlur(clip.id, 'trim_end', e.target.value)} />
                          <span className="mono" style={{ fontSize: 10, color: 'var(--text-faint)' }}>из {formatTime(clip.source_duration)}</span>
                        </div>
                        {track.type === 'audio' && (
                          <div className="clip-editor-row">
                            <label>Громкость</label>
                            <input type="range" min="0" max="1" step="0.05" defaultValue={clip.volume}
                              onMouseUp={(e) => handleUpdateClip(clip.id, { volume: parseFloat(e.target.value) })}
                              onTouchEnd={(e) => handleUpdateClip(clip.id, { volume: parseFloat(e.target.value) })}
                              style={{ flex: 1 }} />
                            <span className="mono" style={{ fontSize: 10 }}>{Math.round(clip.volume * 100)}%</span>
                          </div>
                        )}
                        <button className="btn btn-danger btn-sm" onClick={() => { handleDeleteClip(clip.id); setSelectedClipId(null); }}>
                          Удалить клип
                        </button>
                      </div>
                    );
                  })()}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {publishOpen && selectedMoment && (
        <PublishModal moment={selectedMoment} onClose={() => setPublishOpen(false)} onPublished={load} />
      )}

      {saveProjectOpen && (
        <div className="modal-overlay" onClick={() => setSaveProjectOpen(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <h3 style={{ marginBottom: 4 }}>Отложить в проекты</h3>
            <p style={{ fontSize: 12, color: 'var(--text-soft)', marginBottom: 16 }}>
              {selectedMoment
                ? 'Сохранится именно этот момент — вернёшься прямо к нему.'
                : 'Сохранится видео целиком.'}
            </p>
            <textarea
              className="publish-textarea"
              placeholder="Заметка самому себе (необязательно)…"
              value={projectNote}
              onChange={(e) => setProjectNote(e.target.value)}
              autoFocus
            />
            <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
              <button className="btn btn-ghost" onClick={() => setSaveProjectOpen(false)} style={{ flex: 1 }}>Отмена</button>
              <button className="btn btn-primary" onClick={handleSaveProject} disabled={savingProject} style={{ flex: 1 }}>
                {savingProject ? 'Сохраняем…' : 'Сохранить'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
