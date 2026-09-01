import { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { api, ApiError } from '../api/client';

export default function ProfilePage() {
  const { user } = useAuth();

  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  if (!user) return null;

  async function handleChangePassword(e) {
    e.preventDefault();
    setError(null);
    setSuccess(false);

    if (newPassword.length < 8) {
      setError('Новый пароль должен быть не короче 8 символов');
      return;
    }
    if (newPassword !== confirmPassword) {
      setError('Пароли не совпадают');
      return;
    }

    setLoading(true);
    try {
      await api.changePassword(currentPassword, newPassword);
      setSuccess(true);
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось сменить пароль');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <h1 style={{ fontSize: 20, marginBottom: 20 }}>Профиль</h1>

      <div className="video-list" style={{ marginBottom: 28 }}>
        <div className="video-row" style={{ cursor: 'default' }}>
          <span style={{ flex: 1, color: 'var(--text-soft)' }}>Email</span>
          <span>{user.email}</span>
        </div>
        <div className="video-row" style={{ cursor: 'default' }}>
          <span style={{ flex: 1, color: 'var(--text-soft)' }}>Зарегистрирован</span>
          <span className="mono">{new Date(user.created_at).toLocaleDateString('ru-RU')}</span>
        </div>
      </div>

      <div className="prop-section-title" style={{ marginBottom: 12 }}>Смена пароля</div>
      <form onSubmit={handleChangePassword} className="panel" style={{ padding: 20, maxWidth: 360 }}>
        <label className="field-label">Текущий пароль</label>
        <input
          type="password" required value={currentPassword}
          onChange={(e) => setCurrentPassword(e.target.value)}
          style={{ width: '100%', marginBottom: 12 }}
        />

        <label className="field-label">Новый пароль</label>
        <input
          type="password" required value={newPassword} placeholder="Минимум 8 символов"
          onChange={(e) => setNewPassword(e.target.value)}
          style={{ width: '100%', marginBottom: 12 }}
        />

        <label className="field-label">Повтори новый пароль</label>
        <input
          type="password" required value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          style={{ width: '100%', marginBottom: 12 }}
        />

        {error && <div className="form-error" style={{ marginBottom: 12 }}>{error}</div>}
        {success && (
          <div className="form-success" style={{ marginBottom: 12 }}>
            Пароль изменён. Все другие устройства вышли из аккаунта.
          </div>
        )}

        <button className="btn btn-primary" type="submit" disabled={loading}>
          {loading ? 'Сохраняем…' : 'Сменить пароль'}
        </button>
      </form>
    </div>
  );
}
