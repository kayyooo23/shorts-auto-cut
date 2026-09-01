import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { api, ApiError } from '../api/client';

function AnthropicKeySection() {
  // Эндпоинт есть только в desktop-сборке (RUNNER_MODE=local) — в облаке
  // ключ задаётся через переменную окружения при деплое. 404 здесь
  // означает "не desktop", а не ошибку — просто не показываем секцию.
  const [available, setAvailable] = useState(false);
  const [isSet, setIsSet] = useState(false);
  const [value, setValue] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [keyError, setKeyError] = useState(null);

  useEffect(() => {
    api.getAnthropicKeyStatus()
      .then((data) => { setAvailable(true); setIsSet(data.is_set); })
      .catch(() => setAvailable(false));
  }, []);

  async function handleSave(e) {
    e.preventDefault();
    if (!value.trim()) return;
    setSaving(true);
    setKeyError(null);
    setSaved(false);
    try {
      await api.setAnthropicKey(value.trim());
      setIsSet(true);
      setSaved(true);
      setValue('');
    } catch (err) {
      setKeyError(err instanceof ApiError ? err.detail : 'Не удалось сохранить ключ');
    } finally {
      setSaving(false);
    }
  }

  if (!available) return null;

  return (
    <div className="panel" style={{ padding: 20, maxWidth: 440, marginBottom: 20 }}>
      <h3 style={{ fontSize: 14, marginBottom: 6 }}>Anthropic API ключ</h3>
      <p style={{ fontSize: 12, color: 'var(--text-soft)', marginBottom: 12 }}>
        Нужен для поиска ярких моментов в видео и подбора хештегов через Claude.
        Без ключа остальное (загрузка, редактирование, публикация) работает как обычно —
        просто эти две функции честно скажут, что ключ не задан.
        Получить ключ можно в консоли Anthropic (console.anthropic.com).
      </p>

      {isSet && !saved && (
        <div className="tag tag-success" style={{ marginBottom: 12, display: 'inline-flex' }}>
          <span className="tag-dot" /> Ключ сохранён
        </div>
      )}
      {saved && (
        <div className="tag tag-success" style={{ marginBottom: 12, display: 'inline-flex' }}>
          <span className="tag-dot" /> Сохранено
        </div>
      )}

      <form onSubmit={handleSave}>
        <label className="field-label">{isSet ? 'Заменить ключ' : 'Ключ'}</label>
        <input
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="sk-ant-..."
          style={{ width: '100%', marginBottom: 12 }}
        />
        {keyError && <div className="form-error" style={{ marginBottom: 12 }}>{keyError}</div>}
        <button type="submit" className="btn btn-primary" disabled={saving || !value.trim()}>
          {saving ? 'Сохраняем…' : 'Сохранить'}
        </button>
      </form>
    </div>
  );
}

export default function SettingsPage() {
  const { logout } = useAuth();
  const navigate = useNavigate();

  const [confirming, setConfirming] = useState(false);
  const [password, setPassword] = useState('');
  const [confirmText, setConfirmText] = useState('');
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const canDelete = password.length > 0 && confirmText.trim().toUpperCase() === 'УДАЛИТЬ';

  async function handleDelete(e) {
    e.preventDefault();
    if (!canDelete) return;

    setLoading(true);
    setError(null);
    try {
      await api.deleteAccount(password);
      await logout();
      navigate('/login');
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось удалить аккаунт');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <h1 style={{ fontSize: 20, marginBottom: 20 }}>Настройки</h1>

      <AnthropicKeySection />

      <div className="prop-section-title" style={{ color: 'var(--danger)', marginBottom: 12 }}>
        Опасная зона
      </div>

      <div className="panel" style={{ padding: 20, maxWidth: 440, borderColor: 'var(--danger)' }}>
        <h3 style={{ fontSize: 14, marginBottom: 6 }}>Удалить аккаунт</h3>
        <p style={{ fontSize: 12, color: 'var(--text-soft)', marginBottom: 16 }}>
          Необратимо удаляет аккаунт и всё, что с ним связано: видео, моменты, субтитры,
          дорожки и клипы, подключённые соцаккаунты, черновики хештегов, проекты. Отменить
          нельзя.
        </p>

        {!confirming ? (
          <button className="btn btn-danger" onClick={() => setConfirming(true)}>
            Удалить аккаунт
          </button>
        ) : (
          <form onSubmit={handleDelete}>
            <label className="field-label">Текущий пароль</label>
            <input
              type="password" required value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={{ width: '100%', marginBottom: 12 }}
            />

            <label className="field-label">
              Напиши <b>УДАЛИТЬ</b>, чтобы подтвердить
            </label>
            <input
              type="text" required value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              style={{ width: '100%', marginBottom: 12 }}
            />

            {error && <div className="form-error" style={{ marginBottom: 12 }}>{error}</div>}

            <div style={{ display: 'flex', gap: 8 }}>
              <button
                type="button" className="btn btn-ghost"
                onClick={() => { setConfirming(false); setPassword(''); setConfirmText(''); setError(null); }}
              >
                Отмена
              </button>
              <button type="submit" className="btn btn-danger" disabled={!canDelete || loading}>
                {loading ? 'Удаляем…' : 'Удалить аккаунт навсегда'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
