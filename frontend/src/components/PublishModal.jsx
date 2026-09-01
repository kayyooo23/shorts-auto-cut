import { useEffect, useState } from 'react';
import { api, ApiError } from '../api/client';

export default function PublishModal({ moment, onClose, onPublished }) {
  const [accounts, setAccounts] = useState([]);
  const [drafts, setDrafts] = useState([]);
  const [selected, setSelected] = useState([]);
  const [uniqueize, setUniqueize] = useState(false);
  const [description, setDescription] = useState('');
  const [hashtags, setHashtags] = useState('');
  const [selectedDraftId, setSelectedDraftId] = useState('');
  const [savingDraft, setSavingDraft] = useState(false);
  const [newDraftName, setNewDraftName] = useState('');
  const [suggesting, setSuggesting] = useState(false);
  const [scheduleMode, setScheduleMode] = useState('now'); // 'now' | 'later'
  const [scheduledAt, setScheduledAt] = useState('');
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api.listSocialAccounts().then(setAccounts).catch(() => {});
    api.listHashtagDrafts().then(setDrafts).catch(() => {});
  }, []);

  async function handleSuggest() {
    setSuggesting(true);
    setError(null);
    try {
      const suggested = await api.suggestHashtags(moment.id);
      setHashtags(suggested.join(' '));
      setSelectedDraftId('');
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось подобрать хештеги');
    } finally {
      setSuggesting(false);
    }
  }

  function toggle(id) {
    setSelected((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));
  }

  function applyDraft(id) {
    setSelectedDraftId(id);
    const draft = drafts.find((d) => d.id === id);
    if (draft) setHashtags(draft.hashtags);
  }

  async function handleSaveDraft() {
    if (!newDraftName.trim() || !hashtags.trim()) {
      setError('Укажи название и хотя бы один хештег, чтобы сохранить черновик');
      return;
    }
    try {
      const draft = await api.createHashtagDraft(newDraftName.trim(), hashtags.trim());
      setDrafts((cur) => [draft, ...cur]);
      setSelectedDraftId(draft.id);
      setSavingDraft(false);
      setNewDraftName('');
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось сохранить черновик');
    }
  }

  async function handleDeleteDraft(id, e) {
    e.stopPropagation();
    await api.deleteHashtagDraft(id);
    setDrafts((cur) => cur.filter((d) => d.id !== id));
    if (selectedDraftId === id) setSelectedDraftId('');
  }

  async function handleSubmit() {
    if (selected.length === 0) {
      setError('Выбери хотя бы один аккаунт');
      return;
    }
    let scheduledAtIso = null;
    if (scheduleMode === 'later') {
      if (!scheduledAt) {
        setError('Укажи дату и время публикации');
        return;
      }
      const asDate = new Date(scheduledAt);
      if (asDate.getTime() <= Date.now()) {
        setError('Время публикации должно быть в будущем');
        return;
      }
      scheduledAtIso = asDate.toISOString();
    }

    setSubmitting(true);
    setError(null);
    try {
      await api.publishMoment(moment.id, {
        social_account_ids: selected,
        uniqueize,
        description: description.trim() || null,
        hashtags: hashtags.trim() || null,
        scheduled_at: scheduledAtIso,
      });
      await onPublished();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось опубликовать');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card modal-card-wide" onClick={(e) => e.stopPropagation()}>
        <h3 style={{ marginBottom: 4 }}>Опубликовать момент</h3>
        <p style={{ fontSize: 12, color: 'var(--text-soft)', marginBottom: 16 }}>
          Выбери аккаунты, на которые опубликовать этот рендер
        </p>

        {accounts.length === 0 ? (
          <p style={{ fontSize: 13, color: 'var(--text-faint)' }}>
            Нет подключённых аккаунтов. Подключи хотя бы один в разделе «Аккаунты».
          </p>
        ) : (
          <div className="account-checklist">
            {accounts.map((a) => (
              <label key={a.id} className="account-check-row">
                <input type="checkbox" checked={selected.includes(a.id)} onChange={() => toggle(a.id)} />
                <span className="tag tag-neutral">{a.platform}</span>
                <span style={{ fontSize: 13 }}>{a.platform_username || a.id.slice(0, 8)}</span>
              </label>
            ))}
          </div>
        )}

        <div className="prop-section-title" style={{ marginTop: 16 }}>Описание</div>
        <textarea
          className="publish-textarea"
          placeholder="Подпись к видео…"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />

        <div className="prop-section-title" style={{ marginTop: 12, display: 'flex', justifyContent: 'space-between' }}>
          <span>Хештеги</span>
          <span style={{ display: 'flex', gap: 10 }}>
            <span className="link-btn" onClick={suggesting ? undefined : handleSuggest} style={suggesting ? { opacity: 0.6, cursor: 'default' } : undefined}>
              {suggesting ? 'Подбираем…' : '✨ подобрать ИИ'}
            </span>
            {!savingDraft && (
              <span className="link-btn" onClick={() => setSavingDraft(true)}>+ сохранить как черновик</span>
            )}
          </span>
        </div>

        {drafts.length > 0 && (
          <select
            className="draft-select"
            value={selectedDraftId}
            onChange={(e) => applyDraft(e.target.value)}
          >
            <option value="">— выбрать черновик —</option>
            {drafts.map((d) => (
              <option key={d.id} value={d.id}>{d.name}</option>
            ))}
          </select>
        )}

        {drafts.length > 0 && (
          <div className="draft-chip-list">
            {drafts.map((d) => (
              <span key={d.id} className={`draft-chip${selectedDraftId === d.id ? ' active' : ''}`} onClick={() => applyDraft(d.id)}>
                {d.name}
                <button className="draft-chip-remove" onClick={(e) => handleDeleteDraft(d.id, e)} aria-label="Удалить черновик">×</button>
              </span>
            ))}
          </div>
        )}

        <textarea
          className="publish-textarea"
          placeholder="#юмор #сериал #shorts"
          value={hashtags}
          onChange={(e) => setHashtags(e.target.value)}
        />

        {savingDraft && (
          <div className="save-draft-row">
            <input
              type="text" placeholder="Название черновика" value={newDraftName}
              onChange={(e) => setNewDraftName(e.target.value)}
            />
            <button className="btn btn-ghost btn-sm" onClick={handleSaveDraft}>Сохранить</button>
            <button className="btn btn-ghost btn-sm" onClick={() => setSavingDraft(false)}>Отмена</button>
          </div>
        )}

        <label className="account-check-row" style={{ marginTop: 14 }}>
          <input type="checkbox" checked={uniqueize} onChange={(e) => setUniqueize(e.target.checked)} />
          <span style={{ fontSize: 13 }}>Уникализировать (разные копии для разных аккаунтов)</span>
        </label>

        <div className="prop-section-title" style={{ marginTop: 16 }}>Когда публиковать</div>
        <div className="schedule-toggle">
          <button
            type="button"
            className={`schedule-toggle-btn${scheduleMode === 'now' ? ' active' : ''}`}
            onClick={() => setScheduleMode('now')}
          >
            Сейчас
          </button>
          <button
            type="button"
            className={`schedule-toggle-btn${scheduleMode === 'later' ? ' active' : ''}`}
            onClick={() => setScheduleMode('later')}
          >
            Запланировать
          </button>
        </div>
        {scheduleMode === 'later' && (
          <input
            type="datetime-local"
            value={scheduledAt}
            onChange={(e) => setScheduledAt(e.target.value)}
            style={{ marginTop: 8, width: '100%' }}
          />
        )}

        {error && <div className="form-error" style={{ marginTop: 12 }}>{error}</div>}

        <div style={{ display: 'flex', gap: 8, marginTop: 20 }}>
          <button className="btn btn-ghost" onClick={onClose} style={{ flex: 1 }}>Отмена</button>
          <button className="btn btn-primary" onClick={handleSubmit} disabled={submitting} style={{ flex: 1 }}>
            {submitting ? 'Публикуем…' : scheduleMode === 'later' ? 'Запланировать' : 'Опубликовать'}
          </button>
        </div>
      </div>
    </div>
  );
}
