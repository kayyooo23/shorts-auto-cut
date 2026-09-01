import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, ApiError } from '../api/client';

const STATUS_LABELS = {
  uploaded: { label: 'В очереди', tag: 'tag-neutral' },
  transcribing: { label: 'Транскрибируем', tag: 'tag-progress' },
  finding_moments: { label: 'Ищем моменты', tag: 'tag-progress' },
  ready: { label: 'Готово', tag: 'tag-success' },
  failed: { label: 'Ошибка', tag: 'tag-error' },
};

export default function VideosPage() {
  const [videos, setVideos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploadError, setUploadError] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(null);
  const fileInputRef = useRef(null);
  const navigate = useNavigate();

  const loadVideos = useCallback(async () => {
    try {
      const data = await api.listVideos();
      setVideos(data);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadVideos();
    // Поллинг: пока хотя бы одно видео обрабатывается — обновляем список раз в 3с
    const interval = setInterval(() => {
      setVideos((current) => {
        const stillProcessing = current.some((v) => !['ready', 'failed'].includes(v.status));
        if (stillProcessing) loadVideos();
        return current;
      });
    }, 3000);
    return () => clearInterval(interval);
  }, [loadVideos]);

  async function handleFileChange(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadError(null);
    setUploadProgress(0);
    try {
      const result = await api.uploadVideo(file, setUploadProgress);
      setUploadProgress(null);
      await loadVideos();
      navigate(`/videos/${result.video.id}`);
    } catch (err) {
      setUploadProgress(null);
      setUploadError(err instanceof ApiError ? err.detail : 'Не удалось загрузить видео');
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h1 style={{ fontSize: 20 }}>Мои видео</h1>
        <div>
          <input
            ref={fileInputRef} type="file" accept="video/mp4,video/quicktime,video/x-matroska,video/avi,video/webm"
            style={{ display: 'none' }} onChange={handleFileChange}
          />
          <button className="btn btn-primary" onClick={() => fileInputRef.current?.click()} disabled={uploadProgress !== null}>
            {uploadProgress !== null ? `Загрузка ${uploadProgress}%` : '+ Загрузить видео'}
          </button>
        </div>
      </div>

      {uploadError && <div className="form-error" style={{ marginBottom: 16 }}>{uploadError}</div>}

      {loading ? (
        <p style={{ color: 'var(--text-soft)' }}>Загружаем список…</p>
      ) : videos.length === 0 ? (
        <div className="empty-state">
          <p>Пока нет загруженных видео.</p>
          <p style={{ color: 'var(--text-faint)', fontSize: 13 }}>Загрузи первое — и найдём яркие моменты автоматически.</p>
        </div>
      ) : (
        <div className="video-grid">
          {videos.map((v) => {
            const status = STATUS_LABELS[v.status] || STATUS_LABELS.uploaded;
            return (
              <div key={v.id} className="video-card" onClick={() => navigate(`/videos/${v.id}`)}>
                <div className="video-card-thumb">
                  <img src={api.getVideoThumbnailUrl(v.id)} alt="" loading="lazy" />
                  <span className={`tag ${status.tag} video-card-status`}>
                    <span className="tag-dot" /> {status.label}
                  </span>
                </div>
                <div className="video-card-info">
                  <div className="video-card-name">{v.filename}</div>
                  <span className="mono video-card-date">
                    {new Date(v.created_at).toLocaleDateString('ru-RU')}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
