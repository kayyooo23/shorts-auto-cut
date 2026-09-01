import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, ApiError } from '../api/client';

function formatDate(iso) {
  return new Date(iso).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export default function ProjectsPage() {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState(null);
  const [draftNote, setDraftNote] = useState('');
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  async function load() {
    try {
      const data = await api.listProjects();
      setProjects(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось загрузить проекты');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  function startEditing(project) {
    setEditingId(project.id);
    setDraftNote(project.note || '');
  }

  async function saveNote(id) {
    try {
      await api.updateProject(id, { note: draftNote });
      setEditingId(null);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось сохранить заметку');
    }
  }

  async function handleDelete(id, e) {
    e.stopPropagation();
    await api.deleteProject(id);
    await load();
  }

  function openProject(project) {
    navigate(`/videos/${project.video_id}`);
  }

  if (loading) return <p style={{ color: 'var(--text-soft)' }}>Загружаем…</p>;

  return (
    <div>
      <h1 style={{ fontSize: 20, marginBottom: 4 }}>Проекты</h1>
      <p style={{ fontSize: 13, color: 'var(--text-faint)', marginBottom: 20 }}>
        Отложенные видео и моменты — с заметкой самому себе, чтобы вспомнить, на чём остановился
      </p>

      {error && <div className="form-error" style={{ marginBottom: 16 }}>{error}</div>}

      {projects.length === 0 ? (
        <div className="empty-state">
          <p>Пока нет отложенных проектов.</p>
          <p style={{ color: 'var(--text-faint)', fontSize: 13 }}>
            В редакторе момента есть кнопка «Отложить в проекты» — используй её, чтобы вернуться позже.
          </p>
        </div>
      ) : (
        <div className="project-list">
          {projects.map((p) => (
            <div key={p.id} className="project-card" onClick={() => openProject(p)}>
              <div className="project-card-header">
                <div>
                  <div className="project-card-title">{p.title || p.video.filename}</div>
                  <div className="project-card-meta mono">
                    {formatDate(p.updated_at)}
                    {p.moment && <span> · момент: {p.moment.hook_line || `${p.moment.start}–${p.moment.end}с`}</span>}
                  </div>
                </div>
                <button className="btn btn-danger btn-sm" onClick={(e) => handleDelete(p.id, e)}>Удалить</button>
              </div>

              {editingId === p.id ? (
                <div onClick={(e) => e.stopPropagation()}>
                  <textarea
                    className="publish-textarea"
                    value={draftNote}
                    onChange={(e) => setDraftNote(e.target.value)}
                    placeholder="Заметка самому себе…"
                    style={{ marginTop: 10 }}
                  />
                  <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                    <button className="btn btn-primary btn-sm" onClick={() => saveNote(p.id)}>Сохранить</button>
                    <button className="btn btn-ghost btn-sm" onClick={() => setEditingId(null)}>Отмена</button>
                  </div>
                </div>
              ) : (
                <div
                  className="project-card-note"
                  onClick={(e) => { e.stopPropagation(); startEditing(p); }}
                >
                  {p.note || <span style={{ color: 'var(--text-faint)' }}>+ добавить заметку</span>}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
